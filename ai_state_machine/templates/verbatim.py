from typing import Any

from ai_state_machine.templates import GenieTemplate


class VerbatimTemplate(GenieTemplate):
    """
    A template that returns a verbatim string with no attempt to use any data context.
    """

    def __init__(self, content: str):
        super().__init__(None)
        self._content = content

    def _render(self, data_context: dict[str, Any]) -> str:
        """
        Return a verbatim string with no attempt to use any data context.
        """
        return self._content
