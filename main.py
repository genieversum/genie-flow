from typing import Optional

from statemachine import State, StateMachine
from pydantic import BaseModel, Field


class WorkOrderRecord(BaseModel):
    activity_type: Optional[str] = Field(None, description="type of the activity")
    activity_verified: bool = Field(False, description="user verified activity type")

    leak_detail: Optional[str] = Field(None, description="detail of leak""")
    paint_detail: Optional[str] = Field(None, description="detail of paint")


class WorkOrderStateMachine(StateMachine):
    user_enters_work_order = State(
        initial=True,
        value="Welcome to this interview. Please enter your work order summary"
    )
    ai_extracts_activity_type = State(
        value="""
        You are an interviewer and want to extract the activity type 
        from a work order summary.
        
        The summary is given below.
        
        Possible activity types are
        - fixed a leak
        - painted the meter
        - other
        
        Please interpret the following work order and match the most appropriate
        activity type.
        
        Work Order Summary
        ---
        {work_order_summary}  
        """
    )
    user_verifies_activity_type = State(
        value="""
        I have identified the activity type to be '{activity_type}'. Is this correct?
        If this is not correct, please let me know and also what the correct 
        activity type should be. 
        """
    )
    ai_extracts_activity_type_verification = State(
        value="""
        Extract from the following user comment if they agree with my previous statement
        or not. If they didn't agree with my previous statement, they should provide
        an activity type. Possible activity types are
        - fixed a leak
        - painted the meter.
        
        If the user agrees with my previous statement, just state YES.
        If they user did not agree with my previous statement, just respond with
        the activity type they provided.
        If they did not provide an alternative activity type, respond with NOT PROVIDED.
        
        User Response
        ___
        {user_response}
        """
    )
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
        user_enters_work_order.to(ai_extracts_activity_type) |
        user_verifies_activity_type.to(ai_extracts_activity_type_verification) |
        user_enters_activity_type.to(ai_extracts_activity_type) |
        user_verifies_extracted_details.to(ai_extracts_details_verification) |
        user_enters_additional_details.to(ai_extracts_additional_details)
    )

    ai_extraction = (
        ai_extracts_activity_type.to(user_verifies_activity_type) |
        ai_extracts_activity_type_verification.to(ai_extracts_leak_details, cond=["activity_type_verified", "activity_type_leak"]) |
        ai_extracts_activity_type_verification.to(ai_extracts_paint_details, cond=["activity_type_verified","activity_type_paint"]) |
        ai_extracts_activity_type_verification.to(user_enters_activity_type, unless="activity_type_verified") |
        ai_extracts_leak_details.to(user_verifies_extracted_details) |
        ai_extracts_paint_details.to(user_verifies_extracted_details) |
        ai_extracts_details_verification.to(ai_stores_details, cond="details_verified") |
        ai_extracts_details_verification.to(user_enters_additional_details, unless="details_verified") |
        ai_extracts_additional_details.to(user_verifies_extracted_details)
    )

    def __init__(self, word_order_record: WorkOrderRecord):
        self.record = word_order_record
        super(WorkOrderStateMachine, self).__init__()

    @property
    def activity_type_leak(self):
        return self.record.activity_type == "leak"

    @property
    def activity_type_paint(self):
        return self.record.activity_type == "paint"

    def on_enter_state(self, event: str, state: State):
        

    def on_enter_ai_extracts_activity_type(self, user_input: str):
        if "leak" in user_input.lower():
            self.record.activity_type = "leak"
        else:
            self.record.activity_type = "unknown"
        return self.record.activity_type

    def on_enter_ai_extracts_activity_type_verification(self, user_input: str):
        if "yes" in user_input.lower():
            self.activity_type_verified = True
        return self.activity_type_verified



