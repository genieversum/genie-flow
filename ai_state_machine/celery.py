import logging
from typing import Any, Optional

from celery import Celery, Task
from celery.canvas import Signature, chord, group
from celery.result import AsyncResult
from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from ai_state_machine.environment import GenieEnvironment
from ai_state_machine.genie import GenieModel, GenieStateMachine
from ai_state_machine.model.template import CompositeTemplateType, CompositeContentType
from ai_state_machine.model.dialogue import DialogueElement
from ai_state_machine.session_lock import SessionLockManager
from ai_state_machine.utils import get_class_from_fully_qualified_name, \
    get_fully_qualified_name_from_class


class _TaskCompiler:

    def __init__(
            self,
            celery_app: Celery,
            template: CompositeTemplateType,
            session_id: str,
            render_data: dict[str, Any],
            model_fqn: str,
            event_to_send_after: str,
    ):
        self.celery_app = celery_app
        self.session_id = session_id
        self.model_fqn = model_fqn
        self.event_to_send_after = event_to_send_after

        self.nr_tasks = 0
        self.task: Optional[Signature] = None
        self._compile_task(template, render_data)

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

    def _compile_task_graph(
            self,
            template: CompositeTemplateType,
            render_data: dict[str, Any],
    ) -> Signature:
        """
        Compiles a Celery task that follows the structure of the composite template.
        """
        if isinstance(template, str):
            self.nr_tasks += 1
            return self._invoke_task.s(template)

        if isinstance(template, Task):
            self.nr_tasks += 1
            return template.s(render_data)

        if isinstance(template, list):
            chained = None
            for t in template:
                if chained is None:
                    chained = self._compile_task_graph(t, render_data)
                else:
                    chained |= self._chained_template_task.s(render_data)
                    chained |= self._compile_task_graph(t, render_data)
            self.nr_tasks += 2 * len(template) - 1
            return chained

        if isinstance(template, dict):
            dict_keys = list(template.keys())  # make sure to go through keys in fixed order
            self.nr_tasks += len(dict_keys) + 1
            return chord(
                group(*[self._compile_task_graph(template[k], render_data) for k in dict_keys]),
                self._combine_group_to_dict_task.s(dict_keys),
            )

        raise ValueError(
            f"cannot compile a task for a render of type '{type(template)}'"
        )

    def _compile_task(self, template, render_data: dict[str, Any]):
        template_task = self._compile_task_graph(template, render_data)
        self.task = (
            template_task |
            self._trigger_ai_event_task.s(
                self.model_fqn,
                self.session_id,
                self.event_to_send_after,
            )
        )
        self.nr_tasks += 1


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
            """
            This Celery Task is executed at the end of an AI transition and all the relevant
            Invokers have run. It takes the output of the previous task, pulls up the model
            form the store, creates the state machine for it and sends that state machine
            the event that was given.

            :param task_instance: Celery Task instance - a reference to this task itself (bound)
            :param response: The response from the previous task
            :param cls_fqn: The fully qualified name of the class of the model
            :param session_id: The session id
            :param event_name: The name of the event that needs to be sent to the state machine
            """
            model_class = get_class_from_fully_qualified_name(cls_fqn)
            with self.session_lock_manager.get_locked_model(session_id, model_class) as model:
                model.complete_running_task(task_instance.request.id)

                state_machine = model.get_state_machine_class()(model)
                state_machine.add_observer(self)

                logging.debug(f"sending {event_name} to model for session {session_id}")
                state_machine.send(event_name, response)
                logging.debug(f"actor input is now {model.actor_input}")
                model.complete_subtask()

        return trigger_ai_event

    def _add_invoke_task(self):

        @self.celery_app.task(name="genie_flow.invoke_task")
        def invoke_ai_event(render_data: dict[str, Any], template_name: str) -> str:
            """
            This Celery Task executes the actual Invocation. It is given the data that should be
            used to render the template. It then recreates the Dialogue and invokes the template.

            :param render_data: The data that should be used to render the template
            :param template_name: The name of the template that should be used to render
            :returns: the result of the invocation
            """
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

    def enqueue_task(
            self,
            template: CompositeTemplateType,
            session_id: str,
            render_data: dict[str, Any],
            model_fqn: str,
            event_to_send_after: str,
    ) -> tuple[str, int]:
        task_compiler = _TaskCompiler(
            self.celery_app,
            template,
            session_id,
            render_data,
            model_fqn,
            event_to_send_after,
        )

        task_id = task_compiler.task.apply_async((render_data,)).id
        return task_id, task_compiler.nr_tasks

    def _enqueue_task(
            self,
            state_machine: GenieStateMachine,
            model: GenieModel,
            target_state: State,
    ):
        task_id, nr_tasks = self.enqueue_task(
            template=state_machine.get_template_for_state(target_state),
            session_id=model.session_id,
            render_data=state_machine.render_data,
            model_fqn=get_fully_qualified_name_from_class(model),
            event_to_send_after=target_state.transitions.unique_events[0],
        )
        model.set_running_task(task_id, nr_tasks)

    def get_task_result(self, task_id) -> AsyncResult:
        return AsyncResult(task_id, app=self.celery_app)

    def on_user_input(self, event_data: EventData):
        logger.debug("User input received")
        event_data.machine.model.actor = "user"
        self._enqueue_task(
            event_data.machine,
            event_data.machine.model,
            event_data.target,
        )

    def on_ai_extraction(self, event_data: EventData):
        logger.debug("AI extraction event received")
        event_data.machine.model.actor = "assistant"
        event_data.machine.model.actor_input = self.genie_environment.render_template(
            template_path=event_data.machine.get_template_for_state(event_data.target),
            data_context=event_data.machine.render_data,
        )

    def on_advance(self, event_data: EventData):
        logger.debug("Advance event received")
        event_data.machine.model.actor = "assistant"
        self._enqueue_task(
            event_data.machine,
            event_data.machine.model,
            event_data.target,
        )
