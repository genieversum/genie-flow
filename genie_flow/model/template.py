from celery import Task

CompositeTemplateType = (
    str | Task | list["CompositeTemplateType"] | dict[str, "CompositeTemplateType"]
)
CompositeContentType = (
    str | list["CompositeContentType"] | dict[str, "CompositeContentType"]
)
