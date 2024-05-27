from fastapi import FastAPI, HTTPException

from ai_state_machine import core
from ai_state_machine import registry
from ai_state_machine.templates.jinja import register_template_directory
from example_claims.claims import ClaimsModel
from ai_state_machine.model import EventInput

app = FastAPI()

registry.register("claims_genie", ClaimsModel)
register_template_directory("claims", "example_claims/templates")


def _unknown_state_machine_exception(state_machine_key: str) -> HTTPException:
    return HTTPException(
            status_code=404,
            detail=f"State machine {state_machine_key} is unknown",
        )


@app.get("/")
def get_root():
    return "Hello World!"


@app.get("/v1/ai/{state_machine_key}/start_session/")
def start_session(state_machine_key: str):
    try:
        return core.create_new_session(registry.retrieve(state_machine_key))
    except KeyError:
        return _unknown_state_machine_exception(state_machine_key)


@app.post("/v1/ai/{state_machine_key}/event/")
def start_event(state_machine_key: str, event: EventInput):
    try:
        return core.process_event(event, registry.retrieve(state_machine_key))
    except KeyError:
        return _unknown_state_machine_exception(state_machine_key)


@app.get("/v1/ai/{state_machine_key}/task_state/{session_id}")
def get_task_state(state_machine_key: str, session_id: str):
    try:
        return core.get_task_state(session_id, registry.retrieve(state_machine_key))
    except KeyError:
        return _unknown_state_machine_exception(state_machine_key)


@app.get("/v1/ai/{state_machine_key}/model/{session_id}")
def get_model(state_machine_key: str, session_id: str):
    try:
        return core.get_model(session_id, registry.retrieve(state_machine_key))
    except KeyError:
        return _unknown_state_machine_exception(state_machine_key)
