import builtins
import importlib
import time
from typing import Any

from celery import Celery
from jinja2 import Template
from pydantic_redis import Model

from ai_state_machine.model import ContentType
from ai_state_machine.model import CompositeContentType
from ai_state_machine.store import STORE


app = Celery(
    "My Little AI App",
    backend="redis://localhost",
    broker="pyamqp://",
)


def get_fully_qualified_name_from_class(o: Any) -> str:
    cls = o.__class__
    module = cls.__module__
    if module == 'builtins':
        return cls.__qualname__  # we do builtins without the module path
    return module + '.' + cls.__qualname__


def get_class_from_fully_qualified_name(class_path):
    try:
        module_name, class_name = class_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
    except ValueError:
        class_name = class_path
        module = builtins

    return getattr(module, class_name)


@app.task
def trigger_ai_event(class_fqn: str, session_id: str, event_name: str, response: str):
    cls: Model = get_class_from_fully_qualified_name(class_fqn)

    model = cls.select(session_id=session_id)
    model.running_task_id = None

    state_machine = model.create_state_machine()
    state_machine.send_event(event_name, response)

    cls.insert(model)


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
