from typing import Optional

from celery import Celery
from dependency_injector import containers, providers
from redis import Redis
import pydantic_redis

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.model import DialogueElement

_CONTAINER: Optional[containers.Container] = None


class CeleryApp(Celery):
    def __init__(self, broker: str, backend: str, celery_db: int):
        super().__init__(
            "genie_flow",
            broker=f"{broker}/{celery_db}",
            backend=f"{backend}/{celery_db}",
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

    celery_app = providers.Singleton(
        CeleryApp,
        broker=config.celery.broker,  # "amqp://guest:guest@localhost:5672//",
        backend=config.celery.backend,  # "redis://localhost:6379/0"
        celery_db=config.celery.db,  # 0
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

    genie_environment = providers.Singleton(
        GenieEnvironment,
        config.template_root_path,
        config.pool_size,
    )


def _create_container() -> GenieFlowContainer:
    container = GenieFlowContainer()
    container.wire(modules=[
        "."
    ])
    container.init_resources()

    container.pydantic_redis_store().register_model(DialogueElement)

    return container


def get_container() -> GenieFlowContainer:
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = _create_container()
    return _CONTAINER
