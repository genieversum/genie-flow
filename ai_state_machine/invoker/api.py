import json
from typing import Optional

from requests import Session, Response

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.model.dialogue import DialogueElement
from loguru import logger


class RequestFactory:

    def __init__(self, config: dict[str]):
        self.session: Optional[Session] = None

        self.method = config["method"]
        self.endpoint = config["endpoint"]
        self.headers = config["headers"]

    def request(self, params: dict[str, str]) -> Response:
        if self.session is None:
            self.session = Session()
            self.session.headers.update(self.headers)

        return self.session.request(
            method=self.method,
            url=self.endpoint,
            params=params,
        )


class APIInvoker(GenieInvoker):

    def __init__(
            self,
            connection_config: dict[str],
    ):
        self.connection_factory = RequestFactory(connection_config)

    @classmethod
    def from_config(cls, config: dict):
        connection_config = config["connection"]
        return cls(connection_config)

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]]) -> str:
        logger.debug(f"invoking API with '{content}'")
        query_params = json.loads(content)
        response = self.connection_factory.request(query_params)
        response.raise_for_status()
        return json.dumps(response.json())
