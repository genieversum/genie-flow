import logging
import os
from abc import ABC
from typing import Optional

import openai
from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionSystemMessageParam, \
    ChatCompletionUserMessageParam, ChatCompletionAssistantMessageParam, ChatCompletionMessageParam
from openai.types.chat.completion_create_params import ResponseFormat

from ai_state_machine.invoker.genie import GenieInvoker
from ai_state_machine.model import DialogueElement


_CHAT_COMPLETION_MAP = {
    "system": ChatCompletionSystemMessageParam,
    "assistant": ChatCompletionAssistantMessageParam,
    "user": ChatCompletionUserMessageParam,
}


def chat_completion_message(dialogue_element: DialogueElement) -> ChatCompletionMessageParam:
    try:
        return _CHAT_COMPLETION_MAP[dialogue_element.actor](
            role=dialogue_element.actor,
            content=dialogue_element.actor_text,
        )
    except KeyError:
        raise ValueError(f"Unexpected actor type: {dialogue_element.actor}")


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
        return openai.AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY") or config["api_key"],
            api_version=config["api_version"],
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT") or config["azure_endpoint"],
        )


class AzureOpenAIChatInvoker(AbstractAzureOpenAIInvoker):
    """
    A Chat Completion invoker for Azure OpenAI clients.
    """

    @classmethod
    def from_config(cls, config: dict[str, str]) -> "AzureOpenAIChatInvoker":
        return cls(
            openai_client=cls._create_client(config),
            deployment_name=config["deployment_name"],
        )

    @property
    def _response_format(self) -> Optional[ResponseFormat]:
        return None

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]] = None) -> str:
        if dialogue is None:
            dialogue = []
        messages = [chat_completion_message(element) for element in dialogue]
        messages.append(
            ChatCompletionUserMessageParam(
                role="user",
                content=content,
            )
        )
        response = self._client.chat.completions.create(
            model=self._deployment_name,
            messages=messages,
            response_format=self._response_format,
        )
        try:
            return response.choices[0].message.content
        except Exception as e:
            logging.warning(f"Failed to call OpenAI: {str(e)}")
            return f"** call to OpenAI API failed; error: {str(e)}"


class AzureOpenAIChatJSONInvoker(AzureOpenAIChatInvoker):
    """
    A chat completion invoker for Azure OpenAI clients witch will return a JSON string.
    """

    @property
    def _response_format(self) -> Optional[ResponseFormat]:
        return ResponseFormat(type="json_object")
