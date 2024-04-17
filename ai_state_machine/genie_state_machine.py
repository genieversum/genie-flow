import logging
from typing import Optional

from celery import chain, group, Task
from celery.canvas import Signature
from jinja2 import Template
from loguru import logger
from pydantic import BaseModel, Field
from pydantic_redis import Model
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from ai_state_machine.model import DialogueElement, DialogueFormat, CompositeTemplateType, \
    CompositeContentType
from ai_state_machine.celery_tasks import call_llm_api, combine_group_to_dict, trigger_ai_event
from ai_state_machine.store import get_fully_qualified_name_from_class


class GenieModel(Model):
    """
    The base model for all models that will carry data in the dialogue. Contains the attributes
    that are required and expected by the `GenieStateMachine` such as `state` and `session_id`/

    This class also carries the dialogue - a list of `DialogueElement`s of the previous chat.

    And it carries a number of state-dependent attributes that are important to the progress of
    the dialogue, such as `running_task_id` which indicates if there is a currently running task,
    as well as `actor` and `actor_text`, both indicators for the most recent interaction.

    This class is a subclass of the pydantic_redis `Model` class, which makes it possible to
    persist the values into Reids and retrieve it again by its primary key. The attribute
    `_primary_key_field` is used to determine the name of the primary key.
    """
    _primary_key_field: str = "session_id"

    state: str | int | None = Field(
        None,
        description="The current state that this model is in, represented by the value of the state"
    )
    session_id: str = Field(
        description="The ID of the session this claims belongs to."
    )
    dialogue: list[DialogueElement] = Field(
        default_factory=list,
        description="The list of dialogue elements that have been used in the dialogue so far",
    )
    running_task_id: Optional[str] = Field(
        None,
        description="the (Celery) task id of the currently running task",
    )
    actor: Optional[str] = Field(
        None,
        description="The actor that has created the current input",
    )
    actor_input: str = Field(
        "",
        description="the most recent received input from the actor",
    )

    @property
    def state_machine_class(self) -> type["GenieStateMachine"]:
        """
        Property that returns the class of the state machine that this model should be
        managed by.
        """
        raise NotImplementedError()

    def create_state_machine(self) -> "GenieStateMachine":
        """
        Create and return a newly instantiated state machine, of the appropirate class,
        that manages this instance of a model.
        """
        return self.state_machine_class(model=self)

    @property
    def current_response(self) -> Optional[DialogueElement]:
        """
        Return the most recent `DialogueElement` from the dialogue list.
        """
        return self.dialogue[-1] if len(self.dialogue) > 0 else None

    def format_dialogue(self, target_format: DialogueFormat) -> str:
        """
        Apply the given target format to the dialogue of this instance.
        """
        return DialogueFormat.format(self.dialogue, target_format)


class GenieStateMachine(StateMachine):

    def __init__(
            self,
            model: GenieModel,
            new_session: bool = False,
            user_actor_name: str = "USER",
            ai_actor_name: str = "LLM",
            templates_property_name: str = "templates"
    ):
        self._user_actor_name = user_actor_name
        self._ai_actor_name = ai_actor_name
        self.templates_property_name = templates_property_name

        self.current_template: Optional[CompositeTemplateType] = None
        super(GenieStateMachine, self).__init__(model=model)

        templates = getattr(self, templates_property_name)
        missing_templates = [
            state.id
            for state in self.states
            if state.id not in templates
        ]
        if missing_templates:
            raise ValueError(f"Missing templates for states: {', '.join(missing_templates)}")

        if new_session:
            initial_prompt = self.get_target_rendering(self.current_state)
            self.model.dialogue.append(
                DialogueElement(
                    actor=self._ai_actor_name,
                    actor_text=initial_prompt,
                )
            )

    @property
    def render_data(self) -> dict[str, str]:
        """
        Returns a dictionary containing all data that can be used to render a template.

        It will contain:
        - "state_id": The ID of the current state of the state machine
        - "state_name": The name of the current state of the state machine
        - "dialogue" The string output of the current dialogue
        - all keys and values of the machine's current model
        """
        render_data = self.model.model_dump()
        render_data.update(
            {
                "state_id": self.current_state.id,
                "state_name": self.current_state.name,
                "chat_history": str(self.model.format_dialogue(DialogueFormat.CHAT)),
            }
        )
        return render_data

    def get_state_template(self, target: State) -> CompositeTemplateType:
        try:
            return getattr(self, self.templates_property_name).get(target.id)
        except KeyError:
            logging.error(f"Failed to find template for state {target.id}")
            raise

    def render_template(self, template: CompositeTemplateType) -> CompositeContentType:
        if isinstance(template, str):
            return template
        if isinstance(template, Template):
            return template.render(self.render_data)
        if isinstance(template, list):
            return [self.render_template(t) for t in template]
        if isinstance(template, dict):
            return {k: self.render_template(t) for k, t in template.items()}
        if isinstance(template, Task):
            return template(self.render_data)

    def get_target_rendering(self, target: State) -> str:
        """
        Render the structure of rendered prompts that are recorded for the target state.
        If the target state has a template, return the rendered template using the
        `self.render_data` property.
        If the target state as a template that is as string, that string is returned.
        If the target state has a template of any other value, return the string representation
        of that value.

        If the target state has no template, just return the name of the target state.
        """
        template = self.get_state_template(target)
        if isinstance(template, Template):
            return template.render(self.render_data)
        if isinstance(template, str):
            return template

        logger.warning(f"Trying to render a template of type {type(template)}")
        return str(template)

    # EVENT HANDLERS
    def before_transition(self, event_data: EventData):
        """
        Set the current actors input and the current rendering for the target state.
        It is assumed that the event data that is provided to the event
        that started this transition is the actor input.

        Triggered when an event is received, right before the current state is exited.

        This method takes the events first argument and places that in `self.actor_input`. This
        makes it available for further processing.

        It will also take the rendering of the target template and stores that into
        `self.current_rendering` for further processing.

        If the event data does not contain the actor input, the actor is reset to an empty
        string.

        :param event_data: the event data that was provided to start this transition
        """
        try:
            self.model.actor_input = event_data.args[0]
            logger.debug("Setting the actor input to %s", self.model.actor_input)
        except (TypeError, IndexError) as e:
            logger.debug("Starting a transition without an actor input")
            self.model.actor_input = ""

        self.current_template = self.get_state_template(event_data.target)

    def on_user_input(self, event_data: EventData):
        """
        This method gets triggered when a "user_input" event is received.
        We are setting the model's current actor to the User actor name.

        This method then creates the Celery task that needs to be ran, according to the
        template of the target state. It also determines what event needs to be sent
        when that task has finished.

        Finally, the Celery task is enqueued, the corresponding task id recorded on the model
        and returned.
        """
        logger.debug(f"User input event received")
        self.model.actor = self._user_actor_name

        return self.run_task(event_data)

    def on_ai_extraction(self, target: State):
        """
        This event is received when an `ai_extraction` event is received.
        We are setting the model's current actor to the AI actor and rendering the
        template of the target event. Any extraction from the results of the AI call
        need to be done before; typically in a `on_exit_<state>` method.
        """
        logger.debug(f"AI extraction event received")
        self.model.actor = self._ai_actor_name
        self.model.actor_input = self.render_template(self.current_template)

        return None

    def on_advance(self, event_data: EventData):
        """
        This hook is called when an 'advance' event is received. These mean that output was shown
        to the user (for instance, an intermediate result) and that the client wants the
        state machine to move on without actual user input.
        We are setting the model's current actor to the AI actor name.
        """
        logger.debug(f"Advance event received")
        self.model.actor = self._ai_actor_name

        return self.run_task(event_data)

    def after_transition(self, state: State, **kwargs):
        logger.info(f"== concluding transition into state {state.name} ({state.id})")

        if self.model.actor is not None:
            logger.debug("Adding a dialogue element to the dialogue")
            self.model.dialogue.append(
                DialogueElement(
                    actor=self.model.actor,
                    actor_text=self.model.actor_input,
                )
            )
            self.model.actor = None
            self.model.actor_input = None

    def _compile_task(self, template: CompositeTemplateType) -> Signature:
        """
        Compiles a Celery task that follows the structure of the composite template.
        """
        if isinstance(template, str):
            return call_llm_api.s(template)
        if isinstance(template, Template):
            prompt = self.render_template(template)
            return call_llm_api.s(prompt)

        if isinstance(template, Task):
            return template.s(self.render_data)

        if isinstance(template, list):
            return chain(*[self._compile_task(t) for t in template])
        if isinstance(template, dict):
            dict_keys = template.keys()  # make sure to go through keys in fixed order
            return chain(
                group(*[self._compile_task(template[k]) for k in dict_keys]),
                combine_group_to_dict.s(dict_keys)
            )
        raise ValueError(f"trying to compile a task for a render of type '{type(template)}'")

    def create_ai_task(self, template: CompositeTemplateType, event_to_send_after: str):
        fqn = get_fully_qualified_name_from_class(self.model)
        return chain(
            self._compile_task(template),
            trigger_ai_event.s(fqn, self.model.session_id, event_to_send_after),
        )

    def run_task(self, event_data: EventData) -> str:
        # TODO what if there are more than one event leading out the the future state
        event_to_send_after = event_data.target.transitions.unique_events[0]
        task = self.create_ai_task(self.current_template, event_to_send_after)
        self.model.running_task_id = task.apply_async().id
        return self.model.running_task_id

    # VALIDATIONS AND CONDITIONS
    def is_valid_response(self, event_data: EventData):
        logger.debug(f"is valid response {event_data.args}")
        return all(
            [
                event_data.args is not None,
                len(event_data.args) > 0,
                event_data.args[0] is not None,
                event_data.args[0] != "",
            ]
        )

