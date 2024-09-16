import json
from typing import Optional

from requests import Session, Response

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.model.dialogue import DialogueElement
from loguru import logger


class RequestFactory:

    def __init__(
            self,
            method: str,
            endpoint: str,
            headers: dict[str, str],
    ):
        """
        A request factory creates and calls a Request object with predefined attributes.
        The attributes that are predefined are given as parameters when creating this request
        factory.

        :param method: The HTTP method to use.
        :param endpoint: The URL endpoint.
        :param headers: A dictionary of headers that need to be added to the request.
        """
        self.session: Optional[Session] = None

        self.method = method
        self.endpoint = endpoint
        self.headers = headers

    def request(self, params: dict[str, str]) -> Response:
        """
        Conduct the request using the provided attributes.

        :param params: A dictionary of parameters that need to be added to the request.
        :return: A Response object containing the response.
        """
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
        """
        The API Invoker conducts a request to an API. It expects a configuration for the
        connection, giving the `method`, the `endpoint` and the `headers` dictionary.

        NB: currently only support GET requests where the content of the invocation should
        be a JSON object where the keys and values are sent as query parameters.

        :param connection_config: A dictionary containing the connection configuration.
        """
        method: str = connection_config["method"]
        endpoint: str = connection_config["endpoint"]
        headers: dict[str, str] = connection_config["headers"]

        if method.upper() != "GET":
            raise ValueError("API invoker currently only supports GET requests.")

        self.connection_factory = RequestFactory(method, endpoint, headers)

    @classmethod
    def from_config(cls, config: dict):
        """
        The config should be a dictionary containing the connection configuration under the
        key `connection`.
        """
        connection_config = config["connection"]
        return cls(connection_config)

    def invoke(self, content: str) -> str:
        """
        Conducts a request to an API using the provided content. The content is expected to be
        a JSON object where the keys and values are sent as query parameters.

        We are assuming the call will return a JSON object, which is then returned in JSON
        as the result of the invocation.

        :param content: The content of the invocation. This content needs to be a JSON string
        that contains all keys that will be passed as query parameters.
        :return: A JSON representation of the response from the API call.
        """
        logger.debug(f"invoking API with '{content}'")
        query_params = json.loads(content)
        response = self.connection_factory.request(query_params)
        response.raise_for_status()
        if response.status_code == 204 or response.text == "":
            return ""
        return json.dumps(response.json())
