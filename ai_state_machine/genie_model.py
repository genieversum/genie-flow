from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_state_machine.genie_state_machine import GenieStateMachine
from ai_state_machine.model import DialogueElement


class GenieModel(BaseModel, ABC):
    state: str | int = Field(
        description="The current state that this model is in, represented by the value of the state"
    )
    session_id: str = Field(
        description="The ID of the session this claims belongs to."
    )
    dialogue: list[DialogueElement] = Field(
        default_factory=list,
        description="The list of dialogue elements that have been used in the dialogue so far",
    )
    running_task_id: Optional[str] = Field(
        None,
        description="the (Celery) task id of the currently running task",
    )
    actor_input: str = Field(
        "",
        description="the most recent received input from an actor",
    )

    @abstractmethod
    @property
    def state_machine_class(self) -> type[GenieStateMachine]:
        raise NotImplementedError()

    def create_state_machine(self) -> GenieStateMachine:
        return self.state_machine_class(model=self)
