run-worker:
	celery --app main.genie_flow.celery_app worker

run-api:
	uvicorn main:genie_environment.fastapi_app

