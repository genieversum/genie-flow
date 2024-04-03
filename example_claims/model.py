from pydantic import BaseModel, Field


class AIResponse(BaseModel):
    session_id: str = Field(
        description="The Session ID associated with the response"
    )
    response: str = Field(
        description="The text response from the AI service"
    )
    next_actions: list[str] = Field(
        description="A list of possible follow-up events"
    )


class EventInput(BaseModel):
    session_id: str = Field(
        description="The Session ID that this event is associated with"
    )
    event: str = Field(description="The name of the event that is triggered")
    event_input: str = Field(
        description="The string input that belongs to this event"
    )
