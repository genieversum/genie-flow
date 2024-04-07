from abc import ABC, abstractmethod
from typing import Optional

from celery import chain
from jinja2 import Template
from loguru import logger
from pydantic import BaseModel, Field
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from ai_state_machine.model import DialogueElement, DialogueFormat
from ai_state_machine.celery_tasks import call_llm_api, trigger_ai_event


class GenieState(State):

    def __init__(self, value: str | int, template: str | Template, **kwargs):
        if not isinstance(value, str) and not isinstance(value, int):
            raise ValueError("`value` must be of type str or int and not {}".format(type(value)))

        super().__init__(value=value, **kwargs)
        self.template = template


class GenieModel(BaseModel):  # , ABC):
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
    actor_input: str = Field(
        "",
        description="the most recent received input from an actor",
    )

    @property
    def state_machine_class(self) -> type["GenieStateMachine"]:
        raise NotImplementedError()

    def create_state_machine(self) -> "GenieStateMachine":
        return self.state_machine_class(model=self)

    @property
    def current_response(self) -> Optional[DialogueElement]:
        return self.dialogue[-1] if len(self.dialogue) > 0 else None

    def format_dialogue(self, target_format: DialogueFormat) -> str:
        return DialogueFormat.format(self.dialogue, target_format)


class GenieStateMachine(StateMachine):

    def __init__(
            self,
            model: GenieModel,
            new_session: bool = False,
            user_actor_name: str = "USER",
            ai_actor_name: str = "LLM",
    ):
        self._user_actor_name = user_actor_name
        self._ai_actor_name = ai_actor_name
        self.current_dialogue_element: Optional[DialogueElement] = None
        super(GenieStateMachine, self).__init__(model=model)

        if new_session:
            initial_prompt = self.get_target_prompt(self.current_state)
            self.model.dialogue.append(
                DialogueElement(
                    actor=self._ai_actor_name,
                    internal_repr=initial_prompt,
                    external_repr=initial_prompt,
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
        - "actor_input": the most recently received input from an actor
        - all keys and values of the machine's current model
        """
        render_data = self.model.model_dump()
        render_data.update(
            {
                "state_id": self.current_state.id,
                "state_name": self.current_state.name,
                "chat_history": str(self.model.format_dialogue(DialogueFormat.CHAT)),
                "actor_input": self.model.actor_input,
            }
        )
        return render_data

    def get_target_prompt(self, target: State) -> str:
        """
        If the target state value is a template, return the rendered template using the
        `self.render_data` property. If the target state value is not a template, just
        return the value from the target state.
        """
        prompt = target.template
        if isinstance(prompt, Template):
            return prompt.render(self.render_data)
        if isinstance(prompt, str):
            return prompt
        return str(prompt)

    # EVENT HANDLERS
    def before_transition(self, event_data: EventData) -> str:
        """
        Set the actors input. It is assumed that the event data that is provided to the event
        that started this transition is the actor input.

        Triggered when an event is received, right before the current state is exited.

        This method takes the events first argument and places that in `self.actor_input`. This
        makes it available for further processing.

        If the event data does not contain the actor input, the actor is reset to an empty
        string.

        :param event_data: the event data that was provided to start this transition
        :return: the first argument that was passed to this event
        """
        try:
            self.model.actor_input = event_data.args[0]
            logger.debug("Setting the actor input to %s", self.actor_input)
        except (TypeError, IndexError) as e:
            logger.debug("Starting a transition without an actor input")
            self.model.actor_input = ""

        return self.model.actor_input

    def on_user_input(self, event_data: EventData):
        """
        This method gets triggered when a "user_input" event is received. We should now be
        transitioning into an AI state. During this transition, we will trigger the AI
        invocation. That means: render the template of the state that we are transitioning
        into and send that off to the generative AI solution.
        """
        logger.debug(f"User input event received")

        self.current_dialogue_element = DialogueElement(
            actor=self._user_actor_name,
            internal_repr=self.model.actor_input,
            external_repr=self.model.actor_input,
        )

        llm_prompt = self.get_target_prompt(event_data.target)

        # TODO what if there are more events possible from the target state
        event_to_send_when_done = event_data.target.transitions.unique_events[0]

        task = chain(
            call_llm_api.s(llm_prompt),
            trigger_ai_event.s(self.model.session_id, event_to_send_when_done)
        )
        self.model.running_task_id = task.apply_async()
        return self.model.running_task_id

    def on_ai_extraction(self, target: State):
        """
        This event is received when an `ai_extaction` event is received. This means that
        the LLM response has been received and that is the value of the actor input at this
        stage.

        We use the template of the target state to render this LLM output and create the
        dialogue element for it. It will serve as the response to the user.
        """
        logger.debug(f"AI extraction event received")
        self.model.running_task_id = None

        response_to_user = self.get_target_prompt(target)
        self.current_dialogue_element = DialogueElement(
            actor=self._ai_actor_name,
            internal_repr=self.model.actor_input,
            external_repr=response_to_user,
        )
        return response_to_user

    def on_advance(self, target: State):
        """
        This hook is called when an 'advance' event is received. These mean that output was shown
        to the user (for instance, an intermediate result) and that the client wants the
        state machine to move on without actual user input.
        """
        pass

    def on_enter_state(self, state: State, **kwargs):
        logger.info(f"== entering state {state.name} ({state.id})")

        if self.current_dialogue_element is not None:
            logger.debug("Adding a dialogue element to the dialogue")
            self.model.dialogue.append(self.model.current_dialogue_element)
            self.model.current_dialogue_element = None

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
