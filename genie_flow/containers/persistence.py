from typing import Optional

from dependency_injector import containers, providers
from redis import Redis, ConnectionPool

from genie_flow.permanent_storage.abstract_file_store import FileStorageConfig
from genie_flow.permanent_storage.embedded_store import EmbeddedStorageManager
from genie_flow.permanent_storage.postgres_store import PostgresFileStoreManager, PostgresConfig
from genie_flow.session_lock import SessionLockManager


def _create_file_storage_config(file_storage_config):
    return FileStorageConfig(
        file_storage_url=file_storage_config.file_storage_url,
        compress=file_storage_config.compress or False,
        shard_depth=file_storage_config.shard_depth or 2,
        file_storage_options=file_storage_config.options or {},
    )


def _create_embedded_file_store(store_config):
    return EmbeddedStorageManager(
        critical_watermark =store_config.critical_watermark or 120,
        max_writes =store_config.max_writes or 32,
        file_storage_config = _create_file_storage_config(store_config.file_storage_config),
        database_path = store_config.database_config.path,
        database_retries = store_config.database_config.retries or 5,
    )


def _create_postgres_file_store(store_config):
    pg_config = store_config.postgres_config
    database_config = PostgresConfig(
        host=pg_config.host,
        port=pg_config.port,
        database=pg_config.database,
        user=pg_config.user,
        password=pg_config.password,
        max_pool_size=pg_config.max_pool_size,
        timeout=pg_config.timeout,
    )
    return PostgresFileStoreManager.from_config(
        critical_watermark =store_config.critical_watermark or 120,
        max_writes =store_config.max_writes or 32,
        file_storage_config = _create_file_storage_config(store_config.file_storage_config),
        database_config=database_config,
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
            _create_embedded_file_store,
            config.permanent_store.config,
        ),
        postgres=providers.Singleton(
            _create_postgres_file_store,
            config.permanent_store.config,
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

