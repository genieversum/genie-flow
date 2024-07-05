import json
from typing import Optional

import weaviate
from loguru import logger
from weaviate import WeaviateClient
from weaviate.collections.classes.grpc import MetadataQuery

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.invoker.utils import get_config_value
from ai_state_machine.model.dialogue import DialogueElement


class WeaviateClientFactory:
    """
    A factory to create Weaviate clients. Maintains a singleton but when that singleton
    is not live, will create a new one.

    Configuration is set at initiation of the factory, and then used for the Weaviate client.

    This factory works like a context manager, so can be used as follows:

    ```
    with WeaviateClientFactory() as client:
        client.collections. ...
    ```

    """

    def __init__(self, config: dict[str]):
        """
        Creates a new Weaviate client factory. Configuration should include: `http_host`,
        `http_port`, `http_secure`, `grpc_host`, `grpc_port`, and `grpc_secure`. The values from
        config will be overriden by environment variables, respectively: `WEAVIATE_HTTP_HOST`,
        `WEAVIATE_HTTP_PORT`, `WEAVIATE_HTTP_SECURE`, `WEAVIATE_GRPC_HOST`, `WEAVIATE_GRPC_PORT` and
        `WEAVIATE_GRPC_SECURE`.
        """
        self._client: Optional[WeaviateClient] = None

        self.http_host = get_config_value(
            config,
            "WEAVIATE_HTTP_HOST",
            "http_host",
            "HTTP Host URI",
        )
        self.http_port = get_config_value(
            config,
            "WEAVIATE_HTTP_PORT",
            "http_port",
            "HTTP Port number",
        )
        self.http_secure = get_config_value(
            config,
            "WEAVIATE_HTTP_SECURE",
            "http_secure",
            "HTTP Secure flag",
        )
        self.grpc_host = get_config_value(
            config,
            "WEAVIATE_GRPC_HOST",
            "grpc_host",
            "GRPC Host URI",
        )
        self.grpc_port = get_config_value(
            config,
            "WEAVIATE_GRPC_PORT",
            "grpc_port",
            "GRPC Port number",
        )
        self.grpc_secure = get_config_value(
            config,
            "WEAVIATE_GRPC_SECURE",
            "grpc_secure",
            "GRPC Secure flag",
        )

    def __enter__(self):
        if self._client is None or not self._client.is_live():
            logger.debug("No live weaviate client, creating a new one")
            if self._client is not None:
                self._client.close()
            self._client = weaviate.connect_to_custom(
                self.http_host,
                self.http_port,
                self.http_secure,
                self.grpc_host,
                self.grpc_port,
                self.grpc_secure,
            )
        return self._client

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class WeaviateSimilaritySearchInvoker(GenieInvoker):
    """
    A Genie Invoker to retrieve documents from Weaviate, using similarity search.

    This is the basic Weaviate similarity search invoker that reads `distance`, and `limit` from
    the `meta.yaml` file that is used to create this invoker.
    """

    def __init__(
            self,
            connection_config: dict[str],
            collection: str,
            distance: float,
            limit: int,
    ) -> None:
        self.client_factory: WeaviateClientFactory = WeaviateClientFactory(connection_config)
        self.collection = collection
        self.distance = distance
        self.limit = limit

    @classmethod
    def from_config(cls, config: dict):
        """
        Creates a Weaviate SimilaritySearchInvoker from configuration. Configuration should include
        a key `connection` which contains all keys for setting up the connection. Should also
        include the key `query`, with settings for `collection`, `distance`, and `limit`.
        """
        connection_config = config["connection"]
        query_config = config["query"]
        return cls(
            connection_config,
            query_config["collection"],
            float(query_config["distance"]),
            int(query_config["limit"]),
        )

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]]) -> str:
        """
        This invokes the similarity search, based on the configuration for `collection`, `distance`,
        and `limit'. Will return a JSON version of the documents retrieved, containing:

            `_id` - the document id as used by Weaviate,
            `distance` - the distance reported for the similarity search,
            all other properties that have been stored with the object
        """
        logger.debug(f"invoking weaviate near text search with '{content}'")
        with self.client_factory as client:
            collection = client.collections.get(self.collection)
            results = collection.query.near_text(
                query=content,
                distance=self.distance,
                limit=self.limit,
                return_metadata=MetadataQuery(distance=True)
            )
            return json.dumps(
                [
                    dict(
                        _id=str(o.uuid),
                        distance=o.metadata.distance,
                        **o.properties,
                    )
                    for o in results.objects
                ]
            )
