from celery import Celery
from dependency_injector import containers, providers


class CeleryApp(Celery):
    def __init__(self, broker: str, backend: str):
        super().__init__(
            "genie_flow",
            broker=f"{broker}",
            backend=f"{backend}",
            redis_socket_timeout=4.0,
            redis_socket_connect_timeout=4.0,
        )


class GenieFlowCeleryContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    genie_environment = providers.DependenciesContainer()

    celery_app = providers.Singleton(
        CeleryApp,
        broker=config.broker,
        backend=config.backend,
    )
