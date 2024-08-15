import json
from hashlib import md5
from typing import Optional, LiteralString

from loguru import logger
from neo4j import GraphDatabase, Driver, Result, Record, Query
from neo4j.exceptions import ResultConsumedError
from pydantic import BaseModel, Field

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.invoker.utils import get_config_value, ConfigReader
from ai_state_machine.model.dialogue import DialogueElement


_DRIVER: Optional[Driver] = None


def _create_driver(config: dict):
    logger.debug("Creating driver from config {}", config)
    db_uri = config["database_uri"]
    db_auth = (config["username"], config["password"])
    return GraphDatabase.driver(uri=db_uri, auth=db_auth)


RecordFieldBaseType = str | int | float | None
RecordFieldExtendedType = (
        RecordFieldBaseType |
        list[RecordFieldBaseType] |
        dict[str, RecordFieldBaseType]
)
RecordType = list[RecordFieldExtendedType]

class Neo4jQueryResult(BaseModel):
    headers: list[str] = Field(
        default_factory=list,
        description="List of headers returned by neo4j query",
    )
    records: list[RecordType] = Field(
        default_factory=list,
        description="List of list of values returned by neo4j query",
    )
    has_more: bool = Field(
        default=False,
        description="True if there are more records available from the query that have"
                    "not been fetched because of limit settings",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message returned by neo4j query",
    )

    @classmethod
    def from_neo4j_result(
            cls,
            records: list[Record],
            keys: tuple[str],
            has_more: bool,
    ) -> "Neo4jQueryResult":
        return cls(
            headers=keys,
            records=[record for record in records],
            has_more=has_more,
        )


class Neo4jClient:

    def __init__(
            self,
            driver: Driver,
            database_name: str,
            limit: int,
            query_timeout: float,
            execute_write_queries: bool,
    ):
        self.driver = driver
        self.database_name = database_name
        self.limit = limit
        self.query_timeout = query_timeout
        self.execute_write_queries = execute_write_queries

    def _limiting_transformer(self, result: Result) -> Neo4jQueryResult:
        records = result.fetch(self.limit)
        keys = result.keys()
        has_more = False
        try:
            peek = result.peek()
            logger.debug("peeking returns: {peek}", peek=str(peek))
            has_more = peek is not None
        except ResultConsumedError:
            pass
        return Neo4jQueryResult.from_neo4j_result(records, keys, has_more)

    def execute(self, query_string: LiteralString) -> str:
        logger.debug("executing query {query_string}", query_string=query_string)
        logger.info(
            "executing query hash {query_hash}",
            query_hash=md5(query_string.encode("utf-8")).hexdigest(),
        )
        query = Query(query_string, timeout=self.query_timeout)
        try:
            result = self.driver.execute_query(
                query_=query,
                database_=self.database_name,
                result_transformer_=self._limiting_transformer,
            )
            logger.info(
                "executed query hash {query_hash}",
                query_hash=md5(query_string.encode("utf-8")).hexdigest(),
            )
            return result.model_dump_json()
        except Exception as e:
            result = Neo4jQueryResult(error=str(e))
            return result.model_dump_json()


class Neo4jClientFactory:
    def __init__(self, config: dict):
        global _DRIVER

        config_reader = ConfigReader(config, "NEO4J")
        if _DRIVER is None:
            config_to_use = dict(
                database_uri=config_reader.get_config_value("database_uri"),
                username=config_reader.get_config_value("username"),
                password=config_reader.get_config_value("password"),
            )
            _DRIVER = _create_driver(config_to_use)
            _DRIVER.verify_connectivity()

        self.database_name = config_reader.get_config_value("database_name")
        self.limit = config_reader.get_config_value("limit",1000)
        self.query_timeout = config_reader.get_config_value("query_timeout", None)
        self.execute_write_queries = config_reader.get_config_value("write_queries", False)

    def __enter__(self):
        return Neo4jClient(
            _DRIVER,
            self.database_name,
            self.limit,
            self.query_timeout,
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
        - query_timeout: (NEO4J_QUERY_TIMEOUT) the number of seconds to wait for a query to
        execute, otherwise cancel the query. A zero indicates indefinite wait. None (the
        default) will use the default on the server.
        - write_queries: (NEO4J_WRITE_QUERIES) indicates whether we allow write-queries.
        Defaults to False if not provided.
        """
        logger.debug("Creating Neo4jInvoker from config {}", config)
        return cls(config)

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]]) -> str:
        query_hash = md5(content.encode("utf-8")).hexdigest()
        logger.info(
            "invoking neo4j query with query hash {query_hash}",
            query_hash=query_hash,
        )
        with self.client_factory as client:
            result = client.execute(content)
        logger.debug(
            "invoking neo4j query {query} resulted in {result}",
            query=content,
            result=result,
        )
        logger.info(
            "finished invoking neo4j query {query_hash} with result {result_hash}",
            query_hash=query_hash,
            result_hash=md5(result.encode("utf-8")).hexdigest(),
        )
        return result
