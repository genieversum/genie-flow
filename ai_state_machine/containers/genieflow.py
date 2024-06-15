from celery import Celery
from dependency_injector import containers, providers

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.model.types import ModelKeyRegistryType
from ai_state_machine.session import SessionManager


class GenieFlowContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    model_key_registry = providers.Singleton(ModelKeyRegistryType)

    storage = providers.DependenciesContainer()

    session_manager = providers.Singleton(
        SessionManager,
        session_lock_manager=storage.session_lock_manager,
        model_key_registry=model_key_registry,
    )

    celery_app = providers.Singleton(
        CeleryApp,
        broker=config.celery.broker,
        backend=config.celery.backend,
    )

    genie_environment = providers.Singleton(
        GenieEnvironment,
        config.template_root_path,
        config.pool_size,
        storage.store_manager,
        model_key_registry,
    )
