from ai_state_machine.containers import init_genie_flow
from example_claims.claims import ClaimsModel


genie_environment = init_genie_flow("config.yaml")
genie_environment.register_model("claims_genie", ClaimsModel)
genie_environment.register_template_directory("claims", "example_claims/templates")

worker = genie_environment.celery_app.Worker(app=genie_environment.celery_app)
worker.start()
