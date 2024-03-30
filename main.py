from dataclasses import dataclass
from datetime import datetime
import json
from typing import Optional, Any

from jinja2 import Template
from loguru import logger
from statemachine import State, StateMachine
from pydantic import BaseModel, Field, ConfigDict, PrivateAttr
from statemachine.event_data import EventData

import prompts as p


class GenieModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _state: State = PrivateAttr(default=None)


class WorkOrderRecord(GenieModel):
    work_order_summary: Optional[str] = Field(None, description="user entered summary of the work order")

    activity_type: Optional[str] = Field(None, description="type of the activity")

    leak_detail: Optional[str] = Field(None, description="detail of leak")
    paint_detail: Optional[str] = Field(None, description="detail of paint")


class DialogueElement(BaseModel):
    """
    An element of a dialogue. Typically, a phrase that is output by an originator.
    """

    originator: str = Field(description="the originator of the dialogue element")
    timestamp: datetime = Field(
        default_factory=lambda : datetime.now(),
        description="the timestamp when this dialogue element was created"
    )
    internal_repr: str = Field(description="the internal representation, before applying any rendering")
    external_repr: str = Field(description="the external representation after rendering is applied")

    @classmethod
    def from_state(cls, originator: str, internal_repr: str, state: State, data: Optional[BaseModel] = None):
        external_repr = internal_repr
        if isinstance(state.value, Template):
            template_data = data.model_dump() if data is not None else dict()
            template_data["internal_repr"] = internal_repr
            external_repr = state.value.render(template_data)

        return DialogueElement(
            originator=originator,
            internal_repr=internal_repr,
            external_repr=external_repr,
        )


class GenieStateMachine(StateMachine):

    def __init__(self, model: GenieModel):
        super(GenieStateMachine, self).__init__(model=model, state_field="_state")
        self.dialogue: list[DialogueElement] = [
            DialogueElement.from_state(
                "ai",
                "",
                self.current_state,
                self.model,
            )
        ]
        self.actor_input: Optional[str] = None

    @property
    def current_response(self) -> Optional[DialogueElement]:
        return self.dialogue[-1] if len(self.dialogue) > 0 else None

    # EVENT HANDLERS
    def before_transition(self, *args, **kwargs) -> str:
        """
        Set the actors input.

        Triggered when an event is received, right but before the current state is exited.

        This method takes the events first argument and places that in `self.actor_input`. This
        makes it available for further processing.

        :param args: the list of arguments passed to this event
        :return: the first argument that was passed to this event
        """
        self.actor_input = args[0]
        return self.actor_input

    def on_user_input(self):
        """
        :param args:
        :param kwargs:
        :return:
        """
        logger.debug(f"User input event received")
        self.dialogue.append(
            DialogueElement(
                originator="human",
                internal_repr=self.actor_input,
                external_repr=self.actor_input,
            )
        )
        # self.prompt = kwargs["target"].value.render(self.model.dict())
        # call the LLM to interpret the prompt

    def on_ai_extraction(self, *args, target: State):
        """
        This hook get triggered when an "ai_extraction" event is received. It adds the AI response to the dialogue
        list as the tuple ("ai-response", ai_response).

        This hook then looks at the 'value' of the target state - which is assumed to be a Jinja template - and renders
        that template using the values of `self.model` and the template variable `ai_response` with the raw
        response that is received from the AI. The rendering of that template is then added to the dialogue
        list as the tuple ("ai", ai_chat_response).

        The state machine will then transfer into the next state which will be a "waiting for user input" state.

        :param args:
        :param target: the `State` that the state machine will move into after this event.
        :return:
        """
        logger.debug(f"AI extraction event received")
        self.dialogue.append(
            DialogueElement.from_state(
                "ai",
                internal_repr=self.actor_input,
                state=target,
                data=self.model,
            )
        )

    def on_enter_state(self, state: State, **kwargs):
        logger.info(f"== entering state {self.current_state.name} ({self.current_state.id})")


    # VALIDATIONS AND CONDITIONS
    def is_user_entry_valid(self, event_data: EventData):
        logger.debug("is user entry valid", event_data)
        return all(
            [
                event_data.args is not None,
                len(event_data.args) > 0,
                event_data.args[0] is not None,
                event_data.args[0] != "",
            ]
        )

    def is_valid_ai_response(self, event_data: EventData):
        if event_data.args is None or len(event_data.args) == 0:
            raise ValueError("Invalid response from AI")


class WorkOrderStateMachine(GenieStateMachine):
    user_enters_work_order = State(initial=True, value=p.OPENING)
    ai_extracts_activity_type = State(value=p.AI_EXTRACT_ACTIVITY_TYPE)
    user_verifies_activity_type = State(value=p.USER_VERIFIES_ACTIVITY_TYPE)
    ai_extracts_activity_type_verification = State(value=p.AI_EXTRACT_ACTIVITY_TYPE_VERIFICATION)
    user_enters_activity_type = State(value=p.USER_ENTERS_ACTIVITY_TYPE)
    activity_type_verified: bool = False

    ai_extracts_leak_details = State(value=p.AI_EXTRACTS_DETAILS)
    ai_extracts_paint_details = State(value=p.AI_EXTRACTS_DETAILS)

    user_verifies_extracted_details = State(value=p.USER_VERIFIES_DETAILS)
    ai_extracts_details_verification = State(value=p.AI_EXTRACTS_DETAILS_VERIFICATION)
    user_enters_additional_details = State(value=p.USER_ENTERS_ADDITIONAL_DETAILS)
    ai_extracts_additional_details = State(value=p.AI_EXTRACTS_ADDITIONAL_DETAILS)
    details_verified: bool = False

    ai_stores_details = State(final=True)

    user_input = (
        user_enters_work_order.to(ai_extracts_activity_type, cond="is_user_entry_valid") |
        user_enters_work_order.to(user_enters_work_order, unless="is_user_entry_valid") |
        user_verifies_activity_type.to(ai_extracts_activity_type_verification) |
        user_enters_activity_type.to(ai_extracts_activity_type) |
        user_verifies_extracted_details.to(ai_extracts_details_verification) |
        user_enters_additional_details.to(ai_extracts_additional_details)
    )

    ai_extraction = (
        ai_extracts_activity_type.to(user_verifies_activity_type) |
        ai_extracts_activity_type_verification.to(ai_extracts_leak_details, validators="is_valid_ai_response", cond="is_activity_type_leak") |
        ai_extracts_activity_type_verification.to(ai_extracts_paint_details, validators="is_valid_ai_response", cond="is_activity_type_paint") |
        ai_extracts_activity_type_verification.to(user_enters_activity_type, validators="is_valid_ai_response", unless=["is_activity_type_leak", "is_activity_type_paint"]) |
        ai_extracts_leak_details.to(user_verifies_extracted_details) |
        ai_extracts_paint_details.to(user_verifies_extracted_details) |
        ai_extracts_details_verification.to(ai_stores_details, cond="details_verified") |
        ai_extracts_details_verification.to(user_enters_additional_details, unless="details_verified") |
        ai_extracts_additional_details.to(user_verifies_extracted_details)
    )


    def _is_activity_type(self, ai_response: str, target_activity_type: str) -> bool:
        if ai_response.startswith("YES"):
            return self.model.activity_type == target_activity_type
        if ai_response.startswith("ACTIVITY_TYPE"):
            return ai_response.split(" ")[1] == target_activity_type

    def is_activity_type_leak(self, event_data: EventData):
        logger.debug("is activity_type 'leak'")
        return self._is_activity_type(event_data.args[0], "leak")

    def is_activity_type_paint(self, event_data: EventData):
        logger.debug("is activity_type 'paint'")
        return self._is_activity_type(event_data.args[0], "paint")

    # DATA EXTRACTORS
    def on_exit_user_enters_work_order(self, user_input):
        logger.debug("on exit user enters work order", user_input)
        self.model.work_order_summary = user_input

    def on_exit_ai_extracts_activity_type(self, ai_response: str):
        self.model.activity_type = ai_response

    def on_exit_ai_extracts_leak_details(self, ai_response: str):
        self.model.leak_detail = ai_response

    def on_exit_ai_extracts_paint_details(self, ai_response: str):
        self.model.paint_detail = ai_response

    # def current_state_output(self):
    #     self.current_state_value.


if __name__ == "__main__":
    logger.remove()
    logger.add("main.log", retention="1 hour")
    logger.info("==== STARTING ====")

    wo = WorkOrderRecord()
    sm = WorkOrderStateMachine(wo)

    # from statemachine.contrib.diagram import DotGraphMachine
    # graph = DotGraphMachine(WorkOrderStateMachine)
    # dot = graph()
    # dot.write_png("work-order-state-machine.png")

    with open("test-script.txt", "r") as script_file:
        for script_line in script_file:
            line_parts = script_line.split(":")
            actor = line_parts[0].strip().upper()
            line_content = line_parts[1].strip()
            print(
                f"""{'='*5}
State: [{sm.current_state.id}]
Record: {json.dumps(sm.model.dict(), indent=4)}
>> {sm.dialogue[-1].external_repr}
[{actor}]: {line_content}
"""
            )

            if actor == "ME":
                sm.user_input(line_content)
            elif actor == "AI":
                sm.ai_extraction(line_content)
            else:
                logger.error("found a line in the script that is not attributed to an actor")
                raise RuntimeError()
