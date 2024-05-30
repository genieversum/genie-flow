from typing import Optional

from ai_state_machine.invoker import GenieInvoker
from ai_state_machine.model import DialogueElement


class VerbatimInvoker(GenieInvoker):

    @classmethod
    def from_config(cls, config: dict):
        return cls()

    def invoke(self, content: str, dialogue: Optional[list[DialogueElement]]) -> str:
        return content
