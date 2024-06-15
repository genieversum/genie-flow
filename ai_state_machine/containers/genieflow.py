from celery import Celery
from dependency_injector import containers, providers

import ai_state_machine.containers
from ai_state_machine.celery import CeleryManager
from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.model.types import ModelKeyRegistryType
from ai_state_machine.session import SessionManager


class GenieFlowContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    core = providers.Container(
        ai_state_machine.containers.GenieFlowCoreContainer,
        config=config,
    )

    model_key_registry = providers.Singleton(ModelKeyRegistryType)

    storage = providers.Container(
        ai_state_machine.containers.GenieFlowPersistenceContainer,
        config=config.persistence,
    )

    session_manager = providers.Singleton(
        SessionManager,
        session_lock_manager=storage.session_lock_manager,
        model_key_registry=model_key_registry,
    )

    genie_environment = providers.Singleton(
        GenieEnvironment,
        config.template_root_path,
        config.pool_size,
        storage.store_manager,
        model_key_registry,
    )

    celery_app = providers.Singleton(
        Celery,
        "genie_flow",
        **config.celery(),
    )

    celery_manager = providers.Singleton(
        CeleryManager,
        celery_app,
        storage.session_lock_manager,
        storage.store_manager,
        genie_environment,
    )
