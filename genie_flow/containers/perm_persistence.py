from dependency_injector import containers, providers
from pymongo import MongoClient


class GenieFlowPermanentPersistenceContainer(containers.DeclarativeContainer):

    config = providers.Configuration()

    mongo_store = providers.Singleton(
        MongoClient,
        host=config.mongo_store.host,
        port=config.mongo_store.port,
        username=config.mongo_store.username,
        password=config.mongo_store.password,
        authSource=config.mongo_store.db,
    )
