from typing import NamedTuple, TypeAlias

from celery import Task


class MapTaskTemplate(NamedTuple):
    template_name: str
    list_attribute: str
    map_index_field: str = "map_index"
    map_value_field: str = "map_value"


class NamedQueueTaskTemplate(NamedTuple):
    template: "CompositeTemplateType"
    queue_name: str


CompositeTemplateType: TypeAlias = (
    str
    | Task
    | list["CompositeTemplateType"]
    | dict[str, "CompositeTemplateType"]
    | MapTaskTemplate
    | NamedQueueTaskTemplate
)
CompositeContentType = (
    str | list["CompositeContentType"] | dict[str, "CompositeContentType"]
)
