import time
from typing import Any

from celery import Celery
from jinja2 import Template

from ai_state_machine.model import ContentType
from ai_state_machine.model import CompositeContentType
from ai_state_machine.store import STORE


app = Celery(
    "My Little AI App",
    backend="redis://localhost",
    broker="pyamqp://",
)


@app.task
def trigger_ai_event(session_id: str, event_name: str, response: str):
    model = retrieve_state_model(session_id)
    model.running_task_id = None

    state_machine = model.create_state_machine()
    state_machine.send_event(event_name, response)

    store_state_model(model)


@app.task
def call_llm_api(prompt: str) -> str:
    time.sleep(3)  # fake make the actual call

    return prompt


@app.task
def combine_group_to_dict(keys: list[str], results: list[ContentType]) -> CompositeContentType:
    return {
        keys[i]: results[i]
        for i in range(len(keys))
    }
