import uuid

from fastapi import FastAPI

from ai_state_machine.store import retrieve_state_machine, store_state_machine
from example_claims.claims import ClaimsModel, ClaimsMachine
from example_claims.model import AIResponse, EventInput, AIStatusResponse

app = FastAPI()


@app.get("/")
def get_root():
    return "Hello World!"


@app.get("/v1/start_session/")
def start_session():
    session_id = str(uuid.uuid4().hex)
    state_machine = ClaimsMachine(session_id=session_id)
    store_state_machine(state_machine)

    response = state_machine.current_response.external_repr
    return AIResponse(
        session_id=session_id,
        response=response,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


@app.post("/v1/event/")
def start_event(event: EventInput):
    state_machine = retrieve_state_machine(event.session_id)
    state_machine.send(event.event, event.event_input)
    store_state_machine(state_machine)

    response = state_machine.current_response.external_repr
    return AIResponse(
        session_id=event.session_id,
        response=response,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


@app.get("/v1/state/{session_id}")
def get_state(session_id: str):
    state_machine = retrieve_state_machine(session_id)
    return AIStatusResponse(
        session_id=session_id,
        ready=state_machine.running_task_id is None
    )
