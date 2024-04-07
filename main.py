import uuid

from fastapi import FastAPI

from ai_state_machine.store import retrieve_state_model, store_state_model
from example_claims.claims import ClaimsModel, ClaimsMachine
from example_claims.model import AIResponse, EventInput, AIStatusResponse

app = FastAPI()


@app.get("/")
def get_root():
    return "Hello World!"


@app.get("/v1/start_session/")
def start_session():
    session_id = str(uuid.uuid4().hex)

    model = ClaimsModel(
        session_id=session_id,
        # state=ClaimsMachine.initial_state.value,
    )
    state_machine = ClaimsMachine(model=model, new_session=True)
    store_state_model(session_id, model)
    response = model.current_response.external_repr

    return AIResponse(
        session_id=session_id,
        response=response,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


@app.post("/v1/event/")
def start_event(event: EventInput):
    model = retrieve_state_model(event.session_id)
    state_machine = model.create_state_machine()
    state_machine.send(event.event, event.event_input)
    store_state_model(event.session_id, model)

    response = state_machine.current_response.external_repr
    return AIResponse(
        session_id=event.session_id,
        response=response,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


@app.get("/v1/task_state/{session_id}")
def get_tast_state(session_id: str):
    model = retrieve_state_model(session_id, ClaimsModel)
    return AIStatusResponse(
        session_id=session_id,
        ready=model.running_task_id is None
    )


@app.get("/v1/model/{session_id}")
def get_model(session_id: str):
    model = retrieve_state_model(session_id, ClaimsModel)
    return model
