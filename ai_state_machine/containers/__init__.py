from os import PathLike
from typing import Optional

from celery import Celery
import pydantic_redis

from ai_state_machine.app import GenieFlowRouterBuilder
from ai_state_machine.celery_tasks import (
    add_trigger_ai_event_task,
    add_invoke_task,
    add_combine_group_to_dict,
    add_chained_template,
)
from ai_state_machine.containers.genieflow import GenieFlowContainer
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.model.dialogue import DialogueElement


_CONTAINER: Optional[GenieFlowContainer] = None


def init_genie_flow(config_file_path: str | PathLike) -> GenieEnvironment:
    global _CONTAINER

    if _CONTAINER is not None:
        raise RuntimeError("Already initialized")

    # create and wire the container
    _CONTAINER = GenieFlowContainer()
    _CONTAINER.config.from_yaml(config_file_path, required=True)
    _CONTAINER.wire(packages=["ai_state_machine"])
    _CONTAINER.init_resources()

    # register Celery tasks
    add_trigger_ai_event_task(
        _CONTAINER.celery_app(),
        _CONTAINER.session_lock_manager(),
        _CONTAINER.store_manager(),
    )
    add_invoke_task(
        _CONTAINER.celery_app(),
        _CONTAINER.genie_environment(),
    )
    add_combine_group_to_dict(_CONTAINER.celery_app())
    add_chained_template(_CONTAINER.celery_app())

    # wire the FastAPI routes
    _CONTAINER.fastapi_app().include_router(
        GenieFlowRouterBuilder(_CONTAINER.session_manager()).router,
        prefix=_CONTAINER.config.api.prefix() or "/v1/ai",
    )

    # register base classes for storage
    _CONTAINER.pydantic_redis_store().register_model(DialogueElement)
    _CONTAINER.pydantic_redis_store().register_model(GenieModel)

    return _CONTAINER.genie_environment()


def get_environment() -> GenieEnvironment:
    global _CONTAINER

    if _CONTAINER is None:
        raise RuntimeError("Not initialized")

    return _CONTAINER.genie_environment()
