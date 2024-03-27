from typing import Optional

from jinja2 import Template
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
    ai_extracts_activity_type_verification = State(value=p.AI_EXTRACT_ACTIVITY_TYPE_VERIFICATION)
    user_enters_activity_type = State(value=p.USER_ENTERS_ACTIVITY_TYPE)
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
        ai_extracts_activity_type_verification.to(ai_extracts_leak_details, validators="is_valid_ai_response", cond="is_activity_type_leak") |
        ai_extracts_activity_type_verification.to(ai_extracts_paint_details, validators="is_valid_ai_response", cond="is_activity_type_paint") |
        ai_extracts_activity_type_verification.to(user_enters_activity_type, validators="is_valid_ai_response", unless=["is_activity_type_leak", "is_activity_type_paint"]) |
        ai_extracts_leak_details.to(user_verifies_extracted_details) |
        ai_extracts_paint_details.to(user_verifies_extracted_details) |
        ai_extracts_details_verification.to(ai_stores_details, cond="details_verified") |
        ai_extracts_details_verification.to(user_enters_additional_details, unless="details_verified") |
        ai_extracts_additional_details.to(user_verifies_extracted_details)
    )

    def __init__(self, word_order_record: WorkOrderRecord):
        self.record = word_order_record
        self.dialogue: list[tuple[str, str]] = list()  # [("ai", self.current_state_value.render())]
        super(WorkOrderStateMachine, self).__init__()

    # EVENT HANDLERS
    def on_user_input(self, *args, **kwargs):
        """
        This hook gets triggered when a "user_input" event is received. It adds the user input to the dialogue
        list (as the tuple ("user", user_input)) and triggers the AI background process.

        The state machine will then progress into the next state which will be a "waiting for AI" state.

        :param args:
        :param kwargs:
        :return:
        """
        logger.debug(f"User input received: {args} and {kwargs}")
        self.dialogue.append(("user", args[0]))
        # self.prompt = kwargs["target"].value.render(self.record.dict())
        # call the LLM to interpret the prompt

    def on_ai_extraction(self, *args, target: State):
        """
        This hook get triggered when an "ai_extraction" event is received. It adds the AI response to the dialogue
        list as the tuple ("ai-response", ai_response).

        This hook then looks at the 'value' of the target state - which is assumed to be a Jinja template - and renders
        that template using the values of `self.record` and the template variable `ai_response` with the raw
        response that is received from the AI. The rendering of that template is then added to the dialogue
        list as the tuple ("ai", ai_chat_response).

        The state machine will then transfer into the next state which will be a "waiting for user input" state.

        :param args:
        :param target: the `State` that the state machine will move into after this event.
        :return:
        """
        logger.debug(f"AI extraction received: {args}")
        ai_response = args[0]
        self.dialogue.append(("ai-response", ai_response))

        if isinstance(target.value, Template):
            template_values = self.record.dict()
            template_values["ai_response"] = ai_response
            ai_chat_response = target.value.render(template_values)
            self.dialogue.append(("ai", ai_chat_response))

    def on_enter_state(self):
        if len(self.dialogue) == 0:
            logger.info("START")
        else:
            logger.info(f">> {self.dialogue[-1][0].upper()}: {self.dialogue[-1][1]}")

    # VALIDATIONS AND CONDITIONS
    def is_user_entry_valid(self, event_data: EventData):
        logger.debug("is user entry valid", event_data)
        return event_data.args is not None and len(event_data.args) > 0 and event_data.args[0] != ""

    def is_valid_ai_response(self, event_data: EventData):
        if event_data.args is None or len(event_data.args) == 0:
            raise ValueError("Invalid response from AI")

    def _is_activity_type(self, ai_response: str, target_activity_type: str) -> bool:
        if ai_response.startswith("YES"):
            return self.record.activity_type == target_activity_type
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
        self.record.work_order_summary = user_input

    def on_exit_ai_extracts_activity_type(self, ai_response: str):
        self.record.activity_type = ai_response
        return self.record.activity_type


if __name__ == "__main__":
    from statemachine.contrib.diagram import DotGraphMachine

    wo = WorkOrderRecord()
    sm = WorkOrderStateMachine(wo)

    graph = DotGraphMachine(WorkOrderStateMachine)
    dot = graph()
    dot.write_png("work-order-state-machine.png")

    # logger.debug(f"BOT: {sm.current_state.value.render(sm.record.dict())}")
    sm.user_input("I repaired a leak")
    logger.debug(sm)

    sm.ai_extraction(ai.extract_activity_type(sm.dialogue[-1][1]))
    logger.debug(sm)

    sm.user_input("yes")
    logger.debug(sm)

    sm.ai_extraction(ai.extract_activity_type_verification(sm.dialogue[-1][1]))
    logger.debug(sm)
