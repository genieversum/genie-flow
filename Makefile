run-worker:
	celery --app main.celery_app worker

run-api:
	uvicorn main:genie_flow.fastapi_app
