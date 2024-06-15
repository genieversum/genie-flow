from dependency_injector import providers, containers
from fastapi import FastAPI


class GenieFlowAPIContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    genie_environment = providers.DependenciesContainer()

    fastapi_app = providers.Singleton(
        FastAPI,
        title="GenieFlow",
        summary="Genie Flow API",
        **config(),
    )
