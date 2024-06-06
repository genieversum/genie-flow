from typing import Optional

from celery import group, Task, Celery
from celery.canvas import Signature, chord
from dependency_injector.wiring import Provide, inject
from jinja2 import TemplateNotFound
from loguru import logger
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from ai_state_machine.containers import GenieFlowContainer
from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model import DialogueElement, DialogueFormat, CompositeTemplateType, \
    CompositeContentType
from ai_state_machine.store import get_fully_qualified_name_from_class


class GenieStateMachine(StateMachine):
    """
    A State Machine class that is able to manage an AI driven dialogue and extract information
    from it. The extracted information is stored in an accompanying data model (based on the
    `GenieModel` class.
    """

    @inject
    def __init__(
            self,
            model: GenieModel,
            new_session: bool = False,
            templates_property_name: str = "templates",
            celery_app: Celery = Provide[GenieFlowContainer.celery_app]
    ):
        self.templates_property_name = templates_property_name
        self.celery_app = celery_app

        self.current_template: Optional[CompositeTemplateType] = None
        super(GenieStateMachine, self).__init__(model=model)

        if new_session:
            self._validate_state_templates()

            initial_prompt = self.render_template(self.get_template_for_state(self.initial_state))
            self.model.dialogue.append(
                DialogueElement(
                    actor="assistant",
                    actor_text=initial_prompt,
                )
            )

    @inject
    def _non_existing_templates(
            self,
            template: CompositeTemplateType,
            genie_environment: GenieEnvironment = Provide[GenieFlowContainer.genie_environment],
    ) -> list:
        if isinstance(template, str):
            try:
                print(type(genie_environment))
                _ = genie_environment.get_template(template)
                return []
            except TemplateNotFound:
                return [template]

        if isinstance(template, Task):
            # TODO might want to check if the task exists
            return []

        if isinstance(template, list):
            result = []
            for t in template:
                result.extend(self._non_existing_templates(t))
            return result

        if isinstance(template, dict):
            result = []
            for key in template.keys():
                result.extend([f"{key}/{t}" for t in self._non_existing_templates(template[key])])
            return result

    def _validate_state_templates(self):
        templates = getattr(self, self.templates_property_name)
        states_without_template = {
            state.id
            for state in self.states
            if state.id not in templates
        }

        unknown_template_names = self._non_existing_templates(
            [
                templates[t]
                for t in set(state.id for state in self.states) - states_without_template
            ]
        )

        if states_without_template or unknown_template_names:
            raise ValueError(
                f"Missing templates for states: [{', '.join(states_without_template)}] and "
                f"cannot find templates with names: [{', '.join(unknown_template_names)}]"
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

    @inject
    def render_template(
            self,
            template: CompositeTemplateType,
            genie_environment: GenieEnvironment = Provide[GenieFlowContainer.genie_environment],
    ) -> CompositeContentType:
        """
        Render a given template with the `render_data`. This rendering is done synchronously.
        If the template is a string, it is assumed to be the name of the template that needs
        to be retrieved from the template environment. If the template is a list, the templates
        within that list are rendered. If the template is a dictionary, the result is a dictionary
        with each of the renderings per key of that dictionary. Finally, if the template is a Task,
        that task is called with the current render data.

        :param template: The template to render
        :param genie_environment: The GenieEnvironment to use
        :return: The rendered template
        :raises TypeError: If the template is of a type that we cannot render
        """
        if isinstance(template, str):
            return genie_environment.render_template(template, self.render_data)
        if isinstance(template, list):
            return [self.render_template(t) for t in template]
        if isinstance(template, dict):
            return {k: self.render_template(t) for k, t in template.items()}
        if isinstance(template, Task):
            return template(self.render_data)
        raise TypeError(f"Unsupported type of template {type(template)}")

    def get_template_for_state(self, state: State) -> CompositeTemplateType:
        """
        Retrieve the template for a given state. Raises an exception if the given
        state does not have a template defined.

        :param state: The state for which to retrieve the template for
        :return: The template for the given state
        :raises AttributeError: If this object does not have an attribute that carries the templates
        :raises KeyError: If there is no template defined for the given state
        """
        try:
            return getattr(self, self.templates_property_name).get(state.id)
        except AttributeError:
            logger.error(f"No attribute named '{self.templates_property_name}' with the templates")
            raise
        except KeyError:
            logger.error(f"No template for state {state.id}")
            raise

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

        self.current_template = self.get_template_for_state(event_data.target)

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
        self.model.actor = "user"

        return self.enqueue_task(event_data)

    def on_ai_extraction(self, target: State):
        """
        This event is received when an `ai_extraction` event is received.
        We are setting the model's current actor to the AI actor and rendering the
        template of the target event. Any extraction from the results of the AI call
        need to be done before; typically in a `on_exit_<state>` method.
        """
        logger.debug(f"AI extraction event received")
        self.model.actor = "assistant"
        self.model.actor_input = self.render_template(self.current_template)
        logger.debug(f"AI output rendered into: \n{self.model.actor_input}")

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

        return self.enqueue_task(event_data)

    def after_transition(self, state: State, **kwargs):
        """
        A generic hook that gets called after a transition has been completed. This is used
        to add to the dialogue a new `DialogueElement` with the current actor and actor input.
        """
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
            invoke_task = self.celery_app.tasks["genie_flow.invoke_task"]
            return invoke_task.s(template, self.render_data)

        if isinstance(template, Task):
            return template.s(self.render_data)

        if isinstance(template, list):
            chained_template_task = self.celery_app.tasks["genie_flow.chained_task"]

            chained = None
            for t in template:
                if chained is None:
                    chained = self._compile_task(t)
                else:
                    chained |= chained_template_task.s(t, self.render_data)
                    chained |= self._compile_task(t)
            return chained

        if isinstance(template, dict):
            combine_group_to_dict_task = self.celery_app.tasks["genie_flow.combine_group_to_dict"]

            dict_keys = list(template.keys())  # make sure to go through keys in fixed order
            return chord(
                group(*[self._compile_task(template[k]) for k in dict_keys]),
                combine_group_to_dict_task.s(dict_keys)
            )
        raise ValueError(f"cannot compile a task for a render of type '{type(template)}'")

    def create_ai_task(self, template: CompositeTemplateType, event_to_send_after: str):
        trigger_ai_event_task = self.celery_app.tasks["genie_flow.trigger_ai_event"]

        return (
            self._compile_task(template) |
            trigger_ai_event_task.s(
                get_fully_qualified_name_from_class(self.model),
                self.model.session_id,
                event_to_send_after,
            )
        )

    def enqueue_task(self, event_data: EventData) -> str:
        trigger_ai_event_task = self.celery_app.tasks["genie_flow.trigger_ai_event"]

        # TODO what if there are more than one event leading out the the future state
        event_to_send_after = event_data.target.transitions.unique_events[0]

        task = (
                self._compile_task(self.current_template) |
                trigger_ai_event_task.s(
                    get_fully_qualified_name_from_class(self.model),
                    self.model.session_id,
                    event_to_send_after
                )
        )
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
