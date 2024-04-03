from typing import Optional

from jinja2 import Template
from loguru import logger
from statemachine import StateMachine, State
from statemachine.event_data import EventData

from ai_state_machine.model import GenieModel, DialogueElement


class GenieStateMachine(StateMachine):

    def __init__(
            self,
            model: GenieModel,
            user_actor_name: str = "HUMAN",
            ai_actor_name: str = "AI",
    ):
        super(GenieStateMachine, self).__init__(model=model, state_field="_state")
        self._user_actor_name = user_actor_name
        self._ai_actor_name = ai_actor_name

        initial_prompt = self.get_target_prompt(self.current_state)
        self.dialogue: list[DialogueElement] = [
            DialogueElement(
                actor=self._ai_actor_name,
                internal_repr=initial_prompt,
                external_repr=initial_prompt,
            )
        ]
        self.actor_input: str = ""

    @property
    def current_response(self) -> Optional[DialogueElement]:
        return self.dialogue[-1] if len(self.dialogue) > 0 else None

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
                "dialogue": str(self.dialogue),
                "actor_input": self.actor_input,
            }
        )
        return render_data

    def get_target_prompt(self, target: State) -> str:
        """
        If the target state value is a template, return the rendered template using the
        `self.render_data` property. If the target state value is not a template, just
        return the value from the target state.
        """
        prompt = target.value
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
            self.actor_input = event_data.args[0]
            logger.debug("Setting the actor input to %s", self.actor_input)
        except (TypeError, IndexError) as e:
            logger.debug("Starting a transition without an actor input: %s", e)
            self.actor_input = ""

        return self.actor_input

    def on_user_input(self, event_data: EventData):
        """
        This method gets triggered when a "user_input" event is received. We should now be
        transitioning into an AI state. During this transition, we will trigger the AI
        invocation. That means: render the template of the state that we are transitioning
        into and send that off to the generative AI solution.

        If the `value` of the target state is a Jinja2 template, we will render that template
        using the data provided by `self.render_data`. If not, then the prompt will be the
        literal value of the target state.

        """
        logger.debug(f"User input event received")
        self.dialogue.append(
            DialogueElement(
                actor=self._user_actor_name,
                internal_repr=self.actor_input,
                external_repr=self.actor_input,
            )
        )
        prompt = self.get_target_prompt(event_data.target)
        # TODO call the LLM to interpret the prompt

    def on_ai_extraction(self, target: State):
        """
        This hook get triggered when an "ai_extraction" event is received. It adds the AI response
        to the dialogue list as the tuple ("ai-response", ai_response).

        This hook then looks at the 'value' of the target state - which is assumed to be a Jinja template - and renders
        that template using the values of `self.model` and the template variable `ai_response` with the raw
        response that is received from the AI. The rendering of that template is then added to the dialogue
        list as the tuple ("ai", ai_chat_response).

        The state machine will then transfer into the next state which will be a "waiting for user input" state.

        :param target: the `State` that the state machine will move into after this event.
        :return:
        """
        logger.debug(f"AI extraction event received")
        self.dialogue.append(
            DialogueElement(
                actor=self._ai_actor_name,
                internal_repr=self.actor_input,
                external_repr=self.get_target_prompt(target),
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
