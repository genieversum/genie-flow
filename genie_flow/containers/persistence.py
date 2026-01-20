from dependency_injector import containers, providers
from redis import Redis, ConnectionPool

from genie_flow.permanent_storage import PermanentStorageManager, PermanentStorageManagerProtocol, \
    DummyStorageManager
from genie_flow.session_lock import SessionLockManager


def _create_permanent_storage_manager(
        config: providers.Configuration,
) -> PermanentStorageManagerProtocol:
    if not config:
        return DummyStorageManager()
    return PermanentStorageManager(
        database_path=config.database_path(),
        blob_path=config.blob_path(),
        compress=config.compress() or False,
        blob_directory_depth=config.blob_directory_depth() or 2,
    )


class GenieFlowPersistenceContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    redis_object_store_pool = providers.Singleton(
        ConnectionPool,
        host=config.object_store.host,
        port=config.object_store.port,
        db=config.object_store.db,
        password=config.object_store.password,
        max_connections=config.object_store.max_connections or 200,
    )

    redis_object_store = providers.Singleton(
        Redis,
        connection_pool=redis_object_store_pool,
    )

    redis_lock_store_pool = providers.Singleton(
        ConnectionPool,
        host=config.lock_store.host,
        port=config.lock_store.port,
        db=config.lock_store.db,
        password=config.lock_store.password,
        max_connections=config.lock_store.max_connections or 200,
    )

    redis_lock_store = providers.Singleton(
        Redis,
        connection_pool=redis_lock_store_pool,
    )

    redis_progress_store_pool = providers.Singleton(
        ConnectionPool,
        host=config.progress_store.host,
        port=config.progress_store.port,
        db=config.progress_store.db,
        password=config.progress_store.password,
        max_connections=config.progress_store.max_connections or 200,
    )

    redis_progress_store = providers.Singleton(
        Redis,
        connection_pool=redis_progress_store_pool,
    )

    permanent_store_manager = providers.Singleton(
        _create_permanent_storage_manager,
        config.permanent_store,
    )

    session_lock_manager = providers.Singleton(
        SessionLockManager,
        redis_object_store=redis_object_store,
        redis_lock_store=redis_lock_store,
        redis_progress_store=redis_progress_store,
        compression=config.object_store.object_compression or True,
        application_prefix=config.application_prefix or 'genie-flow',
        object_expiration_seconds=config.object_store.expiration_seconds or 120,
        lock_expiration_seconds=config.lock_store.expiration_seconds or 120,
        progress_expiration_seconds=config.progress_store.expiration_seconds or 120,
    )

