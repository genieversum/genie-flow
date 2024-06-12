import loguru

from dependency_injector import containers, providers


class GenieFlowCoreContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    logger = providers.Singleton(loguru.Logger, __name__)
