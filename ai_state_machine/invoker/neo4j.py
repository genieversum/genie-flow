import json
from hashlib import md5
from typing import Optional, LiteralString

from dependency_injector import containers, providers
from loguru import logger
from neo4j import GraphDatabase, Driver

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.invoker.utils import get_config_value
from ai_state_machine.model.dialogue import DialogueElement


_DRIVER: Optional[Driver] = None


def _create_driver(config: dict):
    logger.debug("Creating driver from config {}", config)
    db_uri = config["database_uri"]
    db_auth = (config["username"], config["password"])
    return GraphDatabase.driver(uri=db_uri, auth=db_auth)


# class _Neo4jDriverContainer(containers.DeclarativeContainer):
#     config = providers.Configuration()
#
#     driver = providers.Resource(
#         _create_driver,
#         config=config,
#     )


class Neo4jClientFactory:

    class Neo4jClient:

        def __init__(
                self,
                driver: Driver,
                database_name: str,
                limit: int,
                execute_write_queries: bool,
        ):
            self.driver = driver
            self.database_name = database_name
            self.limit = limit
            self.execute_write_queries = execute_write_queries

        def execute(self, query: LiteralString) -> str:
            records, summary, keys = self.driver.execute_query(
                query_=query,
                database_=self.database_name,
            )
            logger.info("executed query, result summary {}", summary)
            return json.dumps([record for record in records[:self.limit]])

    def __init__(self, config: dict):
        global _DRIVER

        if _DRIVER is None:
            config_to_use = dict(
                database_uri=get_config_value(
                    config,
                    "NEO4J_DATABASE_URI",
                    "database_uri",
                    "Neo4j Database URI",
                ),
                username=get_config_value(
                    config,
                    "NEO4J_USERNAME",
                    "username",
                    "Neo4j Username",
                ),
                password=get_config_value(
                    config,
                    "NEO4J_PASSWORD",
                    "password",
                    "Neo4j Password",
                ),
            )
            _DRIVER = _create_driver(config_to_use)
            _DRIVER.verify_connectivity()

        self.database_name = get_config_value(
            config,
            "NEO4J_DATABASE_NAME",
            "database_name",
            "Neo4j Database Name",
        )
        self.limit = get_config_value(
            config,
            "NEO4J_LIMIT",
            "limit",
            "Neo4j Limit of returned records",
            1000,
        )
        self.execute_write_queries = get_config_value(
            config,
            "NEO4J_WRITE_QUERIES",
            "write_queries",
            "Neo4j executes Write queries",
            False,
        )

    def __enter__(self):
        return Neo4jClientFactory.Neo4jClient(
            _DRIVER,
            self.database_name,
            self.limit,
            self.execute_write_queries,
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class Neo4jInvoker(GenieInvoker):

    def __init__(self, config: dict):
        self.client_factory = Neo4jClientFactory(config)

    @classmethod
    def from_config(cls, config: dict):
        """
        Creates a Neo4jInvoker instance from configuration.
        The config in the `meta.yaml` file should contain the following keys. All these keys
        also have an environment variable alternative that will be used if the key is not
        provided.
        - database_uri: (NEO4J_DATABASE_URI) the URI to the database server
        - username: (NEO4J_USERNAME) the username to connect to the database server
        - password: (NEO4J_PASSWORD) the password to connect to the database server
        - database_name: (NEO4J_DATABASE_NAME) (optional) the database name to connect to on
        the database server. If none provided, defaults to the user"s home database.
        - limit: (NEO4J_LIMIT) the maximum number of records returned by a query. Defaults to
        1000 if there is no limit specified in the `meta.yaml` file nor in an environment
        variable.
        - write_queries: (NEO4J_WRITE_QUERIES) indicates whether we allow write-queries.
        Defaults to False if not provided.
        """
        logger.debug("Creating Neo4jInvoker from config {}", config)
        return cls(config)

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]]) -> str:
        logger.info(
            "invoking neo4j query with query '{}'",
            md5(content.encode("utf-8")).hexdigest(),
        )
        with self.client_factory as client:
            result = client.execute(content)
        logger.info(
            "finished invoking neo4j query {} with result {}",
            md5(content.encode("utf-8")).hexdigest(),
            md5(result.encode("utf-8")).hexdigest(),
        )
        return result
