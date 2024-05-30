from abc import ABC
from typing import Any, Optional

from celery import Task

from ai_state_machine.model import DialogueElement
from ai_state_machine.environment import GenieEnvironment


class GenieTemplate(ABC):
    """
    The abstract template for rendering content from a data model or dictionary. This is the
    abstraction around any form of template that can be rendered.

    This is an abstract base class which should be overridden for specific templates..
    """

    def __init__(self, template_path: str, genie_environment: GenieEnvironment):
        self.template_path = template_path
        self.genie_environment = genie_environment

    def render(self, data_context: dict[str, Any]) -> str:
        """
        Render this template with the given data context into a string.

        :param data_context: a dict or GenieModel that is used as context for the rendering.
        :return: the rendered string.
        """
        return self.genie_environment.render_template(self.template_path, data_context)

    def invoke(
            self,
            data_context: dict[str, Any],
            dialogue: Optional[list[DialogueElement]] = None,
    ) -> str:
        """
        Render this template with the given data context and invoke the underlying invoker
        with the optional dialogue. Return the output of the invocation.
        :param data_context: a dict that is used as context for the rendering.
        :param dialogue: an optional list of dialogue elements that can be used in the invocation.
        :return: the output of the invocation.
        """
        return self.genie_environment.invoke_template(
            self.template_path,
            data_context,
            dialogue
        )


TemplateDictionary = dict[str, "CompositeTemplate"]
TemplateList = list["CompositeTemplate"]
CompositeTemplate = GenieTemplate | TemplateDictionary | TemplateList | Task
