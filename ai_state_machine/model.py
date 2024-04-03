import collections
from abc import abstractmethod
from datetime import datetime
from typing import Optional, overload, Iterable, MutableSequence

from jinja2 import Template
from pydantic import BaseModel, ConfigDict, PrivateAttr, Field
from statemachine import State


class DialogueElement(BaseModel):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

    actor: str = Field(description="the originator of the dialogue element")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="the timestamp when this dialogue element was created"
    )
    internal_repr: str = Field(
        description="the internal representation, before applying any rendering"
    )
    external_repr: str = Field(
        description="the external representation after rendering is applied"
    )


class Dialogue(collections.abc.MutableSequence):
    _sequence: MutableSequence[DialogueElement] = []

    def insert(self, index, value):
        self._sequence.insert(index, value)

    @overload
    @abstractmethod
    def __getitem__(self, index: int) -> DialogueElement: ...

    @overload
    @abstractmethod
    def __getitem__(self, index: slice) -> MutableSequence[DialogueElement]: ...

    def __getitem__(self, index):
        return self._sequence.__getitem__(index)

    @overload
    @abstractmethod
    def __setitem__(self, index: int, value: DialogueElement) -> None: ...

    @overload
    @abstractmethod
    def __setitem__(self, index: slice, value: Iterable[DialogueElement]) -> None: ...

    def __setitem__(self, index, value):
        self._sequence.__setitem__(index, value)

    @overload
    @abstractmethod
    def __delitem__(self, index: int) -> None: ...

    @overload
    @abstractmethod
    def __delitem__(self, index: slice) -> None: ...

    def __delitem__(self, index):
        self._sequence.__delitem__(index)

    def __len__(self):
        return len(self._sequence)

    def __repr__(self):
        return self._sequence.__repr__()

    def __str__(self):
        """
        Returns a string representation of the Dialogue, where the actor is printed
        between square brackets, followed by a colon. Consecutive DialogueElements
        are separated by five equal-signs and new-lines.

        Of the DialogElements, the external_repr is used.
        """
        separator = f"\n\n{'='*5}\n"
        return separator.join(
            [
                f"[{item.actor}]: {item.external_repr}"
                for item in self._sequence
            ]
        )


class GenieModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _state: State = PrivateAttr(default=None)
