from typing import Optional

from jinja2 import Template
from pydantic import Field
from statemachine import State

from ai_state_machine.model import GenieModel
from ai_state_machine.genie_state_machine import GenieStateMachine
import example_claims.prompts as p


class ClaimsModel(GenieModel):
    session_id: str = Field(
        description="The ID of the session this claims belongs to."
    )
    user_role: Optional[str] = Field(
        None,
        description="the business role of the user",
    )


class ClaimsMachine(GenieStateMachine):
    user_entering_role = State(initial=True, value=p.USER_ENTERING_PROMPT)
    ai_extracts_information = State(value=p.AI_EXTRACTING_INFO_PROMPT)
    user_enters_additional_information = State(
        value=Template("{{response}}")
    )

    ai_extracts_categories = State(value=Template(
            """
You are an insightful AI that understands how to find the relevant parts of information from a question-answer dialogue
Your task is to categorise dictionary tuple in 'chat_history' into the four categories outlined below.
Let's do it step by step.

'chat_history' is a dictionary of dictionaries, where each sub-dictionary contains a question and answer.

For question-answer dictionary, categorise the answer component into the following four categories:
- "user_role" =  The role of the user (normally found in the first dictionary)
- "product_description" = A description of the product they want to market that might detail ingredients, benefits and/or sensory experience
- "target_persona" = A description of the target persona to be advertised
- "further_info" = Any further information

You must generate a json object where the keys are each of the categories outlined above, and the values are the parts you have identified
that belong in the respective category. If there are no parts identified, you can write 'N/A'.

chat_history
---
{{dialogue}}

---
Please ensure that your response is a json object of categorised information from 'chat_history'.
Here is the json schema that you must adhere to:
{
    user_role: < STR: The role of the user (normally found in the first array) >,
    product_description: < STR: A description of the product they want to market that might detail ingredients, benefits and/or sensory experience >,
    target_persona: < STR: A description of the target persona to be advertised >,
    further_info: < STR: Any further information >,
}
            """
        )
    )

    # EVENTS AND TRANSITIONS
    user_input = (
        user_entering_role.to(ai_extracts_information)
    )

    ai_extraction = (
        ai_extracts_information.to(
            ai_extracts_categories,
            unless="response_contains_stop",
        ) |
        ai_extracts_information.to(
            user_enters_additional_information,
            cond="needs_more_information",
        )
    )

    # CONDITIONS
    def response_contains_stop(self, event):