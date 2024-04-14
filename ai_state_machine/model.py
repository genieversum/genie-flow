import collections
import json
import uuid
from abc import abstractmethod, ABC
from datetime import datetime
from enum import Enum
from typing import overload, Iterable, MutableSequence, Union, Optional

from celery import Task
from jinja2 import Template
from pydantic import BaseModel, Field
from pydantic_redis import Model

from ai_state_machine.store import STORE

TemplateType = str | Template
ExecutableTemplateType = TemplateType | Task
CompositeTemplateType = Union[
    ExecutableTemplateType,
    list[ExecutableTemplateType],
    dict[str, ExecutableTemplateType],
]

ContentType = str
CompositeContentType = ContentType | list[ContentType] | dict[str, ContentType]


class DialogueElement(Model):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """
    _primary_key_field: str = "id"
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)

    actor: str = Field(description="the originator of the dialogue element")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="the timestamp when this dialogue element was created"
    )
    actor_text: str = Field(
        description="the text that was produced bu the actor"
    )


STORE.register_model(DialogueElement)


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
                    f"[{e.actor.upper()}]: {e.actor_text}"
                    for e in dialogue
                )
            case cls.QUESTION_ANSWER:
                # TODO figure something out for question / answer
                raise NotImplementedError()


class GenieMessage(BaseModel, ABC):
    session_id: str = Field(
        description="the Session ID associated with the interface message"
    )


class AIStatusResponse(GenieMessage):
    ready: bool = Field(
        description="indicated if the response is ready"
    )
    next_actions: list[str] = Field(
        default_factory=list,
        description="A list of actions that the user can send to evolve to the next state",
    )


class AIResponse(GenieMessage):
    response: Optional[str] = Field(
        None,
        description="The text response from the AI service"
    )
    next_actions: list[str] = Field(
        default_factory=list,
        description="A list of possible follow-up events"
    )


class EventInput(GenieMessage):
    event: str = Field(description="The name of the event that is triggered")
    event_input: str = Field(
        description="The string input that belongs to this event"
    )
