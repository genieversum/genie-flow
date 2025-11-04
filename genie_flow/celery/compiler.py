from typing import Any, Optional

import ulid
from celery import Celery, Task, chord, group
from celery.canvas import Signature

from genie_flow.model.template import CompositeTemplateType, MapTaskTemplate, NamedQueueTaskTemplate


class TaskCompiler:

    def __init__(
            self,
            celery_app: Celery,
            template: CompositeTemplateType,
            session_id: str,
            model_fqn: str,
            state_name: str,
            event_to_send_after: str,
    ):
        self.celery_app = celery_app
        self.session_id = session_id
        self.model_fqn = model_fqn
        self.event_to_send_after = event_to_send_after

        self.nr_tasks = 0
        self.task: Optional[Signature] = None

        self.invocation_id = state_name + "-" + str(ulid.new())

        self._compile_task(template)

    @property
    def _invoke_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.invoke_task"]

    @property
    def _map_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.map_task"]

    @property
    def _chained_template_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.chained_template"]

    @property
    def _combine_group_to_dict_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.combine_group_to_dict"]

    @property
    def _combine_group_to_list_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.combine_group_to_list"]

    @property
    def _trigger_ai_event_task(self) -> Task:
        return self.celery_app.tasks["genie_flow.trigger_ai_event"]

    @property
    def error_handler(self) -> Task:
        return self.celery_app.tasks["genie_flow.error_handler"]

    def _compile_task_graph(
            self,
            template: CompositeTemplateType,
    ) -> Signature:
        """
        Compiles a Celery task that follows the structure of the composite template.
        """
        if isinstance(template, str):
            self.nr_tasks += 1
            return self._invoke_task.s(
                template,
                self.session_id,
                self.model_fqn,
                self.invocation_id,
            )

        if isinstance(template, Task):
            self.nr_tasks += 1
            return template.s(
                self.session_id,
                self.model_fqn,
                self.invocation_id,
            )

        if isinstance(template, list):
            chained = None
            for t in template:
                if chained is None:
                    chained = self._compile_task_graph(t)
                else:
                    chained |= self._chained_template_task.s(
                        self.session_id,
                        self.model_fqn,
                    self.invocation_id,
                    )
                    chained |= self._compile_task_graph(t)
            self.nr_tasks += len(template) - 1
            return chained

        if isinstance(template, dict):
            dict_keys = list(template.keys())  # make sure to go through keys in fixed order
            self.nr_tasks += 1
            return chord(
                group(*[self._compile_task_graph(template[k]) for k in dict_keys]),
                self._combine_group_to_dict_task.s(
                    dict_keys,
                    self.session_id,
                    self.model_fqn,
                    self.invocation_id,
                ),
            )

        if isinstance(template, MapTaskTemplate):
            if not isinstance(template.template_name, str):
                raise TypeError("Template name of a MapTaskTemplate should be a string")

            self.nr_tasks += 1
            return self._map_task.s(
                template.list_attribute,
                template.map_index_field,
                template.map_value_field,
                template.template_name,
                self.session_id,
                self.model_fqn,
                self.invocation_id,
            )

        if isinstance(template, NamedQueueTaskTemplate):
            task = self._compile_task_graph(template.template)
            task.set(queue=template.queue_name)
            return task

        raise ValueError(
            f"cannot compile a task for a render of type '{type(template)}'"
        )

    def _compile_task(self, template):
        template_task_graph = self._compile_task_graph(template)
        self.task = (
            template_task_graph |
            self._trigger_ai_event_task.s(
                self.event_to_send_after,
                self.session_id,
                self.model_fqn,
                self.invocation_id,
            )
        )
        self.nr_tasks += 1
