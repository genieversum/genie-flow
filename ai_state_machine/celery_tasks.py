import logging
from typing import Any

from celery import Task

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model import CompositeContentType, DialogueElement
from ai_state_machine.session import SessionLockManager
from ai_state_machine.store import StoreManager


class TriggerAIEventTask(Task):
    name = "genie_flow.trigger_ai_event"

    def __init__(
            self,
            session_lock_manager: SessionLockManager,
            store_manager: StoreManager,
    ):
        super(TriggerAIEventTask, self).__init__()
        self.session_lock_manager = session_lock_manager
        self.store_manager = store_manager

    def run(self, response: str, cls_fqn: str, session_id: str, event_name: str):
        with self.session_lock_manager.get_lock_for_session(session_id):
            model = self.store_manager.retrieve_model(cls_fqn, session_id=session_id)
            assert isinstance(model, GenieModel)
            model.running_task_id = None

            state_machine = model.create_state_machine()
            logging.debug(f"sending {event_name} to model for session {session_id}")
            state_machine.send(event_name, response)

            self.store_manager.store_model(model)


class InvokeTask(Task):
    name = "genie_flow.invoke_task"

    def __init__(self, genie_environment: GenieEnvironment):
        super(InvokeTask, self).__init__()
        self.genie_environment = genie_environment

    def run(self, template_name: str, render_data: dict[str, Any]) -> str:
        dialogue_raw: list[dict] = getattr(render_data, "dialogue", list())
        dialogue = [DialogueElement(**x) for x in dialogue_raw]
        return self.genie_environment.invoke_template(
            template_name,
            render_data,
            dialogue,
        )


class CombineGroupToDictTask(Task):
    name = "genie_flow.combine_group_to_dict"

    def run(self, results: list[CompositeContentType], keys: list[str]) -> CompositeContentType:
        return dict(zip(keys, results))


class ChainedTemplateTask(Task):
    name = "genie_flow.chained_template"

    def run(
            self,
            result_of_previous_call: CompositeContentType,
            template_name: str,
            render_data: dict[str, str],
    ) -> CompositeContentType:
        render_data["previous_result"] = result_of_previous_call
        return template_name, render_data
