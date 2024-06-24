from dependency_injector import containers, providers


class GenieFlowCoreContainer(containers.DeclarativeContainer):

    config = providers.Configuration()
