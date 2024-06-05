from os import PathLike
from typing import Optional

from celery import Celery
from dependency_injector import containers, providers
from fastapi import FastAPI
from redis import Redis
import pydantic_redis

from ai_state_machine import __version__
from ai_state_machine.app import GenieFlowRouterBuilder
from ai_state_machine.celery_tasks import (
    add_trigger_ai_event_task,
    add_invoke_task,
    add_combine_group_to_dict,
    add_chained_template,
)
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.session import SessionManager, SessionLockManager
from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.model import DialogueElement
from ai_state_machine.registry import ModelKeyRegistryType
from ai_state_machine.store import StoreManager


class CeleryApp(Celery):
    def __init__(self, broker: str, backend: str):
        super().__init__(
            "genie_flow",
            broker=f"{broker}",
            backend=f"{backend}",
            redis_socket_timeout=4.0,
            redis_socket_connect_timeout=4.0,
        )


class PydanticRedisStoreWrapper(pydantic_redis.Store):

    def __init__(self, host: str, port: int, db: int, life_span_in_seconds: int = 86400):
        redis_config = pydantic_redis.RedisConfig(
            host=host,
            port=port,
            db=db,
        )
        super().__init__(
            "genie flow store",
            redis_config,
            life_span_in_seconds=life_span_in_seconds,
        )


class GenieFlowContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    fastapi_app = providers.Singleton(
        FastAPI,
        title="GenieFlow",
        summary="Genie Flow API",
        description=__doc__,
        version=__version__,
        debug=config.fastapi.debug() or False,
        openapi_url=config.fastapi.openapi_url() or None,
        docs_url=config.fastapi.docs_url() or None,
        redoc_url=config.fastapi.redoc_url() or None,
        terms_of_service=config.fastapi.terms_of_service() or None,
        contact=config.fastapi.contact() or None,
        license_info=config.fastapi.license() or None,
        root_path=config.fastapi.root_path() or "/api/v1",
    )

    model_key_registry = providers.Singleton(ModelKeyRegistryType)

    celery_app = providers.Singleton(
        CeleryApp,
        broker=config.celery.broker,
        backend=config.celery.backend,
    )

    pydantic_redis_store = providers.Singleton(
        PydanticRedisStoreWrapper,
        host=config.model_store.redis_host,
        port=config.model_store.redis_port,
        db=config.model_store.redis_db,
        life_span_in_seconds=config.model_store.redis.life_span_in_seconds,
    )

    redis_lock_store = providers.Singleton(
        Redis,
        host=config.lock_store.redis_host,
        port=config.lock_store.redis_port,
        db=config.lock_store.redis_db,
    )

    store_manager = providers.Singleton(
        StoreManager,
        store=pydantic_redis_store,
    )

    session_lock_manager = providers.Singleton(
        SessionLockManager,
        redis_lock_store=redis_lock_store,
        lock_expiration_seconds=config.lock_store.lock_expiration_seconds() or 120,
    )

    session_manager = providers.Singleton(
        SessionManager,
        session_lock_manager=session_lock_manager,
        model_key_registry=model_key_registry,
    )

    genie_environment = providers.Singleton(
        GenieEnvironment,
        config.template_root_path,
        config.pool_size,
        pydantic_redis_store,
        model_key_registry,
        fastapi_app,
        celery_app,
    )


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
