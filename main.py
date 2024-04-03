import uuid

from fastapi import FastAPI

from example_claims.claims import ClaimsModel, ClaimsMachine
from fake_database import DB
from example_claims.model import AIResponse, EventInput

app = FastAPI()


@app.get("/")
def get_root():
    return "Hello World!"


@app.get("/v1/start_session/")
def start_session():
    session_id = str(uuid.uuid4().hex)
    claims_model = ClaimsModel(session_id=session_id)
    state_machine = ClaimsMachine(claims_model)
    DB[session_id] = state_machine

    response = state_machine.current_response.external_repr
    return AIResponse(
        session_id=session_id,
        response=response,
        next_actions=state_machine.allowed_events,
    )


@app.post("/v1/event/")
def start_event(event: EventInput):
    state_machine = DB[event.session_id]
    state_machine.send(event.event, event.event_input)
    DB[event.session_id] = state_machine

    response = state_machine.current_response.external_repr
    return AIResponse(
        session_id=event.session_id,
        response=response,
        next_actions=state_machine.allowed_events,
    )
