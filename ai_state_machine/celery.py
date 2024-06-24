import logging
from typing import Any

from celery import Celery, Task
from celery.canvas import Signature, chord, group

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.genie import GenieModel
from ai_state_machine.model.template import CompositeTemplateType, CompositeContentType
from ai_state_machine.model.dialogue import DialogueElement
from ai_state_machine.model.render_job import EnqueuedRenderJob
from ai_state_machine.session_lock import SessionLockManager
from ai_state_machine.store import StoreManager
from ai_state_machine.utils import get_class_from_fully_qualified_name


class CeleryManager:
    """
    The `CeleryManager` instance deals with compiling and enqueuing Celery tasks.
    """

    def __init__(
        self,
        celery: Celery,
        session_lock_manager: SessionLockManager,
        genie_environment: GenieEnvironment,
    ):
        self.celery_app = celery
        self.session_lock_manager = session_lock_manager
        self.genie_environment = genie_environment

        self._add_trigger_ai_event_task()
        self._add_invoke_task()
        self._add_combine_group_to_dict()
        self._add_chained_template()

    def _add_trigger_ai_event_task(self):

        @self.celery_app.task(bind=True, name='genie_flow.trigger_ai_event')
        def trigger_ai_event(
                task_instance,
                response: str,
                cls_fqn: str,
                session_id: str,
                event_name: str,
        ):
            model_class = get_class_from_fully_qualified_name(cls_fqn)
            with self.session_lock_manager.get_locked_model(session_id, model_class) as model:
                model.remove_running_task(task_instance.request.id)

                state_machine = model.get_state_machine_class()(model)
                logging.debug(f"sending {event_name} to model for session {session_id}")
                jobs = state_machine.send(event_name, response)

                task_ids = {
                    self.enqueue_task(enqueable)
                    for enqueable in jobs
                    if isinstance(enqueable, EnqueuedRenderJob)
                }
                model.add_running_tasks(task_ids)

        return trigger_ai_event

    def _add_invoke_task(self):

        @self.celery_app.task(name="genie_flow.invoke_task")
        def invoke_ai_event(render_data: dict[str, Any], template_name: str) -> str:
            dialogue_raw: list[dict] = getattr(render_data, "dialogue", list())
            dialogue = [DialogueElement(**x) for x in dialogue_raw]
            return self.genie_environment.invoke_template(
                template_name,
                render_data,
                dialogue,
            )

        return invoke_ai_event

    def _add_combine_group_to_dict(self):

        @self.celery_app.task(name="genie_flow.combine_group_to_dict")
        def combine_group_to_dict(
                results: list[CompositeContentType], keys: list[str]
        ) -> CompositeContentType:
            return dict(zip(keys, results))

        return combine_group_to_dict

    def _add_chained_template(self):

        @self.celery_app.task(name="genie_flow.chained_template")
        def chained_template(
                result_of_previous_call: CompositeContentType,
                render_data: dict[str, str],
        ) -> str | dict[str, Any]:
            render_data["previous_result"] = result_of_previous_call
            return render_data

        return chained_template

    @property
    def _invoke_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.invoke_task"]

    @property
    def _chained_template_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.chained_template"]

    @property
    def _combine_group_to_dict_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.combine_group_to_dict"]

    @property
    def _trigger_ai_event_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.trigger_ai_event"]

    def _compile_task(
            self,
            template: CompositeTemplateType,
            render_data: dict[str, Any],
    ) -> Signature:
        """
        Compiles a Celery task that follows the structure of the composite template.
        """
        if isinstance(template, str):
            return self._invoke_task.s(template)

        if isinstance(template, Task):
            return template.s(render_data)

        if isinstance(template, list):
            chained = None
            for t in template:
                if chained is None:
                    chained = self._compile_task(t, render_data)
                else:
                    chained |= self._chained_template_task.s(render_data)
                    chained |= self._compile_task(t, render_data)
            return chained

        if isinstance(template, dict):
            dict_keys = list(template.keys())  # make sure to go through keys in fixed order
            return chord(
                group(*[self._compile_task(template[k], render_data) for k in dict_keys]),
                self._combine_group_to_dict_task.s(dict_keys),
            )
        raise ValueError(
            f"cannot compile a task for a render of type '{type(template)}'"
        )

    def enqueue_task(self, enqueable: EnqueuedRenderJob) -> str:
        task = (
            self._compile_task(enqueable.template, enqueable.render_data) |
            self._trigger_ai_event_task.s(
                enqueable.model_fqn,
                enqueable.session_id,
                enqueable.event_to_send_after,
            )
        )
        return task.apply_async((enqueable.render_data,)).id
