from ai_state_machine import GenieFlow
from example_claims.claims import ClaimsModel
from example_qa.q_and_a_trans import QandATransModel

genie_flow = GenieFlow.from_yaml("config.yaml")

genie_flow.genie_environment.register_model("claims_genie", ClaimsModel)
genie_flow.genie_environment.register_template_directory(
    "claims",
    "example_claims/templates",
)

genie_flow.genie_environment.register_model("qa_trans", QandATransModel)
genie_flow.genie_environment.register_template_directory(
    "q_and_a",
    "example_qa/templates",
)

# celery_app = genie_flow.celery_app
