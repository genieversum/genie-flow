from dependency_injector import containers, providers
from redis import Redis

from genie_flow.session_lock import SessionLockManager


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

    redis_progress_store = providers.Singleton(
        Redis,
        host=config.progress_store.host,
        port=config.progress_store.port,
        password=config.progress_store.password,
        db=config.progress_store.db,
    )

    session_lock_manager = providers.Singleton(
        SessionLockManager,
        redis_object_store=redis_object_store,
        redis_lock_store=redis_lock_store,
        redis_progress_store=redis_progress_store,
        compression=config.object_store.object_compression or True,
        application_prefix=config.object_store.application_prefix or 'genie-flow',
        object_expiration_seconds=config.object_store.expiration_seconds or 120,
        lock_expiration_seconds=config.lock_store.expiration_seconds or 120,
        progress_expiration_seconds=config.progress_store.expiration_seconds or 120,
    )
