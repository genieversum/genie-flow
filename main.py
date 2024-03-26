from typing import Optional

from loguru import logger
from statemachine import State, StateMachine
from pydantic import BaseModel, Field
from statemachine.event_data import EventData

import prompts as p
import ai_simulator as ai


class WorkOrderRecord(BaseModel):
    work_order_summary: Optional[str] = Field(None, description="user entered summary of the work order")

    activity_type: Optional[str] = Field(None, description="type of the activity")
    activity_verified: bool = Field(False, description="user verified activity type")

    leak_detail: Optional[str] = Field(None, description="detail of leak")
    paint_detail: Optional[str] = Field(None, description="detail of paint")


class WorkOrderStateMachine(StateMachine):
    user_enters_work_order = State(initial=True, value=p.OPENING)
    ai_extracts_activity_type = State(value=p.AI_EXTRACT_ACTIVITY_TYPE)
    user_verifies_activity_type = State(value=p.USER_VERIFIES_ACTIVITY_TYPE)
    ai_extracts_activity_type_verification = State(value=p.AU_EXTRACT_ACTIVITY_TYPE_VERIFICATION)

    user_enters_activity_type = State()
    activity_type_verified: bool = False

    ai_extracts_leak_details = State()
    ai_extracts_paint_details = State()

    user_verifies_extracted_details = State()
    ai_extracts_details_verification = State()
    user_enters_additional_details = State()
    ai_extracts_additional_details = State()
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
        ai_extracts_activity_type_verification.to(ai_extracts_leak_details, cond=["activity_type_verified", "activity_type_leak"]) |
        ai_extracts_activity_type_verification.to(ai_extracts_paint_details, cond=["activity_type_verified", "activity_type_paint"]) |
        ai_extracts_activity_type_verification.to(user_enters_activity_type, unless="activity_type_verified") |
        ai_extracts_leak_details.to(user_verifies_extracted_details) |
        ai_extracts_paint_details.to(user_verifies_extracted_details) |
        ai_extracts_details_verification.to(ai_stores_details, cond="details_verified") |
        ai_extracts_details_verification.to(user_enters_additional_details, unless="details_verified") |
        ai_extracts_additional_details.to(user_verifies_extracted_details)
    )

    def __init__(self, word_order_record: WorkOrderRecord):
        super(WorkOrderStateMachine, self).__init__()
        self.record = word_order_record
        self.dialogue: list[tuple[str, str]] = [("ai", self.current_state_value)]

    def activity_type_leak(self):
        return self.record.activity_type == "leak"

    def activity_type_paint(self):
        return self.record.activity_type == "paint"

    def is_user_entry_valid(self, event_data: EventData):
        logger.info("user entry valid", event_data)
        return event_data.args is not None and len(event_data.args) > 0 and event_data.args[0] != ""

    # event handlers
    def on_user_input(self, *args, **kwargs):
        logger.info(f"User input received: {args} and {kwargs}")
        self.dialogue.append(("user", args[0]))
        self.prompt = kwargs["target"].value.render(self.record.dict())

    def on_ai_extraction(self, *args):
        logger.info(f"AI extraction received: {args}")
        self.dialogue.append(("ai", args[0]))

    #
    def on_exit_user_enters_work_order(self, user_input):
        logger.info("on exit user enters work order", user_input)
        self.record.work_order_summary = user_input

    def on_enter_ai_extracts_activity_type(self, ai_response: str):
        self.record.activity_type = ai_response
        return self.record.activity_type

    # def on_enter_ai_extracts_activity_type_verification(self, user_input: str):
    #
    #         self.activity_type_verified = True
    #     return self.activity_type_verified


if __name__ == "__main__":
    wo = WorkOrderRecord()
    sm = WorkOrderStateMachine(wo)

    sm.user_input("I repaired a leak")
    logger.info(sm)

    sm.ai_extraction(ai.extract_activity_type(sm.dialogue[-1][1]))
    logger.info(sm)

    sm.user_input("yes")
    logger.info(sm)

    sm.ai_extraction(ai.extract_activity_type_verification(sm.dialogue[-1][1]))
    logger.info(sm)
