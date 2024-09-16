from typing import Optional

from fastapi import HTTPException, APIRouter, FastAPI
from fastapi import status
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from ai_state_machine.model.api import AIStatusResponse, AIResponse, EventInput
from ai_state_machine.session import SessionManager


def _unknown_state_machine_exception(state_machine_key: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"State machine {state_machine_key} is unknown",
    )


class GenieFlowRouterBuilder:

    def __init__(self, session_manager: SessionManager, debug: bool):
        self.session_manager = session_manager
        self.debug = debug

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
            result = self.session_manager.process_event(state_machine_key, event)
            if result.error is not None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=result.error if self.debug else "Genie Flow Internal Error"
                )
            return result
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

    def get_task_state(
        self, state_machine_key: str, session_id: str
    ) -> AIStatusResponse:
        try:
            return self.session_manager.get_task_state(state_machine_key, session_id)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

    def get_model(self, state_machine_key: str, session_id: str) -> BaseModel:
        try:
            return self.session_manager.get_model(state_machine_key, session_id)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)


def create_fastapi_app(
        session_manager: SessionManager,
        config: dict,
        cors_settings: dict,
) -> FastAPI:
    fastapi_app = FastAPI(
        title="GenieFlow",
        summary="Genie Flow API",
        description=__doc__,
        version="0.1.0",
        **config
    )

    debug = config.get("debug", False)
    fastapi_app.include_router(
        GenieFlowRouterBuilder(session_manager, debug).router,
        prefix=getattr(config, "prefix", "/v1/ai"),
    )

    fastapi_app.add_middleware(
        CORSMiddleware,
        **cors_settings
    )

    return fastapi_app
