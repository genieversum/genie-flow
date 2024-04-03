from typing import Optional

from loguru import logger
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from ai_state_machine.model import GenieModel, DialogueElement


class GenieStateMachine(StateMachine):

    def __init__(self, model: GenieModel):
        super(GenieStateMachine, self).__init__(model=model, state_field="_state")
        self.dialogue: list[DialogueElement] = [
            DialogueElement.from_state(
                "ai",
                "",
                self.current_state,
                self.model,
            )
        ]
        self.actor_input: Optional[str] = None

    @property
    def current_response(self) -> Optional[DialogueElement]:
        return self.dialogue[-1] if len(self.dialogue) > 0 else None

    # EVENT HANDLERS
    def before_transition(self, *args, **kwargs) -> str:
        """
        Set the actors input.

        Triggered when an event is received, right but before the current state is exited.

        This method takes the events first argument and places that in `self.actor_input`. This
        makes it available for further processing.

        :param args: the list of arguments passed to this event
        :return: the first argument that was passed to this event
        """
        self.actor_input = args[0]
        return self.actor_input

    def on_user_input(self):
        """
        :param args:
        :param kwargs:
        :return:
        """
        logger.debug(f"User input event received")
        self.dialogue.append(
            DialogueElement(
                actor="user",
                internal_repr=self.actor_input,
                external_repr=self.actor_input,
            )
        )
        # self.prompt = kwargs["target"].value.render(self.model.dict())
        # call the LLM to interpret the prompt

    def on_ai_extraction(self, *args, target: State):
        """
        This hook get triggered when an "ai_extraction" event is received. It adds the AI response to the dialogue
        list as the tuple ("ai-response", ai_response).

        This hook then looks at the 'value' of the target state - which is assumed to be a Jinja template - and renders
        that template using the values of `self.model` and the template variable `ai_response` with the raw
        response that is received from the AI. The rendering of that template is then added to the dialogue
        list as the tuple ("ai", ai_chat_response).

        The state machine will then transfer into the next state which will be a "waiting for user input" state.

        :param args:
        :param target: the `State` that the state machine will move into after this event.
        :return:
        """
        logger.debug(f"AI extraction event received")
        self.dialogue.append(
            DialogueElement.from_state(
                "ai",
                internal_repr=self.actor_input,
                state=target,
                data=self.model,
            )
        )

    def on_enter_state(self, state: State, **kwargs):
        logger.info(f"== entering state {self.current_state.name} ({self.current_state.id})")

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
