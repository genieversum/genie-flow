import pydantic_redis
from dependency_injector import containers, providers
from redis import Redis

from genie_flow.session_lock import SessionLockManager
from genie_flow.store import StoreManager


class PydanticRedisStoreWrapper(pydantic_redis.Store):

    def __init__(
        self, host: str, port: int, db: int, life_span_in_seconds: int = 86400
    ):
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


class GenieFlowPersistenceContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    pydantic_redis_store = providers.Singleton(
        PydanticRedisStoreWrapper,
        host=config.model_store.host,
        port=config.model_store.port,
        db=config.model_store.db,
        life_span_in_seconds=config.model_store.life_span_in_seconds,
    )

    redis_lock_store = providers.Singleton(
        Redis,
        host=config.lock_store.host,
        port=config.lock_store.port,
        db=config.lock_store.db,
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
