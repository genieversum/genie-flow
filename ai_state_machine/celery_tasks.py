import time

from celery import Celery

from ai_state_machine.store import retrieve_state_model, store_state_model


app = Celery(
    "My Little AI App",
    backend="redis://localhost",
    broker="pyamqp://",
)


@app.task
def trigger_ai_event(session_id: str, event_name: str, response: str):
    model = retrieve_state_model(session_id)
    state_machine = model.create_state_machine()
    state_machine.send_event(event_name, response)
    store_state_model(model)


@app.task
def call_llm_api(prompt: str) -> str:
    time.sleep(3)
    return prompt
