import enum
import json
from datetime import datetime
from enum import Enum
from typing import Optional, Callable

from pydantic import Field, field_validator, BaseModel
from statemachine.event_data import EventData


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
    event: Optional[str] = Field(
        default=None,
        description="The event that triggered this dialogue uttering"
    )
    actor_text: Optional[str] = Field(
        default=None,
        description="the text that was produced bu the actor"
    )

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


class StateType(enum.IntEnum):
    RENDERER = 0
    INVOKER = 1


class DialoguePersistence(enum.IntFlag):
    """
    `NONE`: none of the utterings during a transition are recorded

    `SOURCE_EVENT`: the event will be recorded as a source event
    `SOURCE_CONTENT`: the (raw) content, will be recorded
    `SOURCE`: either event or event and source will be recorded

    `TARGET_RAW`: the raw output sent by an invoker will be recorded
    `TARGET_RENDERED`: the rendered output, based on the template of the
    target state, will be recorded
    `TARGET`: the target raw and/or rendered will be recorded (if both, they will be
    separated by \n
    """
    NONE = 0

    SOURCE_EVENT = enum.auto()
    SOURCE_CONTENT = enum.auto()
    SOURCE = SOURCE_EVENT | SOURCE_CONTENT

    TARGET_RAW = enum.auto()
    TARGET_RENDERED = enum.auto()
    TARGET = TARGET_RAW | TARGET_RENDERED

    @staticmethod
    def _render_join(*args: Optional[str]):
        return "\n".join(arg for arg in args if arg is not None)

    def render_user(self, event_name: str, raw: Optional[str]) -> Optional[str]:
        """
        Compile content based on USER flags.

        :param event_name: the name of the event that triggered a transition
        :param raw: the raw content that was sent by the user
        :return: an optional string based on the flags
        """
        if not self & DialoguePersistence.SOURCE:
            return None

        event_name = event_name if self & DialoguePersistence.SOURCE_EVENT else None
        raw = raw if self & DialoguePersistence.SOURCE_CONTENT else None
        return self._render_join(event_name, raw)

    def render_assistant(
        self,
        event_name: str,
        raw: Optional[str],
        rendered:  str | Callable[[], str] | None
    ) -> Optional[str]:
        """
        Compile content based on ASSISTANT flags.

        :param event_name: the name of the event that triggered the transition
        :param raw: the string of raw content sent by the actor
        :param rendered: a string or callable for the rendered content from the actor
        :return: an optional string based on flags and parameters
        """
        if not self & DialoguePersistence.TARGET:
            return None

        event_name = event_name if self & DialoguePersistence.TARGET_EVENT else None
        raw = raw if self & DialoguePersistence.TARGET_RAW else None
        if self & DialoguePersistence.TARGET_RENDERED:
            if callable(rendered):
                rendered = rendered()
        else:
            rendered = None
        return self._render_join(event_name, raw, rendered)
