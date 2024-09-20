import json
import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator
from pydantic_redis import Model


class DialogueElement(Model):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

    _primary_key_field: str = "id"
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)

    actor: str = Field(
        description="the originator of the dialogue element",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="the timestamp when this dialogue element was created",
    )
    actor_text: str = Field(description="the text that was produced bu the actor")

    @field_validator("actor")
    @classmethod
    def known_actors(cls, value: str) -> str:
        if value not in ["system", "assistant", "user"]:
            raise ValueError(f"unknown actor: '{value}'")
        return value


class DialogueFormat(Enum):
    PYTHON_REPR = "python_repr"
    JSON = "json"
    CHAT = "chat"
    QUESTION_ANSWER = "question_answer"

    @classmethod
    def format(
        cls, dialogue: list[DialogueElement], target_format: "DialogueFormat"
    ) -> str:
        if len(dialogue) == 0:
            return ""

        match target_format:
            case cls.PYTHON_REPR:
                return repr(dialogue)
            case cls.JSON:
                return json.dumps([e.model_dump() for e in dialogue])
            case cls.CHAT:
                return "\n\n".join(
                    f"[{e.actor.upper()}]: {e.actor_text}" for e in dialogue
                )
            case cls.QUESTION_ANSWER:
                # TODO figure something out for question / answer
                raise NotImplementedError()
