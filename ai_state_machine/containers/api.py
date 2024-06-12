from dependency_injector import providers, containers
from fastapi import FastAPI


class GenieFlowAPIContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    genie_environment = providers.DependenciesContainer()

    fastapi_app = providers.Singleton(
        FastAPI,
        title="GenieFlow",
        summary="Genie Flow API",
        description=__doc__,
        debug=config.debug() or False,
        openapi_url=config.openapi_url() or None,
        docs_url=config.docs_url() or None,
        redoc_url=config.redoc_url() or None,
        terms_of_service=config.terms_of_service() or None,
        contact=config.contact() or None,
        license_info=config.license() or None,
        root_path=config.root_path() or "/api/v1",
    )
