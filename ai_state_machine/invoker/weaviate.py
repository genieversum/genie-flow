from typing import Optional

import weaviate
from weaviate import WeaviateClient

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.invoker.utils import get_config_value
from ai_state_machine.model.dialogue import DialogueElement


class WeaviateSimilaritySearchInvoker(GenieInvoker):

    def __init__(
            self,
            weaviate_client: WeaviateClient,
            collection: str,
            distance: float,
            limit: int,
    ) -> None:
        self._client = weaviate_client
        self._collection = self._client.collections.get(collection)
        self.distance = distance
        self.limit = limit

    @classmethod
    def _create_client(cls, config: dict[str, str]) -> WeaviateClient:
        http_host = get_config_value(
            config,
            "WEAVIATE_HTTP_HOST",
            "http_host",
            "HTTP Host URI",
        )
        http_port = get_config_value(
            config,
            "WEAVIATE_HTTP_PORT",
            "http_port",
            "HTTP Port number",
        )
        http_secure = get_config_value(
            config,
            "WEAVIATE_HTTP_SECURE",
            "http_secure",
            "HTTP Secure flag",
        )
        grpc_host = get_config_value(
            config,
            "WEAVIATE_GRPC_HOST",
            "grpc_host",
            "GRPC Host URI",
        )
        grpc_port = get_config_value(
            config,
            "WEAVIATE_GRPC_PORT",
            "grpc_port",
            "GRPC Port number",
        )
        grpc_secure = get_config_value(
            config,
            "WEAVIATE_GRPC_SECURE",
            "grpc_secure",
            "GRPC Secure flag",
        )

        return weaviate.connect_to_custom(
            http_host,
            http_port,
            http_secure,
            grpc_host,
            grpc_port,
            grpc_secure,
        )

    @classmethod
    def from_config(cls, config: dict):
        connection_config = config["connection"]
        query_config = config["query"]
        return cls(
            cls._create_client(connection_config),
            query_config["collection"],
            float(query_config["distance"]),
            int(query_config["limit"]),
        )

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]]) -> str:
        results = self._collection.query.near_text(
            query=content,
            distance=self.distance,
            limit=self.limit,
        )
