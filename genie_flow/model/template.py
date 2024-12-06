from typing import NamedTuple

from celery import Task


class MapTaskTemplate(NamedTuple):
    template_name: str
    list_attribute: str
    map_index_field: str = "map_index"
    map_value_field: str = "map_value"


CompositeTemplateType = (
    str
    | Task
    | list["CompositeTemplateType"]
    | dict[str, "CompositeTemplateType"]
    | MapTaskTemplate
)
CompositeContentType = (
    str | list["CompositeContentType"] | dict[str, "CompositeContentType"]
)
