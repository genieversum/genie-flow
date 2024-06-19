from statemachine import State

from ai_state_machine.genie import GenieModel, GenieStateMachine


class QandATransModel(GenieModel):

    @classmethod
    def get_state_machine_class(cls) -> type[GenieStateMachine]:
        return QandATransMachine


class QandATransMachine(GenieStateMachine):

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
        ai_creates_response=[
            "q_and_a/ai_response.jinja2",
            "q_and_a/ai_response_summary.jinja2",
        ],
        # ai_creates_response="q_and_a/ai_response.jinja2",
    )
