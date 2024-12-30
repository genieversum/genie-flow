import json
import typing
from typing import Any

import jmespath
from celery import Celery, Task
from celery.app.task import Context
from celery.canvas import chord, group
from celery.result import AsyncResult
from loguru import logger
from statemachine import State

from genie_flow.celery.compiler import TaskCompiler
from genie_flow.celery.progress import ProgressLoggingTask

from genie_flow.environment import GenieEnvironment
from genie_flow.genie import GenieModel, GenieStateMachine, GenieTaskProgress
from genie_flow.model.template import CompositeContentType
from genie_flow.session_lock import SessionLockManager
from genie_flow.utils import get_class_from_fully_qualified_name, \
    get_fully_qualified_name_from_class

if typing.TYPE_CHECKING:
    from genie_flow.celery.transition import TransitionManager


def parse_if_json(s: str) -> Any:
    if not isinstance(s, str):
        return s

    try:
        return json.loads(s)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return s


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

        self._add_error_handler()
        self._add_trigger_ai_event_task()
        self._add_invoke_task()
        self._add_map_task()
        self._add_combine_group_to_dict()
        self._add_combine_group_to_list()
        self._add_chained_template()

    def _process_model_event(
            self,
            event_argument: str,
            model: GenieModel,
            session_id: str,
            event_name: str,
    ):
        state_machine = model.get_state_machine_class()(model)
        state_machine.add_listener(TransitionManager(self))

        logger.debug(f"sending {event_name} to model for session {session_id}")
        state_machine.send(event_name, event_argument)
        logger.debug(f"actor input is now {model.actor_input}")

    def _add_error_handler(self):

        @self.celery_app.task(name="genie_flow.error_handler")
        def error_handler(
                request: Context,
                exc,
                traceback,
                cls_fqn: str,
                session_id: str,
                event_name: str,
        ):
            """
            Process a backend error. The error is captured and the exception added to the model's
            task_error property. The final event is (still) being sent to the state machine. But the
            actor's input is an empty string.
            """
            logger.error(f"Task {request.id} raised an error: {exc}")
            logger.exception(traceback)

            model_class = get_class_from_fully_qualified_name(cls_fqn)
            with self.session_lock_manager.get_locked_model(
                    session_id,
                    model_class,
            ) as model:
                self._process_model_event(
                    event_argument="",
                    model=model,
                    session_id=session_id,
                    event_name=event_name,
                )

                if model.task_error is None:
                    model.task_error = ""
                model.task_error += json.dumps(
                    dict(
                        session_id=session_id,
                        task_id=request.id,
                        task_name=request.id,
                        exception=str(exc),
                    )
                )

        return error_handler

    def _add_trigger_ai_event_task(self):

        @self.celery_app.task(
            bind=True,
            base=ProgressLoggingTask,
            name='genie_flow.trigger_ai_event'
        )
        def trigger_ai_event(
                task_instance,
                response: str,
                cls_fqn: str,
                event_name: str,
                session_id: str,
        ):
            """
            This Celery Task is executed at the end of a Celery DAG and all the relevant
            Invokers have run. It takes the output of the previous task, pulls up the model
            form the store, creates the state machine for it and sends that state machine
            the event that was given.

            :param task_instance: Celery Task instance - a reference to this task itself (bound)
            :param response: The response from the previous task
            :param cls_fqn: The fully qualified name of the class of the model
            :param event_name: The name of the event that needs to be sent to the state machine
            :param session_id: The session id for which this task is executed
            """
            model_class = get_class_from_fully_qualified_name(cls_fqn)
            with self.session_lock_manager.get_locked_model(session_id, model_class) as model:
                task_progress_list = GenieTaskProgress.select(ids=[session_id])
                if len(task_progress_list) == 0:
                    raise ValueError(f"Could not find task progress for session {session_id}")
                task_progress = task_progress_list[0]
                if task_progress.nr_subtasks_executed - task_progress.total_nr_subtasks > 1:
                    logger.warning(f"Not all subtasks for session {session_id} have been executed")
                GenieTaskProgress.delete(ids=[session_id])

                state_machine = model.get_state_machine_class()(model)
                state_machine.add_listener(TransitionManager(self))

                logger.debug(f"sending {event_name} to model for session {session_id}")
                state_machine.send(event_name, response)
                logger.debug(f"actor input is now {model.actor_input}")

        return trigger_ai_event

    def _add_invoke_task(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            name="genie_flow.invoke_task",
        )
        def invoke_ai_event(
                render_data: dict[str, Any],
                template_name: str,
                session_id: str,
        ) -> str:
            """
            This Celery Task executes the actual Invocation. It is given the data that should be
            used to render the template. It then invokes the template.

            :param render_data: The data that should be used to render the template
            :param template_name: The name of the template that should be used to render
            :param session_id: The session id for which this task is executed
            :returns: the result of the invocation
            """
            return self.genie_environment.invoke_template(template_name, render_data)

        return invoke_ai_event

    def _add_map_task(self):

        @self.celery_app.task(
            bind=True,
            base=ProgressLoggingTask,
            name="genie_flow.map_task",
        )
        def map_task(
                task_instance: Task,
                render_data: dict[str, Any],
                list_attribute: str,
                map_index_field: str,
                map_value_field: str,
                template_name: str,
                session_id: str,
        ):
            """
            This task maps a template onto the different values in a list of model parameters.
            Each of the invocations will be created as a separate Celery task. A final task
            will be run, converting the output into a JSON list of results.

            This mapping will be done at run-time, so all the values in the model's list
            attribute will generate a separate invocation of the template.

            When the template is invoked, it will be rendered with the complete render_data
            object, with an addition of two attributes: the attribute identifying the index
            of the value it is rendered for, and an attribute containing the value itself.

            The names of these attributes are given by `map_index_field` and `map_value_field`
            respectively.

            At this time, only a simple rendered template can be used - no list, dict or
            otherwise.

            :param task_instance: a reference to the map task
            :param render_data: the dict of template render data
            :param list_attribute: the JMES Path into the attribute to map
            :param map_index_field: the name of the attribute carrying the index
            :param map_value_field: the name of the attribute carrying the value
            :param template_name: the name of the template that should be used to render
            :param session_id: the session id for which this task is executed
            """
            list_values = jmespath.search(list_attribute, render_data)
            if not isinstance(list_values, list):
                logger.warning(
                    "path to attribute returns type {path_type} and not a list",
                    path_type=type(list_values),
                )
                list_values = [list_values]

            render_data_list = []
            for map_index, map_value in enumerate(list_values):
                updated_render_data = render_data.copy()
                updated_render_data[map_index_field] = map_index
                updated_render_data[map_value_field] = map_value
                render_data_list.append(updated_render_data)

            invoke_task = self.celery_app.tasks["genie_flow.invoke_task"]
            mapped_tasks = [
                invoke_task.s(updated_render_data, template_name, session_id)
                for updated_render_data in render_data_list
            ]

            combine_task = self.celery_app.tasks["genie_flow.combine_group_to_list"]
            return task_instance.replace(
                chord(
                    group(*mapped_tasks),
                    combine_task.s(session_id),
                )
            )

        return map_task

    def _add_combine_group_to_dict(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            name="genie_flow.combine_group_to_dict",
        )
        def combine_group_to_dict(
                results: list[CompositeContentType],
                keys: list[str],
                session_id: str,
        ) -> CompositeContentType:
            parsed_results = [parse_if_json(s) for s in results]
            return json.dumps(dict(zip(keys, parsed_results)))

        return combine_group_to_dict

    def _add_combine_group_to_list(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            name="genie_flow.combine_group_to_list",
        )
        def combine_chain_to_list(
                results: list[CompositeContentType],
                session_id: str,
        ):
            parsed_results = [parse_if_json(s) for s in results]
            return json.dumps(parsed_results)

        return combine_chain_to_list

    def _add_chained_template(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            name="genie_flow.chained_template",
        )
        def chained_template(
                result_of_previous_call: CompositeContentType,
                render_data: dict[str, str],
                session_id: str,
        ) -> CompositeContentType:

            def parse_result(result: CompositeContentType) -> CompositeContentType:
                if isinstance(result, str):
                    try:
                        return json.loads(result)
                    except json.JSONDecodeError:
                        return result

                if isinstance(result, list):
                    return [parse_result(e) for e in result]

                if isinstance(result, dict):
                    return {k: parse_result(result[k]) for k in result.keys()}

                return result

            render_data["previous_result"] = result_of_previous_call
            render_data["parsed_previous_result"] = parse_result(result_of_previous_call)

            return render_data

        return chained_template

    def enqueue_task(
            self,
            state_machine: GenieStateMachine,
            model: GenieModel,
            target_state: State,
    ):
        """
        Create a new Celery DAG and place it on the Celery queue.

        The DAG is compiled using the `TaskCompiler`, the error handler gets assigned,
        the DAG is enqueued and a new `GenieTaskProgress` object is persisted.

        This is also the point in time where the `render_data` is created (by using the
        `render_data` property of the machine) and therefore frozen. That then becomes
        the `render_data` that is used inside the DAG.

        :param state_machine: the active state machine to use
        :param model: the data model
        :param target_state: the state we will transition into
        """
        model_fqn = get_fully_qualified_name_from_class(model)
        event_to_send_after = target_state.transitions.unique_events[0]
        task_compiler = TaskCompiler(
            self.celery_app,
            state_machine.get_template_for_state(target_state),
            model.session_id,
            state_machine.render_data,
            model_fqn,
            event_to_send_after,
        )
        task_compiler.task.on_error(
            task_compiler.error_handler.s(
                model_fqn,
                model.session_id,
                event_to_send_after,
            )
        )

        task = task_compiler.task.apply_async((state_machine.render_data,))
        GenieTaskProgress.insert(
            GenieTaskProgress(
                session_id=model.session_id,
                task_id=task.id,
                total_nr_subtasks=task_compiler.nr_tasks,
            )
        )

    def get_task_result(self, task_id) -> AsyncResult:
        return AsyncResult(task_id, app=self.celery_app)
