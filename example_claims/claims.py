import json
import logging
from json import JSONDecodeError
from typing import Optional, Union

from jinja2 import Template
from pydantic import Field
from statemachine import State
from statemachine.event_data import EventData

from ai_state_machine.genie_state_machine import GenieStateMachine
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.store import STORE


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
    step_back_research: Optional[dict[str, str]] = Field(
        None,
        description="output of the step-back research",
    )


STORE.register_model(ClaimsModel)


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
    user_entering_role = State(initial=True, value=100)
    ai_extracts_user_role = State(value=110)
    user_entering_role_retry = State(value=120)

    user_entering_initial_information = State(value=150)
    ai_extracts_information = State(value=200)
    user_enters_additional_information = State(value=210)

    # generating claims
    user_views_start_of_generation = State(value=300)
    ai_extracts_categories = State(value=310)
    user_views_categories = State(value=320)
    ai_conducts_research = State(value=330)
    ai_conducts_research_with_packaging = State(value=332)
    user_views_research = State(value=340)
    ai_generates_claims = State(value=350)
    user_views_claims = State(value=360, final=True)

    # EVENTS AND TRANSITIONS
    user_input = (
        user_entering_role.to(ai_extracts_user_role) |
        user_entering_role_retry.to(ai_extracts_user_role) |
        user_entering_initial_information.to(ai_extracts_information) |
        user_enters_additional_information.to(ai_extracts_information)
    )

    ai_extraction = (
        ai_extracts_user_role.to(user_entering_initial_information, cond="user_role_defined") |
        ai_extracts_user_role.to(user_entering_role_retry, unless="user_role_defined") |

        ai_extracts_information.to(user_views_start_of_generation, cond="have_all_info") |
        ai_extracts_information.to(user_enters_additional_information, unless="have_all_info") |
        ai_extracts_categories.to(user_views_categories) |
        ai_conducts_research.to(user_views_research) |
        ai_conducts_research_with_packaging.to(user_views_research) |
        ai_generates_claims.to(user_views_claims)
    )

    advance = (
        user_views_start_of_generation.to(ai_extracts_categories) |
        user_views_categories.to(
            ai_conducts_research,
            unless="user_is_packaging_specialist",
        ) |
        user_views_categories.to(
            ai_conducts_research_with_packaging,
            cond="user_is_packaging_specialist",
        ) |
        user_views_research.to(ai_generates_claims)
    )

    # TEMPLATES
    templates: dict[str, Union[str, Template, dict[str]]] = dict(
        user_entering_role="claims/instruction_opening.jinja2",
        ai_extracts_user_role="claims/prompt_extract_user_role.jinja2",
        user_entering_role_retry="claims/feedback_cannot_extract_role.jinja2",
        user_entering_initial_information="claims/instruction_initial_information.jinja2",
        ai_extracts_information="claims/prompt_extract_information.jinja2",
        user_enters_additional_information="claims/feedback_need_more_information.jinja2",
        user_views_start_of_generation="claims/feedback_start_generation.jinja2",
        ai_extracts_categories=dict(
            user_role="claims/prompt_extract_categories_user_role.jinja2",
            product_description="claims/prompt_extract_categories_product_description.jinja2",
            target_persona="claims/prompt_extract_categories_target_persona.jinja2",
            further_info="claims/prompt_extract_categories_further_information.jinja2",
        ),
        user_views_categories="claims/feedback_view_categories.jinja2",
        ai_conducts_research=dict(
            ingredients="claims/prompt_research_ingredients.jinja2",
            benefits="claims/prompt_research_benefits.jinja2",
            sensory="claims/prompt_research_sensory.jinja2",
            marketing="claims/prompt_research_marketing.jinja2",
        ),
        ai_conducts_research_with_packaging=dict(
            ingredients="claims/prompt_research_ingredients.jinja2",
            benefits="claims/prompt_research_benefits.jinja2",
            sensory="claims/prompt_research_sensory.jinja2",
            marketing="claims/prompt_research_marketing.jinja2",
            packaging="claims/prompt_research_packaging.jinja2",
        ),
        user_views_research="claims/feedback_view_research.jinja2",
        ai_generates_claims="claims/prompt_generate_claims.jinja2",
        user_views_claims="claims/feedback_view_claims.jinja2",
    )

    # CONDITIONS
    def user_role_defined(self, event_data: EventData):
        if len(event_data.args) == 0:
            return False

        ai_output = event_data.args[0]
        return (ai_output is not None) and ("undetermined" not in ai_output)

    def have_all_info(self, event_data: EventData):
        if len(event_data.args) == 0:
            return False

        return "STOP" in event_data.args[0]

    def user_is_packaging_specialist(self):
        return self.model.user_role == "packaging specialist"

    # ACTIONS
    def on_exit_ai_extracts_user_role(self, event_data: EventData):
        self.model.user_role = self.model.actor_input

    def on_exit_ai_extracts_information(self, event_data: EventData):
        pass

    def on_exit_ai_extracts_categories(self):
        """
        We can expect that `self.actor_input` has been provided to process.
        """
        try:
            for k, v in self.model.actor_input.items():
                setattr(self.model, k, v)
        except (JSONDecodeError, KeyError) as e:
            logging.warning("Could not parse JSON from event data: %s", e)
            self.model.further_info = self.model.actor_input
        except TypeError as e:
            logging.warning("Could not update the model from event data: %s", e)
            self.model.further_info = self.model.actor_input

    def on_exit_ai_conducts_research(self, event_data: EventData):
        self.model.step_back_research = self.model.actor_input

    def on_exit_ai_conducts_research_with_packaging(self, event_data: EventData):
        self.model.step_back_research = self.model.actor_input
