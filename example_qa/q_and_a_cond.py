from statemachine import State
from statemachine.event_data import EventData

from ai_state_machine.genie_state_machine import GenieStateMachine
from ai_state_machine.genie_model import GenieModel


class QandACondModel(GenieModel):

    @property
    def get_state_machine_class(self) -> type[GenieStateMachine]:
        return QandACondMachine


class QandACondMachine(GenieStateMachine):

    def __init__(self, model: QandACondModel, new_session: bool = False):
        if not isinstance(model, QandACondModel):
            raise TypeError(
                "The type of model should be QandACondAModel, not {}".format(
                    type(model)
                )
            )

        super(QandACondMachine, self).__init__(model=model, new_session=new_session)

    # STATES
    intro = State(initial=True, value=000)
    user_enters_query = State(value=100)
    ai_creates_response = State(value=200)
    outro = State(final=True, value=300)

    # EVENTS AND TRANSITIONS
    user_input = (
        intro.to(ai_creates_response)
        | user_enters_query.to(ai_creates_response, unless="user_says_stop")
        | user_enters_query.to(outro, cond="user_says_stop")
    )
    ai_extraction = ai_creates_response.to(
        user_enters_query, unless="user_wants_to_quit"
    ) | ai_creates_response.to(outro, cond="user_wants_to_quit")

    # TEMPLATES
    templates = dict(
        intro="q_and_a/intro.jinja2",
        user_enters_query="q_and_a/user_input.jinja2",
        ai_creates_response="q_and_a/ai_response.jinja2",
    )

    # CONDITIONS
    def user_says_stop(self, event: EventData):
        return (
            event.args is not None
            and len(event.args) != 0
            and event.args[0] == "*STOP*"
        )

    def user_wants_to_quit(self, event: EventData):
        return (
            event.args is not None
            and len(event.args) != 0
            and "*STOP*" in event.args[0]
        )
