from fastapi import FastAPI

from ai_state_machine import core
from example_claims.claims import ClaimsModel
from ai_state_machine.model import EventInput

app = FastAPI()


@app.get("/")
def get_root():
    return "Hello World!"


@app.get("/v1/start_session/")
def start_session():
    return core.create_new_session(ClaimsModel)


@app.post("/v1/event/")
def start_event(event: EventInput):
    return core.process_event(event, ClaimsModel)


@app.get("/v1/task_state/{session_id}")
def get_task_state(session_id: str):
    return core.get_task_state(session_id, ClaimsModel)


@app.get("/v1/model/{session_id}")
def get_model(session_id: str):
    return core.get_model(session_id, ClaimsModel)
