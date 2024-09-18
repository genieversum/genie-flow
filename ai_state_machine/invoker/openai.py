import json
import logging
from abc import ABC
from json import JSONDecodeError
from typing import Optional

import openai
from loguru import logger
from openai.lib.azure import AzureOpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
)
from openai.types.chat.completion_create_params import ResponseFormat

from ai_state_machine.invoker.genie import GenieInvoker
from ai_state_machine.invoker.utils import get_config_value


_CHAT_COMPLETION_MAP = {
    "system": ChatCompletionSystemMessageParam,
    "assistant": ChatCompletionAssistantMessageParam,
    "user": ChatCompletionUserMessageParam,
}


def chat_completion_message(
    dialogue_element: dict[str, str],
) -> ChatCompletionMessageParam:
    try:
        role = dialogue_element["role"]
    except KeyError:
        raise KeyError("not provided a role")

    try:
        chat_cls = _CHAT_COMPLETION_MAP[role]
    except KeyError:
        raise KeyError(f"unknown chat role '{role}'")

    try:
        content = dialogue_element["content"]
    except KeyError:
        raise KeyError("not provided content")

    return chat_cls(role=role, content=content)


class AbstractAzureOpenAIInvoker(GenieInvoker, ABC):
    """
    Abstract base class for Azure OpenAI clients. Invocations will be passed on to an
    AzureOpenAI client.
    """

    def __init__(self, openai_client: AzureOpenAI, deployment_name: str):
        """
        :param openai_client: Azure OpenAI client to pass invocations to
        :param deployment_name: name of the Azure OpenAI deployment
        """
        self._client = openai_client
        self._deployment_name = deployment_name

    @classmethod
    def _create_client(cls, config: dict[str, str]) -> AzureOpenAI:
        api_key = get_config_value(
            config,
            "AZURE_OPENAI_API_KEY",
            "api_key",
            "API Key",
        )

        api_version = get_config_value(
            config,
            "AZURE_OPENAI_API_VERSION",
            "api_version",
            "API Version",
        )

        endpoint = get_config_value(
            config,
            "AZURE_OPENAI_ENDPOINT",
            "endpoint",
            "Endpoint",
        )
        if endpoint is None:
            raise ValueError("No endpoint provided")

        return openai.AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )


class AzureOpenAIChatInvoker(AbstractAzureOpenAIInvoker):
    """
    A Chat Completion invoker for Azure OpenAI clients.
    """

    @classmethod
    def from_config(cls, config: dict[str, str]) -> "AzureOpenAIChatInvoker":
        return cls(
            openai_client=cls._create_client(config),
            deployment_name=get_config_value(
                config,
                "AZURE_OPENAI_DEPLOYMENT_NAME",
                "deployment_name",
                "Deployment Name",
            )
        )

    @property
    def _response_format(self) -> Optional[ResponseFormat]:
        return None

    def invoke(self, content: str) -> str:
        """
        Invoking the chat API of OpenAI involves sending a list of chat elements. The content
        passed to this should be a JSON list, as follows:

        .. code-block:: json

        [
            {
                "role": "<role name>",
                "content": "<content>"
            }
        ]

        Here, `role` can be either "system", "assistant" or "user".

        :param content: JSON version of a list of all chat elements that need to be taken into
        account for the chat invocation.

        :returns: the JSON version of the returned response from the API
        """
        try:
            messages_raw = json.loads(content)
        except JSONDecodeError:
            logger.error("failed to decode JSON content")
            logger.debug("cannot parse the following content as JSON: '{}'", content)
            raise ValueError("Invoker input cannot be parsed. Is it JSON?")

        messages = [chat_completion_message(element) for element in messages_raw]
        logger.debug("Invoking OpenAI Chat with the following prompts: {}", messages)
        response = self._client.chat.completions.create(
            model=self._deployment_name,
            messages=messages,
            response_format=self._response_format,
        )
        try:
            return response.choices[0].message.content
        except Exception as e:
            logging.exception("Failed to call OpenAI", exc_info=e)
            raise


class AzureOpenAIChatJSONInvoker(AzureOpenAIChatInvoker):
    """
    A chat completion invoker for Azure OpenAI clients witch will return a JSON string.

    **Important:** when using JSON mode, you **must** also instruct the model to
              produce JSON yourself via a system or user message. Without this, the model may
              generate an unending stream of whitespace until the generation reaches the token
              limit

    """

    @property
    def _response_format(self) -> Optional[ResponseFormat]:
        return ResponseFormat(type="json_object")

    def invoke(self, content: str) -> str:
        if "json" not in content.lower():
            logging.error(
                "sending a JSON invocation to Azure OpenAI without mentioning "
                "the word 'json'."
            )
            raise ValueError("The JSON invoker prompt needs to contain the word 'json'")
        return super(AzureOpenAIChatJSONInvoker).invoke(content)
