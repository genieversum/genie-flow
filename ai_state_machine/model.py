import collections
import json
from abc import abstractmethod
from datetime import datetime
from enum import Enum
from typing import overload, Iterable, MutableSequence

from pydantic import BaseModel, Field


class DialogueElement(BaseModel):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

    actor: str = Field(description="the originator of the dialogue element")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="the timestamp when this dialogue element was created"
    )
    internal_repr: str = Field(
        description="the internal representation, before applying any rendering"
    )
    external_repr: str = Field(
        description="the external representation after rendering is applied"
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
