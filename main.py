from ai_state_machine import registry
from ai_state_machine.containers import init_genie_flow
from example_claims.claims import ClaimsModel

genie_environment = init_genie_flow("config.yaml")

registry.register("claims_genie", ClaimsModel)
genie_environment.register_model(ClaimsModel)

genie_environment.register_template_directory("claims", "example_claims/templates")
