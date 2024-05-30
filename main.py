from fastapi import FastAPI

import ai_state_machine.app
from ai_state_machine import registry
from ai_state_machine.environment import GenieEnvironment
from example_claims.claims import ClaimsModel

app = FastAPI()
app.include_router(ai_state_machine.app.router)

registry.register("claims_genie", ClaimsModel)

genie_environment = GenieEnvironment("example_claims/templates")
genie_environment.register_template_directory("claims", "example_claims/templates")
