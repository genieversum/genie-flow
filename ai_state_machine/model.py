import collections
import json
from abc import abstractmethod
from datetime import datetime
from enum import Enum
from typing import overload, Iterable, MutableSequence, Union

from celery import Task
from jinja2 import Template
from pydantic import BaseModel, Field


TemplateType = str | Template
ExecutableTemplateType = TemplateType | Task
CompositeTemplateType = Union[
    ExecutableTemplateType,
    list[ExecutableTemplateType],
    dict[str, ExecutableTemplateType],
]

ContentType = str
CompositeContentType = ContentType | list[ContentType] | dict[str, ContentType]


class DialogueElement(BaseModel):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

    actor: str = Field(description="the originator of the dialogue element")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="the timestamp when this dialogue element was created"
    )
    actor_text: str = Field(
        description="the text that was produced bu the actor"
    )


class DialogueFormat(Enum):
    PYTHON_REPR = "python_repr"
    JSON = "json"
    CHAT = "chat"
    QUESTION_ANSWER = "question_answer"

    @classmethod
    def format(cls, dialogue: list[DialogueElement], target_format: "DialogueFormat") -> str:
        if len(dialogue) == 0:
            return ""

        match target_format:
            case cls.PYTHON_REPR:
                return repr(dialogue)
            case cls.JSON:
                return json.dumps([e.model_dump() for e in dialogue])
            case cls.CHAT:
                "\n\n".join(
                    f"[{e.actor.upper()}]: {e.external_repr}"
                    for e in dialogue
                )
            case cls.QUESTION_ANSWER:
                # TODO figure something out for question / answer
                raise NotImplementedError()
