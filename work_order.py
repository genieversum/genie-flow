import json
from typing import Optional

from loguru import logger
from statemachine import State
from pydantic import Field
from statemachine.event_data import EventData

import prompts as p
from ai_state_machine.genie_state_machine import GenieStateMachine, GenieModel


class WorkOrderRecord(GenieModel):
    work_order_summary: Optional[str] = Field(None, description="user entered summary of the work order")

    activity_type: Optional[str] = Field(None, description="type of the activity")

    leak_detail: Optional[str] = Field(None, description="detail of leak")
    paint_detail: Optional[str] = Field(None, description="detail of paint")


class WorkOrderStateMachine(GenieStateMachine):
    user_entering_work_order = State(initial=True, value=p.OPENING)
    ai_extracting_activity_type = State(value=p.AI_EXTRACT_ACTIVITY_TYPE)
    user_verifying_activity_type = State(value=p.USER_VERIFIES_ACTIVITY_TYPE)
    ai_extracting_activity_type_verification = State(value=p.AI_EXTRACT_ACTIVITY_TYPE_VERIFICATION)
    user_entering_activity_type = State(value=p.USER_ENTERS_ACTIVITY_TYPE)

    ai_extracts_leak_details = State(value=p.AI_EXTRACTS_DETAILS)
    ai_extracts_paint_details = State(value=p.AI_EXTRACTS_DETAILS)

    user_verifies_extracted_details = State(value=p.USER_VERIFIES_DETAILS)
    ai_extracts_details_verification = State(value=p.AI_EXTRACTS_DETAILS_VERIFICATION)
    user_enters_additional_details = State(value=p.USER_ENTERS_ADDITIONAL_DETAILS)
    ai_extracts_additional_details = State(value=p.AI_EXTRACTS_ADDITIONAL_DETAILS)
    details_verified: bool = False

    ai_stores_details = State(final=True)

    user_input = (
            user_entering_work_order.to(ai_extracting_activity_type, cond="is_valid_response") |
            user_entering_work_order.to(user_entering_work_order, unless="is_valid_response") |
            user_verifying_activity_type.to(ai_extracting_activity_type_verification) |
            user_entering_activity_type.to(ai_extracting_activity_type) |
            user_verifies_extracted_details.to(ai_extracts_details_verification) |
            user_enters_additional_details.to(ai_extracts_additional_details)
    )

    ai_extraction = (
        ai_extracting_activity_type.to(user_verifying_activity_type) |
        ai_extracting_activity_type_verification.to(
            ai_extracts_leak_details,
            validators="is_valid_response",
            cond="is_activity_type_leak",
        ) |
        ai_extracting_activity_type_verification.to(
            ai_extracts_paint_details,
            validators="is_valid_response",
            cond="is_activity_type_paint",
        ) |
        ai_extracting_activity_type_verification.to(
            user_entering_activity_type,
            validators="is_valid_response",
            unless=["is_activity_type_leak", "is_activity_type_paint"],
        ) |
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
                f"""{'=' * 5}
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
