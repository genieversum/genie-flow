from abc import ABC, abstractmethod
from typing import Any, Optional

from ai_state_machine.genie_model import GenieModel
from ai_state_machine.invoker import GenieInvoker


class GenieTemplate(ABC):
    """
    The abstract template for rendering content from a data model or dictionary. This is the
    abstraction around any form of template that can be rendered. The template is always
    connected to an invoker, which means the template can be invoked with a data context.
    Invoking a template means rendering it and then invoking the attached invoker with the
    output of that rendering.

    This is an abstract base class which should be overridden for specific templates..
    """

    def __init__(self, invoker: Optional[GenieInvoker] = None):
        self._invoker = invoker

    @abstractmethod
    def _render(self, data_context: dict[str, Any]) -> str:
        """
        Render this template with the given data context which is a dictionary of keywords
        with a value.

        This method should be overridden by subclasses.

        :param data_context: data context to be used to render placeholders in the template.
        :return: rendered template.
        """
        raise NotImplementedError()

    def render(self, data_context: dict[str, Any] | GenieModel) -> str:
        """
        Render this template with the given data context into a string.

        :param data_context: a dict or GenieModel that is used as context for the rendering.
        :return: the rendered string.
        """
        if isinstance(data_context, GenieModel):
            return self._render(data_context.model_dump())
        return self._render(data_context)

    def invoke(self, data_context: dict[str, Any] | GenieModel) -> str:
        rendered_template = self.render(data_context)
        return self._invoker.invoke(rendered_template)
