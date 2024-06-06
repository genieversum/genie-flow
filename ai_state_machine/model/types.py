from celery import Task

from ai_state_machine.genie_model import GenieModel

ModelKeyRegistryType = dict[str, type[GenieModel]]
CompositeTemplateType = (
    str | Task | list["CompositeTemplateType"] | dict[str, "CompositeTemplateType"]
)
CompositeContentType = (
    str | list["CompositeContentType"] | dict[str, "CompositeContentType"]
)
