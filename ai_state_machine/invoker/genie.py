from abc import ABC, abstractmethod
from typing import Optional

from ai_state_machine.model.dialogue import DialogueElement


class GenieInvoker(ABC):
    """
    The super class of all Genie Invokers. The standard interface to invoke large language models,
    database retrievals, etc.

    This is ab abstraction around calls that take a text content and pass that to a lower level
    service for processing. The returned value is always a result string.

    This class is subclassed with specific classes for external services.
    """

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict):
        raise NotImplementedError()

    @abstractmethod
    def invoke(self, content: str) -> str:
        """
        Invoke the underlying service with the supplied content and dialogue.

        :param content: The text content to invoke the underlying service. The format of
        this string is Invoker dependent. Some may simply expect a string, others may
        need to get a structured document as string - for instance a JSON string - that
        incorporates the values that one needs to pass.
        :return: The result string.
        """
        raise NotImplementedError()
