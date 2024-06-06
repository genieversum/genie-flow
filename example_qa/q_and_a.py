from statemachine import State

from ai_state_machine.genie_state_machine import GenieStateMachine
from ai_state_machine.genie_model import GenieModel


class QandAModel(GenieModel):

    @property
    def state_machine_class(self) -> type[GenieStateMachine]:
        return QandAMachine


class QandAMachine(GenieStateMachine):

    def __init__(self, model: QandAModel, new_session: bool = False):
        if not isinstance(model, QandAModel):
            raise TypeError(
                "The type of model should be QandAModel, not {}".format(type(model))
            )

        super(QandAMachine, self).__init__(model=model, new_session=new_session)

    # STATES
    intro = State(initial=True, value=000)
    user_enters_query = State(value=100)
    ai_creates_response = State(value=200)

    # EVENTS AND TRANSITIONS
    user_input = intro.to(ai_creates_response) | user_enters_query.to(
        ai_creates_response
    )
    ai_extraction = ai_creates_response.to(user_enters_query)

    # TEMPLATES
    templates = dict(
        intro="q_and_a/intro.jinja2",
        user_enters_query="q_and_a/user_input.jinja2",
        ai_creates_response="q_and_a/ai_response.jinja2",
    )
