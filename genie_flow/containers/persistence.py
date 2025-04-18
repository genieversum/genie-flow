from dependency_injector import containers, providers
from redis import Redis

from genie_flow.session_lock import SessionLockManager
from genie_flow.store import StoreManager


class PydanticRedisStoreWrapper(pydantic_redis.Store):

    def __init__(
        self, host: str, port: int, db: int, password: str, life_span_in_seconds: int = 86400
    ):
        redis_config = pydantic_redis.RedisConfig(
            host=host,
            port=port,
            db=db,
            password=password
        )
        super().__init__(
            "genie flow store",
            redis_config,
            life_span_in_seconds=life_span_in_seconds,
        )


class GenieFlowPersistenceContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    redis_object_store = providers.Singleton(
        Redis,
        host=config.model_store.host,
        port=config.model_store.port,
        db=config.model_store.db,
        password=config.model_store.password,
        life_span_in_seconds=config.model_store.life_span_in_seconds,
    )

    redis_lock_store = providers.Singleton(
        Redis,
        host=config.lock_store.host,
        port=config.lock_store.port,
        password=config.lock_store.password,
        db=config.lock_store.db,
    )

    session_lock_manager = providers.Singleton(
        SessionLockManager,
        redis_object_store=redis_object_store,
        redis_lock_store=redis_lock_store,
        lock_expiration_seconds=config.lock_store.lock_expiration_seconds() or 120,
        compression=config.object_compression() or True,
        application_prefix=config.application_prefix() or 'genie-flow'
    )
