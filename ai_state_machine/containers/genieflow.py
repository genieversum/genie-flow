from celery import Celery
from dependency_injector import containers, providers

from ai_state_machine.app import create_fastapi_app
from ai_state_machine.containers.core import GenieFlowCoreContainer
from ai_state_machine.containers.persistence import GenieFlowPersistenceContainer
from ai_state_machine.celery import CeleryManager
from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.model.types import ModelKeyRegistryType
from ai_state_machine.session import SessionManager


class GenieFlowContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    core = providers.Container(
        GenieFlowCoreContainer,
        config=config,
    )

    model_key_registry = providers.Singleton(ModelKeyRegistryType)

    storage = providers.Container(
        GenieFlowPersistenceContainer,
        config=config.persistence,
    )

    genie_environment = providers.Singleton(
        GenieEnvironment,
        config.genie_environment.template_root_path,
        config.genie_environment.pool_size,
        storage.store_manager,
        model_key_registry,
    )

    session_manager = providers.Singleton(
        SessionManager,
        session_lock_manager=storage.session_lock_manager,
        model_key_registry=model_key_registry,
        genie_environment=genie_environment,
    )

    celery_app = providers.Singleton(
        Celery,
        main="genie_flow",
        broker=config.celery.broker,
        backend=config.celery.backend,
        redis_socket_timeout=config.celery.redis_socket_timeout,
        redis_socket_connect_timeout=config.celery.redis_socket_connect_timeout,
    )

    celery_manager = providers.Singleton(
        CeleryManager,
        celery_app,
        storage.session_lock_manager,
        storage.store_manager,
        genie_environment,
    )

    fastapi_app = providers.Resource(
        create_fastapi_app,
        session_manager=session_manager,
        config=config.api,
    )
