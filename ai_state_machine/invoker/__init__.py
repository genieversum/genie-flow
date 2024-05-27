from abc import ABC, abstractmethod


class GenieInvoker(ABC):
    """
    The super class of all Genie Invokers. The standard interface to invoke large language models,
    database retrievals, etc.

    This is ab abstraction around calls that take a text content and pass that to a lower level
    service for processing. The returned value is always a result string.

    This class is subclassed with specific classes for external services.
    """

    @abstractmethod
    def invoke(self, content: str) -> str:
        """
        Invoke the underlying service with the supplied content.

        :param content: The text content to invoke the underlying service.
        :return: The result string.
        """
        raise NotImplementedError()
