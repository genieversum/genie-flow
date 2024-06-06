from fastapi import HTTPException, APIRouter

from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model.api import AIStatusResponse, AIResponse, EventInput
from ai_state_machine.session import SessionManager


def _unknown_state_machine_exception(state_machine_key: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"State machine {state_machine_key} is unknown",
    )


class GenieFlowRouterBuilder:

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    @property
    def router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route(
            "/{state_machine_key}/start_session",
            self.start_session,
            methods=["GET"],
        )
        router.add_api_route(
            "/{state_machine_key}/event",
            self.start_event,
            methods=["POST"],
        )
        router.add_api_route(
            "/{state_machine_key}/task_state/{session_id}",
            self.get_task_state,
            methods=["GET"],
        )
        router.add_api_route(
            "/{state_machine_key}/model/{session_id}",
            self.get_model,
            methods=["GET"],
        )
        return router

    def start_session(self, state_machine_key: str) -> AIResponse:
        try:
            return self.session_manager.create_new_session(state_machine_key)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

    def start_event(self, state_machine_key: str, event: EventInput) -> AIResponse:
        try:
            return self.session_manager.process_event(state_machine_key, event)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

    def get_task_state(
        self, state_machine_key: str, session_id: str
    ) -> AIStatusResponse:
        try:
            return self.session_manager.get_task_state(state_machine_key, session_id)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

    def get_model(self, state_machine_key: str, session_id: str) -> GenieModel:
        try:
            return self.session_manager.get_model(state_machine_key, session_id)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)
