import logging
from typing import Any

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model import CompositeContentType, DialogueElement
from ai_state_machine.store import store_model, retrieve_model, get_lock_for_session

_genie_environment = GenieEnvironment()


@_genie_environment.celery.task
def trigger_ai_event(response: str, cls_fqn: str, session_id: str, event_name: str):
    with get_lock_for_session(session_id):
        model = retrieve_model(cls_fqn, session_id=session_id)
        assert isinstance(model, GenieModel)
        model.running_task_id = None

        state_machine = model.create_state_machine()
        logging.debug(f"sending {event_name} to model for session {session_id}")
        state_machine.send(event_name, response)

        store_model(model)


@_genie_environment.celery.task
def call_llm_api(
        template_name: str,
        render_data: dict[str, Any],
) -> str:
    dialogue_raw: list[dict] = getattr(render_data, "dialogue", list())
    dialogue = [DialogueElement(**x) for x in dialogue_raw]
    return _genie_environment.invoke_template(
        template_name,
        render_data,
        dialogue,
    )


@_genie_environment.celery.task
def combine_group_to_dict(
        results: list[CompositeContentType],
        keys: list[str]
) -> CompositeContentType:
    return dict(zip(keys, results))


@_genie_environment.celery.task
def chained_template(
        result_of_previous_call: CompositeContentType,
        template_name: str,
        render_data: dict[str, str],
) -> CompositeContentType:
    render_data["previous_result"] = result_of_previous_call
    return template_name, render_data
