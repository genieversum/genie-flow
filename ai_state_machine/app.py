from fastapi import HTTPException, APIRouter

from ai_state_machine import core
from ai_state_machine import registry
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model import EventInput, AIResponse, AIStatusResponse

router = APIRouter()


def _unknown_state_machine_exception(state_machine_key: str) -> HTTPException:
    return HTTPException(
            status_code=404,
            detail=f"State machine {state_machine_key} is unknown",
        )


@router.get("/v1/ai/{state_machine_key}/start_session/")
def start_session(state_machine_key: str) -> AIResponse:
    try:
        return core.create_new_session(registry.retrieve(state_machine_key))
    except KeyError:
        raise _unknown_state_machine_exception(state_machine_key)


@router.post("/v1/ai/{state_machine_key}/event/")
def start_event(state_machine_key: str, event: EventInput) -> AIResponse:
    try:
        return core.process_event(event, registry.retrieve(state_machine_key))
    except KeyError:
        raise _unknown_state_machine_exception(state_machine_key)


@router.get("/v1/ai/{state_machine_key}/task_state/{session_id}")
def get_task_state(state_machine_key: str, session_id: str) -> AIStatusResponse:
    try:
        return core.get_task_state(session_id, registry.retrieve(state_machine_key))
    except KeyError:
        raise _unknown_state_machine_exception(state_machine_key)


@router.get("/v1/ai/{state_machine_key}/model/{session_id}")
def get_model(state_machine_key: str, session_id: str) -> GenieModel:
    try:
        return core.get_model(session_id, registry.retrieve(state_machine_key))
    except KeyError:
        raise _unknown_state_machine_exception(state_machine_key)
