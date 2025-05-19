from abc import ABC
from typing import Optional

from pydantic import BaseModel, Field

from genie_flow.genie import GenieModel
from genie_flow.model.user import User
from genie_flow.model.versioned import VersionedModel


class GenieMessage(BaseModel, ABC):
    """
    The base class for any message that is exchanged through the endpoints.
    """

    session_id: str = Field(
        description="the Session ID associated with the interface message"
    )


class GenieMessageWithActions(GenieMessage, ABC):
    """
    The `GenieMessage` that also carries a list of events that can be sent, given the current
    state of the model instance.
    """

    next_actions: list[str] = Field(
        default_factory=list,
        description="A list of actions that the user can send to evolve to the next state",
    )


class AIStatusResponse(GenieMessageWithActions):
    """
    The `GenieMessage` that represents the status of a background task that may run for the
    model object that belongs to a session.
    """

    ready: bool = Field(description="indicated if the response is ready")


class AIProgressResponse(BaseModel):
    total_number_of_subtasks: int = Field()
    number_of_subtasks_executed: int = Field()

    @property
    def percent_completed(self) -> float:
        if self.number_of_subtasks_executed == 0:
            return 100.0

        return 100.0 * float(self.number_of_subtasks_executed) / float(self.total_number_of_subtasks)


class AIResponse(GenieMessageWithActions):
    """
    The response that results from sending an event and the model instance's state machine
    to transition into the next state.
    """

    error: Optional[str] = Field(
        default=None,
        description="A potential error message",
    )
    response: Optional[str] = Field(
        default=None,
        description="The text response from the AI service",
    )
    progress: Optional[AIProgressResponse] = Field(
        default=None,
        description="The progress of any background process execution",
    )


class EventInput(GenieMessage):
    """
    An event with accompanying information that is sent to progress the state machine that
    belongs to a session.
    """

    event: str = Field(description="The name of the event that is triggered")
    event_input: str = Field(description="The string input that belongs to this event")


class SessionStartRequest(BaseModel):
    event: str = Field(description="The name of the event that is triggered")
    event_input: str = Field(description="The string input that belongs to this event")
    user_info: Optional[User] = Field(
        default=None,
        description="The user information that is associated with the session",
    )
