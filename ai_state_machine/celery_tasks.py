import logging
from typing import Any

from celery import Celery

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model import CompositeContentType, DialogueElement
from ai_state_machine.session import SessionLockManager
from ai_state_machine.store import StoreManager


def add_trigger_ai_event_task(
        app: Celery,
        session_lock_manager: SessionLockManager,
        store_manager: StoreManager,
):
    @app.task(name="genie_flow.trigger_ai_event")
    def trigger_ai_event(self, response: str, cls_fqn: str, session_id: str, event_name: str):
        with session_lock_manager.get_lock_for_session(session_id):
            model = store_manager.retrieve_model(cls_fqn, session_id=session_id)
            assert isinstance(model, GenieModel)
            model.running_task_id = None

            state_machine = model.create_state_machine()
            logging.debug(f"sending {event_name} to model for session {session_id}")
            state_machine.send(event_name, response)

            self.store_manager.store_model(model)

    return trigger_ai_event


def add_invoke_task(
    app: Celery,
    genie_environment: GenieEnvironment
):

    @app.task(name="genie_flow.invoke_ai_event")
    def invoke_ai_event(template_name: str, render_data: dict[str, Any]) -> str:
        dialogue_raw: list[dict] = getattr(render_data, "dialogue", list())
        dialogue = [DialogueElement(**x) for x in dialogue_raw]
        return genie_environment.invoke_template(
            template_name,
            render_data,
            dialogue,
        )

    return invoke_ai_event


def add_combine_group_to_dict(app):

    @app.task(name="genie_flow.combine_group_to_dict")
    def combine_group_to_dict(
            results: list[CompositeContentType],
            keys: list[str]
    ) -> CompositeContentType:
        return dict(zip(keys, results))

    return combine_group_to_dict


def add_chained_template(app):

    @app.task(name="genie_flow.chained_template")
    def chained_template(
            result_of_previous_call: CompositeContentType,
            template_name: str,
            render_data: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        render_data["previous_result"] = result_of_previous_call
        return template_name, render_data

    return chained_template
