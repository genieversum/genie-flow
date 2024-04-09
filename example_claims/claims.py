import json
import logging
from json import JSONDecodeError
from typing import Optional, Union

from jinja2 import Template
from pydantic import Field
from statemachine import State
from statemachine.event_data import EventData

from ai_state_machine.genie_state_machine import GenieStateMachine, GenieModel
import example_claims.prompts as p


class ClaimsModel(GenieModel):
    @property
    def state_machine_class(self) -> type[GenieStateMachine]:
        return ClaimsMachine

    user_role: Optional[str] = Field(
        None,
        description="the business role of the user",
    )
    product_description: Optional[str] = Field(
        None,
        description="free form description of the product",
    )
    target_persona: Optional[str] = Field(
        None,
        description="a bio of the persona we want to target",
    )
    further_info: Optional[str] = Field(
        None,
        description="any further relevant information",
    )

    step_back_research: Optional[str] = Field(
        None,
        description="output of the step-back research",
    )


class ClaimsMachine(GenieStateMachine):

    def __init__(self, model: ClaimsModel, new_session: bool = False):
        if not isinstance(model, ClaimsModel):
            raise TypeError("The type of model should be ClaimsModel, not {}".format(type(model)))

        super(ClaimsMachine, self).__init__(
            model=model,
            new_session=new_session,
        )

    # STATES
    # gathering information from the user
    user_entering_role = State(initial=True, value=1)
    ai_extracts_information = State(value=2)
    user_enters_additional_information = State(value=3)

    # generating claims
    user_views_start_of_generation = State(value=10)
    ai_extracts_categories = State(value=11)
    user_views_categories = State(value=12)
    ai_conducts_research = State(value=13)
    user_views_research = State(value=14)
    ai_generates_claims = State(value=15)
    user_views_claims = State(value=16, final=True)

    # TEMPLATES
    templates: dict[str, Union[str, Template, dict[str]]] = dict(
        user_entering_role=p.USER_ENTERING_ROLE_PROMPT,
        ai_extracts_information=p.AI_EXTRACTING_INFO_PROMPT,
        user_enters_additional_information=Template("{{actor_input}}"),
        user_views_start_of_generation=p.USER_VIEUWING_START_OF_GENERATION,
        ai_extracts_categories=p.AI_EXTRACTING_CATEGORIES_PROMPT,
        user_views_categories=p.USER_VIEWING_CATEGORIES_PROMPT,
        ai_conducts_research=p.AI_CONDUCTING_RESEARCH_PROMPT,
        user_views_research=p.USER_VIEWING_BACKGROUND_RESEARCH_PROMPT,
        ai_generates_claims=p.AI_GENERATES_CLAIMS_PROMPT,
        user_views_claims=p.USER_VIEWS_GENERATED_CLAIMS,
    )

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
    def have_all_info(self, event_data: EventData):
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
