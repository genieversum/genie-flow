from os import PathLike
from typing import Optional

from fastapi import FastAPI

from ai_state_machine.app import GenieFlowRouterBuilder
from ai_state_machine.containers.api import GenieFlowAPIContainer
from ai_state_machine.containers.core import GenieFlowCoreContainer
from ai_state_machine.containers.genieflow import GenieFlowContainer
from ai_state_machine.containers.persistence import GenieFlowPersistenceContainer
from ai_state_machine.environment import GenieEnvironment


_CONTAINER_APP: Optional[GenieFlowContainer] = None
_CONTAINER_API: Optional[GenieFlowAPIContainer] = None


def init_genie_flow_app(config_file_path: str | PathLike) -> GenieEnvironment:
    global _CONTAINER_APP

    if _CONTAINER_APP is not None:
        raise RuntimeError("Already initialized")

    # create and wire the container
    _CONTAINER_APP = GenieFlowContainer()
    _CONTAINER_APP.config.from_yaml(config_file_path, required=True)
    _CONTAINER_APP.wire(packages=["ai_state_machine"])
    _CONTAINER_APP.init_resources()

    return _CONTAINER_APP.genie_environment()


def init_genie_flow_api(config_file_path: str | PathLike) -> FastAPI:
    global _CONTAINER_API

    if _CONTAINER_API is not None:
        raise RuntimeError("Already initialized")

    if _CONTAINER_APP is None:
        init_genie_flow_app(config_file_path)

    _CONTAINER_API = GenieFlowAPIContainer(
        config=_CONTAINER_APP.config.api,
        genie_environment=_CONTAINER_APP.genie_environment(),
    )
    _CONTAINER_API.fastapi_app().include_router(
        GenieFlowRouterBuilder(_CONTAINER_APP.session_manager()).router,
        prefix=_CONTAINER_APP.config.api.prefix() or "/v1/ai",
    )

    return _CONTAINER_API.fastapi_app


def get_environment() -> GenieEnvironment:
    global _CONTAINER_APP

    if _CONTAINER_APP is None:
        raise RuntimeError("Not initialized")

    return _CONTAINER_APP.genie_environment()
