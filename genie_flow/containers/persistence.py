from typing import Optional

from dependency_injector import containers, providers
from redis import Redis, ConnectionPool

from genie_flow.permanent_storage.embedded_store import EmbeddedStorageManager
from genie_flow.permanent_storage.postgres_store import PostgresFileStoreManager
from genie_flow.session_lock import SessionLockManager


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
        decode_responses=False,
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

    permanent_store = providers.Selector(
        config.permanent_store.type or "none",
        none=providers.Object(None),
        embedded=providers.Singleton(
            EmbeddedStorageManager,
            database_path=config.permanent_store.config.database_path,
            blob_path=config.permanent_store.config.blob_path,
            compress=config.permanent_store.config.compress or False,
            database_retries=config.permanent_store.config.database_retries or 5,
            blob_directory_depth=config.permanent_store.config.blob_directory_depth or 2,
            critical_watermark=config.permanent_store.config.critical_watermark or 120,
            max_writes=config.permanent_store.config.max_writes or 32,
        ),
        postgres=providers.Singleton(
            PostgresFileStoreManager,
        )
    )

    session_lock_manager = providers.Singleton(
        SessionLockManager,
        redis_object_store=redis_object_store,
        redis_lock_store=redis_lock_store,
        redis_progress_store=redis_progress_store,
        permanent_store=permanent_store,
        compression=config.object_store.object_compression or True,
        application_prefix=config.application_prefix or 'genie-flow',
        object_expiration_seconds=config.object_store.expiration_seconds or 120,
        lock_expiration_seconds=config.lock_store.expiration_seconds or 120,
        progress_expiration_seconds=config.progress_store.expiration_seconds or 120,
    )

