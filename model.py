from datetime import datetime
from typing import Optional

from jinja2 import Template
from pydantic import BaseModel, ConfigDict, PrivateAttr, Field
from statemachine import State


class GenieModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _state: State = PrivateAttr(default=None)


class DialogueElement(BaseModel):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

    actor: str = Field(description="the originator of the dialogue element")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="the timestamp when this dialogue element was created"
    )
    internal_repr: str = Field(description="the internal representation, before applying any rendering")
    external_repr: str = Field(description="the external representation after rendering is applied")

    @classmethod
    def from_state(cls, actor: str, internal_repr: str, state: State, data: Optional[BaseModel] = None):
        external_repr = internal_repr
        if isinstance(state.value, Template):
            template_data = data.model_dump() if data is not None else dict()
            template_data["internal_repr"] = internal_repr
            external_repr = state.value.render(template_data)

        return DialogueElement(
            actor=actor,
            internal_repr=internal_repr,
            external_repr=external_repr,
        )
