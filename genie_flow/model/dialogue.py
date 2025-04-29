import json
from datetime import datetime
from enum import Enum

from pydantic import Field, field_validator, BaseModel


class DialogueElement(BaseModel):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

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

    def as_chat(self) -> str:
        return f"[{self.actor.upper()}]: {self.actor_text}\n"

    def as_yaml(self) -> str:
        lines = "\n".join(f"    {line}" for line in self.actor_text.splitlines())
        return f"""- role: {self.actor}
  content: >
{lines}
"""


class DialogueFormat(Enum):
    PYTHON_REPR = "python_repr"
    JSON = "json"
    YAML = "yaml"
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
                return json.dumps([d.model_dump() for d in dialogue])
            case cls.YAML:
                return "\n".join(d.as_yaml() for d in dialogue)
            case cls.CHAT:
                return "\n".join(d.as_chat() for d in dialogue)
            case cls.QUESTION_ANSWER:
                # TODO figure something out for question / answer
                raise NotImplementedError()
