import json
from typing import Any, Optional

import jmespath
from celery import Celery, Task
from celery.app.task import Context
from celery.canvas import chord, group, Signature
from celery.result import AsyncResult
from loguru import logger
from statemachine import State

from genie_flow.celery.compiler import TaskCompiler
from genie_flow.celery.progress import ProgressLoggingTask
from genie_flow.celery.transition import TransitionManager
from genie_flow.environment import GenieEnvironment
from genie_flow.genie import GenieModel, GenieStateMachine
from genie_flow.model.template import CompositeContentType
from genie_flow.mongo import store_session, store_user
from genie_flow.session_lock import SessionLockManager
from genie_flow.utils import get_fully_qualified_name_from_class


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
        update_mongo_period: float,
    ):
        self.celery_app = celery
        self.session_lock_manager = session_lock_manager
        self.genie_environment = genie_environment
        self.update_mongo_period = update_mongo_period

        self._add_error_handler()
        self._add_trigger_ai_event_task()
        self._add_invoke_task()
        self._add_wrap_index()
        self._add_recompile()
        self._add_map_task()
        self._add_combine_group_to_dict()
        self._add_combine_group_to_list()
        self._add_chained_template()
        self._add_update_mongo_task()
        self._add_periodic_tasks()

    def _retrieve_render_data(
            self,
            drag_net: Optional[dict],
            session_id: str,
            model_fqn: str,
    ) -> dict:
        """
        Retrieve the render data for a given session id and model. A task may have run before
        this and created a drag net dictionary of attributes that need to be added to the
        `render_data`.

        :param drag_net: an optional dict of values that need to be merged into the `render_data`
        :param session_id: the session id
        :param model_fqn: the model fully-qualified name
        :return: a dict with render data
        """
        logger.debug(
            "Retrieving render data for session {session_id}",
            session_id=session_id,
        )
        model = self.session_lock_manager.get_model(session_id, model_fqn)
        render_data = model.render_data

        if drag_net is not None:
            logger.debug(
                "Merging drag net values {drag_net} with render data",
                drag_net=drag_net,
            )
            render_data.update(drag_net)
        return render_data

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
                invocation_id: str,
                event_name: str,
        ):
            """
            Process a backend error. The error is captured and the exception added to the model's
            task_error property. The final event is (still) being sent to the state machine. But the
            actor's input is an empty string.
            """
            logger.error(
                "Task {request.id}, for session {session_id}, invocation {invocation_id} "
                "raised an error: {exc}",
                request=request,
                session_id=session_id,
                invocation_id=invocation_id,
                exc=exc,
            )
            logger.exception(traceback)

            with self.session_lock_manager.get_locked_model(session_id, cls_fqn) as model:
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
                        invocation_id=invocation_id,
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
            session_lock_manager=self.session_lock_manager,
            name='genie_flow.trigger_ai_event'
        )
        def trigger_ai_event(
                task_instance,
                response: str,
                event_name: str,
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ):
            """
            This Celery Task is executed at the end of a Celery DAG and all the relevant
            Invokers have run. It takes the output of the previous task, pulls up the model
            form the store, creates the state machine for it and sends that state machine
            the event that was given.

            :param task_instance: Celery Task instance - a reference to this task itself (bound)
            :param response: The response from the previous task
            :param event_name: The name of the event that needs to be sent to the state machine
            :param session_id: The session id for which this task is executed
            :param model_fqn: The fully qualified name of the class of the model
            """
            with self.session_lock_manager.get_locked_model(session_id, model_fqn) as model:
                self.session_lock_manager.progress_tombstone(session_id, invocation_id)

                state_machine = model.get_state_machine_class()(model)
                state_machine.add_listener(TransitionManager(self))

                logger.debug(
                    "sending {event_name} to state machine for session {session_id}",
                    event_name=event_name,
                    session_id=session_id,
                )
                state_machine.send(event_name, response)

                if model.actor_input is None:
                    logger.debug("actor input is None")
                else:
                    logger.debug(
                        "actor input is now '{actor_input}'",
                        actor_input=(
                            model.actor_input
                            if len(model.actor_input) < 50
                            else model.actor_input[:50] + "..."
                        ),
                    )

        return trigger_ai_event

    def _add_invoke_task(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.invoke_task",
        )
        def invoke_ai_event(
                drag_net: Optional[dict],
                template_name: str,
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ) -> str:
            """
            This Celery Task executes the actual Invocation. It is given the data that should be
            used to render the template. It then invokes the template.

            :param drag_net: potential dict of values that need to be merged into the `render_data`
            :param template_name: The name of the template that should be used to render
            :param session_id: The session id for which this task is executed
            :param model_fqn: The fully qualified name of the model
            :param invocation_id: the id of the invocation that is being executed
            :returns: the result of the invocation
            """
            render_data = self._retrieve_render_data(drag_net, session_id, model_fqn)
            return self.genie_environment.invoke_template(template_name, render_data)

        return invoke_ai_event

    def _add_wrap_index(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.wrap_index",
        )
        def wrap_index(
                map_index: int,
                task_signature: Signature | dict,
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ) -> tuple[int, Any]:
            """
            This is a helper function that wraps the invocation of a task with the index of
            the position in a list. This is used to ensure that the order of the results can
            be recompiled correctly.

            :param map_index: the position in the list of the invocation result
            :param task_signature: the signature of the task to be invoked, or a dict of the same
            :param session_id: The session id for which this task is executed
            :param model_fqn: The fully qualified name of the model
            :param invocation_id: the id of the invocation that is being executed
            :return: a tuple containing the index and the result of the invocation.
            """
            if isinstance(task_signature, dict):
                task_signature = Signature.from_dict(task_signature)
            return map_index, parse_if_json(task_signature())

        return wrap_index

    def _add_recompile(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.recompile",
        )
        def recompile(
                results: list,
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ):
            """
            This is a helper function that re-orders the results of a task that has been
            jumbled. This function expects a list of tuples, where the first element is the
            original position in a list. The second element is the result of the invocation.
            :param results: a list of tuples
            :param session_id: the session id for which this task is executed
            :param model_fqn: the model fully qualified name for which this task is executed
            :param invocation_id: the invocation id for which this task is executed
            :return: a list of results in the order they were invoked.
            """
            if len(results) > 1:
                if all(
                        results[i][0] == results[i-1][0] + 1
                        for i in range(1, len(results))
                ):
                    logger.warning(
                        "results are in order, reordering not strictly required "
                        "for session {session_id} invocation {invocation_id}",
                        session_id=session_id,
                        invocation_id=invocation_id,
                    )

            results.sort(key=lambda x: x[0])
            return json.dumps([r[1] for r in results])

        return recompile

    def _add_map_task(self):

        @self.celery_app.task(
            bind=True,
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.map_task",
        )
        def map_task(
                task_instance: Task,
                drag_net: Optional[dict],
                list_attribute: str,
                map_index_field: str,
                map_value_field: str,
                template_name: str,
                session_id: str,
                model_fqn: str,
                invocation_id: str,
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

            :param task_instance: a reference to the map task itself
            :param drag_net: potential dict of values that need to be merged into the `render_data`
            :param list_attribute: the JMES Path into the attribute to map
            :param map_index_field: the name of the attribute carrying the index
            :param map_value_field: the name of the attribute carrying the value
            :param template_name: the name of the template that should be used to render
            :param session_id: the session id for which this task is executed
            :param model_fqn: the fully qualified name of the model
            """
            render_data = self._retrieve_render_data(drag_net, session_id, model_fqn)
            list_values = jmespath.search(list_attribute, render_data)
            if not isinstance(list_values, list):
                logger.warning(
                    "path to attribute returns type {path_type} and not a list",
                    path_type=type(list_values),
                )
                list_values = [list_values]

            index_wrapper_task = self.celery_app.tasks["genie_flow.wrap_index"]
            invoke_task = self.celery_app.tasks["genie_flow.invoke_task"]

            # We wrap the actual invocation with the index wrapper. This is to work around
            # an apparent bug in Celery where replacing a task with a group jumbles up the
            # order of the results. See the discussion on the Celery home here:
            # https://github.com/celery/celery/discussions/9731
            # The index wrapper task simply returns the index and the invocation result.
            # We then use the recompile task to re-order the results.
            mapped_tasks = [
                index_wrapper_task.s(
                    map_index,
                    invoke_task.s(
                        {
                            map_index_field: map_index,
                            map_value_field: map_value,
                        },
                        template_name,
                        session_id,
                        model_fqn,
                        invocation_id,
                    ),
                    session_id,
                    model_fqn,
                    invocation_id,
                )
                for map_index, map_value in enumerate(list_values)
            ]
            recompile_task = self.celery_app.tasks["genie_flow.recompile"]

            # increase the number of tasks To Do by the number of values mapped,
            # plus one for the combine task, minus one because we are replacing
            # this MapTaskTemplate task that was already counted
            self.session_lock_manager.progress_update_todo(
                session_id,
                invocation_id,
                len(list_values),
            )
            return task_instance.replace(
                chord(
                    group(*mapped_tasks),
                    recompile_task.s(session_id, model_fqn, invocation_id),
                )
            )

        return map_task

    def _add_combine_group_to_dict(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.combine_group_to_dict",
        )
        def combine_group_to_dict(
                results: list[CompositeContentType],
                keys: list[str],
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ) -> CompositeContentType:
            parsed_results = [parse_if_json(s) for s in results]
            return json.dumps(dict(zip(keys, parsed_results)))

        return combine_group_to_dict

    def _add_combine_group_to_list(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.combine_group_to_list",
        )
        def combine_chain_to_list(
                results: list[CompositeContentType],
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ):
            parsed_results = [parse_if_json(s) for s in results]
            return json.dumps(parsed_results)

        return combine_chain_to_list

    def _add_chained_template(self):

        @self.celery_app.task(
            base=ProgressLoggingTask,
            session_lock_manager=self.session_lock_manager,
            name="genie_flow.chained_template",
        )
        def chained_template(
                result_of_previous_call: CompositeContentType,
                session_id: str,
                model_fqn: str,
                invocation_id: str,
        ) -> CompositeContentType:

            parsed_previous_result = None
            try:
                parsed_previous_result = json.loads(result_of_previous_call)
            except json.decoder.JSONDecodeError:
                pass

            return dict(
                previous_result=result_of_previous_call,
                parsed_previous_result=parsed_previous_result,
            )

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
            model_fqn,
            target_state.id,
            event_to_send_after,
        )
        task_compiler.task.on_error(
            task_compiler.error_handler.s(
                model_fqn,
                model.session_id,
                task_compiler.invocation_id,
                event_to_send_after,
            )
        )

        # enqueuing the compiled task with an empty drag_net dictionary
        task = task_compiler.task.apply_async((None,))

        self.session_lock_manager.progress_start(
            session_id=model.session_id,
            invocation_id=task_compiler.invocation_id,
            nr_tasks_todo=task_compiler.nr_tasks,
        )

    def get_task_result(self, task_id) -> AsyncResult:
        return AsyncResult(task_id, app=self.celery_app)

    def _add_update_mongo_task(self):

        @self.celery_app.task(name="genie_flow.scheduler.update_mongo")
        def update_mongo():
            logger.debug("update mongo running")
            updated_sessions = self.session_lock_manager.redis_object_store.smembers(
                self.session_lock_manager.update_set_key
            )
            for session_item in updated_sessions:
                fqn, session_id = session_item.decode().rsplit(':', 1)
                with self.session_lock_manager.get_locked_model(
                        session_id=session_id,
                        model_class=fqn
                ) as model:
                    store_session(model)
                    try:
                        store_user(model.secondary_storage["user_info"], session_id)
                    except KeyError:
                        logger.warning(
                            "No user info found for session {session_id}; ignoring",
                            session_id=session_id,
                        )
                    self.session_lock_manager.redis_object_store.srem(self.session_lock_manager.update_set_key, session_id)
        return update_mongo

    def _add_periodic_tasks(self):
        self.celery_app.conf.beat_schedule = {
            'add-every-30-seconds': {
                'task': 'genie_flow.scheduler.update_mongo',
                'schedule': self.update_mongo_period
            },
        }