from typing import Optional

from pydantic import BaseModel, Field

from ai_state_machine.model import GenieMessage


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
