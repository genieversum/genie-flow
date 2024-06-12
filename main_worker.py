from ai_state_machine.containers import init_genie_flow
from example_claims.claims import ClaimsModel
from example_qa.q_and_a_trans import QandATransModel

genie_environment = init_genie_flow("config.yaml")

genie_environment.register_model("claims_genie", ClaimsModel)
genie_environment.register_template_directory("claims", "example_claims/templates")

genie_environment.register_model("qa_trans", QandATransModel)
genie_environment.register_template_directory("q_and_a", "example_qa/templates")

worker = genie_environment.celery_app.Worker(app=genie_environment.celery_app)
worker.start()
