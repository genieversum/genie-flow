import logging
from abc import ABC
from typing import Optional

from openai._base_client import BaseClient
from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionSystemMessageParam, \
    ChatCompletionUserMessageParam, ChatCompletionAssistantMessageParam
from openai.types.chat.completion_create_params import ResponseFormat

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.model import DialogueElement


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


class AzureOpenAIChatInvoker(AbstractAzureOpenAIInvoker, ABC):
    """
    A Chat Completion invoker for Azure OpenAI clients.
    """

    @property
    def _response_format(self) -> Optional[ResponseFormat]:
        return None

    def invoke(self, content: str, dialogue: list[DialogueElement]) -> str:
        messages = [
            ChatCompletionAssistantMessageParam(
                role="assistant",
                content=element.actor_text,
            ) if element.actor == "LLM" else
            ChatCompletionUserMessageParam(
                role="user",
                content=element.actor_text,
            )
            for element in dialogue
        ]
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
    A chat completion invoker for Azure OpenAI clients witch will return JSON strings.
    """

    def _response_format(self) -> Optional[ResponseFormat]:
        return ResponseFormat(type="json_object")
