import json
from typing import Optional

import jmespath
from fastapi import HTTPException, APIRouter, FastAPI, Body
from fastapi import status
from fastapi.middleware.cors import CORSMiddleware

from genie_flow.model.api import AIStatusResponse, AIResponse, EventInput, SessionStartRequest
from genie_flow.session import SessionManager
from genie_flow.model.user import User


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
            "/{state_machine_key}/start_session",
            self.start_session,
            methods=["POST"],
        )
        router.add_api_route(
            "/{state_machine_key}/start_ephemeral_session",
            self.start_ephemeral_session,
            methods=["POST"],
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
            description=
            "Retrieve data from the model of a session. "
            "Using the query parameter 'path' and specifying a JMSEpath, "
            "this endpoint will only return the specified data.",
        )
        router.add_api_route(
            "/{state_machine_key}/user_sessions",
            self.get_user_sessions,
            methods=["POST"],
        )
        return router

    def get_user_sessions(self, state_machine_key: str, user_info: User):
        try:
            return self.session_manager.get_user_sessions(user_info)
        except Exception as e:
            raise _unknown_state_machine_exception(state_machine_key)

    def start_session(
            self,
            state_machine_key: str,
            user_info: Optional[User] = Body(None),
            seed_data: Optional[str] = Body(None),
    ) -> AIResponse:
        """
        Create a new session for the given model key. If the user info is provided,
        that user info will be associated with the session. If seeding_data is provided,
        that string will be passed into the seed method of the newly created session object.

        :param state_machine_key: the model key of the state machine to start a session for
        :param user_info: optional user info to associate with the session
        :param seed_data: optional string to seed the newly created session object
        :return: a AIResponse object for the new session
        """
        try:
            return self.session_manager.create_new_session(
                state_machine_key,
                user_info,
                seed_data,
            )
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

    def start_ephemeral_session(
            self,
            state_machine_key: str,
            session_start_request: SessionStartRequest
    ):
        try:
            return self.session_manager.start_ephemeral_session(
                state_machine_key,
                session_start_request.event,
                session_start_request.event_input,
                session_start_request.user_info,
            )
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

    def get_model(
            self,
            state_machine_key: str,
            session_id: str,
            path: Optional[str] = None
    ) -> AIResponse:
        try:
            model = self.session_manager.get_model(state_machine_key, session_id)
        except KeyError:
            raise _unknown_state_machine_exception(state_machine_key)

        model_data = model.model_dump(mode="json")
        if path is not None:
            model_data = jmespath.search(path, model_data)

        task_state = self.session_manager.get_task_state(state_machine_key, session_id)
        return AIResponse(
            session_id=session_id,
            response=json.dumps(model_data),
            next_actions=task_state.next_actions if task_state.ready else ["poll"],
        )


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
