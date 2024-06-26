from typing import Optional

from pydantic import Field
from statemachine import State
from statemachine.event_data import EventData

from ai_state_machine.genie import GenieModel, GenieStateMachine


class QandACaptureModel(GenieModel):
    user_name: Optional[str] = Field(None, description="The name of the user")

    @classmethod
    def get_state_machine_class(cls) -> type[GenieStateMachine]:
        return QandACaptureMachine


class QandACaptureMachine(GenieStateMachine):

    # STATES
    intro = State(initial=True, value=000)
    ai_extracts_name = State(value=30)
    need_to_retry = State(value=40)
    welcome_message = State(value=50)
    user_enters_query = State(value=100)
    ai_creates_response = State(value=200)
    outro = State(final=True, value=300)

    # EVENTS AND TRANSITIONS
    user_input = (
        intro.to(ai_extracts_name)
        | need_to_retry.to(ai_extracts_name)
        | welcome_message.to(ai_creates_response)
        | user_enters_query.to(ai_creates_response, unless="user_says_stop")
        | user_enters_query.to(outro, cond="user_says_stop")
    )
    ai_extraction = (
        ai_extracts_name.to(welcome_message, cond="name_is_defined")
        | ai_extracts_name.to(need_to_retry, unless="name_is_defined")
        | ai_creates_response.to(user_enters_query, unless="user_wants_to_quit")
        | ai_creates_response.to(outro, cond="user_wants_to_quit")
    )

    # TEMPLATES
    templates = dict(
        intro="q_and_a/intro_ask_name.jinja2",
        ai_extracts_name="q_and_a/ai_name_extraction.jinja2",
        need_to_retry="q_and_a/request_for_name_retry.jinja2",
        welcome_message="q_and_a/welcome.jinja2",
        user_enters_query="q_and_a/user_input.jinja2",
        ai_creates_response="q_and_a/ai_response.jinja2",
        outro="q_and_a/outro.jinja2",
    )

    # CONDITIONS
    def name_is_defined(self, event_data: EventData) -> bool:
        return (
            event_data.args is not None
            and len(event_data.args) != 0
            and event_data.args[0] != "UNDEFINED"
        )

    def user_says_stop(self, event_data: EventData):
        return (
            event_data.args is not None
            and len(event_data.args) != 0
            and event_data.args[0] == "STOP"
        )

    def user_wants_to_quit(self, event_data: EventData):
        return (
            event_data.args is not None
            and len(event_data.args) != 0
            and "STOP" in event_data.args[0]
        )

    # ACTIONS
    def on_exit_ai_extracts_name(self):
        self.model.user_name = self.model.actor_input
