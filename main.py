from ai_state_machine.containers import init_genie_flow
from example_claims.claims import ClaimsModel
from example_qa.q_and_a_trans import QandATransModel

genie_flow_container = init_genie_flow("config.yaml")
genie_environment = genie_flow_container.genie_environment()

genie_environment.register_model("claims_genie", ClaimsModel)
genie_environment.register_template_directory("claims", "example_claims/templates")

genie_environment.register_model("qa_trans", QandATransModel)
genie_environment.register_template_directory("q_and_a", "example_qa/templates")
