import json
import logging
from json import JSONDecodeError
from typing import Optional

from jinja2 import Template
from pydantic import Field
from statemachine import State
from statemachine.event_data import EventData

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
    product_description: Optional[str] = Field(description="free form description of the product")
    target_persona: Optional[str] = Field(description="a bio of the persona we want to target")
    further_info: Optional[str] = Field(description="any further relevant information")

    step_back_research: Optional[str] = Field(description="output of the step-back research")


class ClaimsMachine(GenieStateMachine):
    # STATES
    # gathering information from the user
    user_entering_role = State(initial=True, value=p.USER_ENTERING_ROLE_PROMPT)
    ai_extracts_information = State(value=p.AI_EXTRACTING_INFO_PROMPT)
    user_enters_additional_information = State(value=Template("{{actor_input}}"))

    # generating claims
    user_views_start_of_generation = State(value=p.USER_VIEUWING_START_OF_GENERATION)
    ai_extracts_categories = State(value=p.AI_EXTRACTING_CATEGORIES_PROMPT)
    user_views_categories = State(value=p.USER_VIEWING_CATEGORIES_PROMPT)
    ai_conducts_research = State(value=p.AI_CONDUCTING_RESEARCH_PROMPT)
    user_views_research = State(value=p.USER_VIEWING_BACKGROUND_RESEARCH_PROMPT)
    ai_generates_claims = State(value=p.AI_GENERATES_CLAIMS_PROMPT)
    user_views_claims = State(value=p.USER_VIEWS_GENERATED_CLAIMS, final=True)

    # EVENTS AND TRANSITIONS
    user_input = (
        user_entering_role.to(ai_extracts_information)
    )

    ai_extraction = (
        ai_extracts_information.to(user_views_start_of_generation, cond="have_all_info") |
        ai_extracts_information.to(user_enters_additional_information, unless="have_all_info") |
        ai_extracts_categories.to(user_views_categories) |
        ai_conducts_research.to(user_views_research) |
        ai_generates_claims.to(user_views_claims)
    )

    advance = (
        user_views_start_of_generation.to(ai_extracts_categories) |
        user_views_categories.to(ai_conducts_research) |
        user_views_research.to(ai_generates_claims)
    )

    # CONDITIONS
    def response_contains_stop(self, event_data: EventData):
        return "STOP" in event_data.args[0].upper()

    # ACTIONS
    def on_exit_ai_extracts_information(self, event_data: EventData):
        pass

    def on_exit_ai_extracts_categories(self):
        """
        We can expect that `self.actor_input` has been provided to process.
        """
        try:
            extracted_categories = json.loads(self.actor_input)
            self.model.update(extracted_categories)
        except (JSONDecodeError, KeyError) as e:
            logging.warning("Could not parse JSON from event data: %s", e)
            self.model["further_info"] = self.actor_input

    def on_exit_ai_conducts_research(self, event_data: EventData):
        self.model.step_back_research = self.actor_input
