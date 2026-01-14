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

    `USER_EVENT`: the event, if sent by the user, will be recorded
    (role: user, event: 'event_name')

    `USER_CONTENT`: the content, if sent by the user, will be recorded
    (role: user, content: `actor_input`)

    `ASSISTANT_EVENT`: the event, if sent by the assistant, will be recorded
    (role: assistant, event: `event_name`)

    `ASSISTANT_RAW`: the raw output sent by an invoker will be recorded
    (role: assistant, content: "raw content")

    `ASSISTANT_RENDERED`: the rendered output, based on the template of the
    target state, will be recorded (role: assistant, content: "rendered content")

    If multiple flags are set (`_CONTENT`, `_EVENT`, `_RENDERED`) then the appropriate
    values will be persisted, separated by a `\n`.
    """
    NONE = 0
    USER_EVENT = enum.auto()
    USER_CONTENT = enum.auto()
    ASSISTANT_EVENT = enum.auto()
    ASSISTANT_RAW = enum.auto()
    ASSISTANT_RENDERED = enum.auto()

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
        if not self & (DialoguePersistence.USER_EVENT | DialoguePersistence.USER_CONTENT):
            return None

        event_name = event_name if self & DialoguePersistence.USER_EVENT else None
        raw = raw if self & DialoguePersistence.USER_CONTENT else None
        return self._render_join(event_name, raw)

    def render_assistant(
        self,
        event_name: str,
        raw: Optional[str],
        rendered:  str | Callable[[], str] | None
    ):
        """
        Compile content based on ASSISTANT flags.

        :param event_name: the name of the event that triggered the transition
        :param raw: the string of raw content sent by the actor
        :param rendered: a string or callable for the rendered content from the actor
        :return: an optional string based on flags and parameters
        """
        if not self & (
                DialoguePersistence.ASSISTANT_EVENT
                | DialoguePersistence.ASSISTANT_RAW
                | DialoguePersistence.ASSISTANT_RENDERED
        ):
            return None

        event_name = event_name if self & DialoguePersistence.ASSISTANT_EVENT else None
        raw = raw if self & DialoguePersistence.ASSISTANT_RAW else None
        if self & DialoguePersistence.ASSISTANT_RENDERED:
            if callable(rendered):
                rendered = rendered()
        else:
            rendered = None
        return self._render_join(event_name, raw, rendered)
