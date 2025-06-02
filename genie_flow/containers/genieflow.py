from celery import Celery
from dependency_injector import containers, providers

from genie_flow.app import create_fastapi_app
from genie_flow.containers.core import GenieFlowCoreContainer
from genie_flow.containers.perm_persistence import GenieFlowPermanentPersistenceContainer
from genie_flow.containers.persistence import GenieFlowPersistenceContainer
from genie_flow.celery import CeleryManager
from genie_flow.environment import GenieEnvironment
from genie_flow.model.types import ModelKeyRegistryType
from genie_flow.session import SessionManager
from genie_flow_invoker.factory import InvokerFactory


class GenieFlowContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    core = providers.Container(
        GenieFlowCoreContainer,
        config=config,
    )

    model_key_registry = providers.Singleton(ModelKeyRegistryType)

    invoker_factory = providers.Factory(
        InvokerFactory,
        config=config.invokers,
    )

    storage = providers.Container(
        GenieFlowPersistenceContainer,
        config=config.persistence,
    )

    permanent_storage = providers.Container(
        GenieFlowPermanentPersistenceContainer,
        config=config.persistence,
    )

    genie_environment = providers.Singleton(
        GenieEnvironment,
        config.genie_environment.template_root_path,
        config.genie_environment.pool_size,
        model_key_registry,
        invoker_factory,
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
        genie_environment,
        update_mongo_period = config.celery.update_mongo_period or 60.0
    )

    session_manager = providers.Singleton(
        SessionManager,
        session_lock_manager=storage.session_lock_manager,
        model_key_registry=model_key_registry,
        genie_environment=genie_environment,
        celery_manager=celery_manager,
    )

    fastapi_app = providers.Resource(
        create_fastapi_app,
        session_manager=session_manager,
        config=config.api,
        cors_settings=config.cors
    )
