from typing import Optional

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.model.dialogue import DialogueElement


class VerbatimInvoker(GenieInvoker):

    @classmethod
    def from_config(cls, config: dict):
        return cls()

    def invoke(self, content: str) -> str:
        """
        Invokes the verbatim invoker that just copies the content as a result.

        :param content: Any text content
        :returns: the `str` version of the content
        """
        return str(content)
