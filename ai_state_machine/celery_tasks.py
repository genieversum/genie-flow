import time

from celery import Celery

from ai_state_machine.model import CompositeContentType
from ai_state_machine.store import store_model, retrieve_model, STORE, get_lock_for_session


app = Celery(
    "My Little AI App",
    backend="redis://localhost",
    broker="pyamqp://",
)


@app.task
def trigger_ai_event(response: str, cls_fqn: str, session_id: str, event_name: str):
    lock = get_lock_for_session(session_id)
    with lock.acquire():
        model = retrieve_model(cls_fqn, session_id=session_id)
        model.running_task_id = None

        state_machine = model.create_state_machine()
        state_machine.send(event_name, response)

        store_model(model)


@app.task
def call_llm_api(prompt: str) -> str:
    time.sleep(3)  # fake make the actual call

    return prompt


@app.task
def combine_group_to_dict(results: list[CompositeContentType], keys: list[str]) -> CompositeContentType:
    return {
        keys[i]: results[i]
        for i in range(len(keys))
    }
