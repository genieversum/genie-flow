import json
import uuid

from loguru import logger
from statemachine.exceptions import TransitionNotAllowed

from genie_flow.celery import CeleryManager
from genie_flow.celery.transition import TransitionManager
from genie_flow.environment import GenieEnvironment
from genie_flow.genie import GenieModel
from genie_flow.model.types import ModelKeyRegistryType
from genie_flow.model.api import AIResponse, EventInput, AIStatusResponse, AIProgressResponse
from genie_flow.session_lock import SessionLockManager


class SessionManager:
    """
    A `SessionManager` instance deals with the lifetime events against the state machine of a
    session. From conception (through a `start_session` call), to handling events being sent
    to the state machine.
    """

    def __init__(
        self,
        session_lock_manager: SessionLockManager,
        model_key_registry: ModelKeyRegistryType,
        genie_environment: GenieEnvironment,
        celery_manager: CeleryManager,
    ):
        self.session_lock_manager = session_lock_manager
        self.model_key_registry = model_key_registry
        self.genie_environment = genie_environment
        self.celery_manager = celery_manager

    def create_new_session(self, model_key: str) -> AIResponse:
        """
        Create a new session. This method creates a new session id (UUID4), creates a model
        instance of the given model class, initiates a state machine for that model instance
        and finally persists the model to Redis.

        The state machine is initiated with the `new_session` flag true, forcing it to place
        the state machine into the initial state and setting the appropriate values of the new
        model instance.

        The method then returns the appropriate `AIResponse` object with the (initial) response
        and the actions that the state machine can take from this initial state.

        :param model_key: the key under which the model class is registered
        :return: an instance of `AIResponse` with the appropriate values
        """
        session_id = str(str(uuid.uuid4()))

        model_class = self.model_key_registry[model_key]
        model = model_class(session_id=session_id)

        state_machine = model.get_state_machine_class()(model)

        initial_prompt = self.genie_environment.render_template(
            state_machine.get_template_for_state(state_machine.current_state),
            state_machine.render_data,
        )
        model.add_dialogue_element("assistant", initial_prompt)
        self.session_lock_manager.store_model(model)

        response = model.current_response.actor_text

        return AIResponse(
            session_id=session_id,
            response=response,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    def _handle_poll(self, model: GenieModel) -> AIResponse:
        """
        This method handles polling from the client. As long as the model instance has a value
        for `running_task_id`, this method returns an AIResponse object with the only possible
        next actions to be `poll`.

        If the model instance does no longer have a running task (because that was finished)
        an AIResponse object is created with the session id, the most recently recorded actor
        text and the events that can be sent from the current state.

        :param model: the model that needs to be polled
        :return: an instance of `AIResponse` with the appropriate values
        """
        if self.session_lock_manager.progress_exists(model.session_id):
            todo, done = self.session_lock_manager.progress_status(model.session_id)
            return AIResponse(
                session_id=model.session_id,
                next_actions=["poll"],
                progress=AIProgressResponse(
                    total_number_of_subtasks=todo,
                    number_of_subtasks_executed=done,
                )
            )

        state_machine = model.get_state_machine_class()(model)
        if model.has_errors:
            return AIResponse(
                session_id=model.session_id,
                error=model.task_error,
                next_actions=state_machine.current_state.transitions.unique_events,
            )
        try:
            actor_response = state_machine.model.current_response.actor_text
        except AttributeError:
            logger.warning(
                "There is no recorded actor response for session {session_id}",
            )
            actor_response = ""

        return AIResponse(
            session_id=model.session_id,
            response=actor_response,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    def _handle_event(self, event: EventInput, model: GenieModel) -> AIResponse:
        """
        This method handels events from the client. It creates the state machine instance for the
        given object and sends the event to it. It then stores the model instance back into Redis.

        If the state machine, after processing the given event, has a currently running task,
        this method returns an AIResponse object with the only next actions to be `poll`.

        If the processing of the event by the state machine has not resulted in a task, this method
        returns an AIResponse object with the most recently recorded actor text and the events that
        can be sent from the current state.

        Session locking, saving and storing of the model object needs to happen outside of
        this method.

        :param event: the event to process
        :param model: the model to process the event against
        :return: an instance of `AIResponse` with the appropriate values
        """
        state_machine = model.get_state_machine_class()(model)
        state_machine.add_listener(TransitionManager(self.celery_manager))
        state_machine.send(event.event, event.event_input)

        if self.session_lock_manager.progress_exists(model.session_id):
            return AIResponse(session_id=event.session_id, next_actions=["poll"])

        return AIResponse(
            session_id=event.session_id,
            response=state_machine.model.current_response.actor_text,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    def process_event(self, model_key: str, event: EventInput) -> AIResponse:
        """
        Process incoming events. Claims a lock to the model instance that the event refers to
        and checks the event. If the event is a `poll` event, handling is performed by the
        `_handle_poll` method. If not, this method returns the result of processing the event.

        :param model_key: the key under which the model class is registered
        :param event: the event to process
        :return: an instance of `AIResponse` with the appropriate values
        """
        model_class = self.model_key_registry[model_key]
        with self.session_lock_manager.get_locked_model(event.session_id, model_class) as model:
            if event.event == "poll":
                return self._handle_poll(model)

            try:
                return self._handle_event(event, model)
            except TransitionNotAllowed:
                state_machine = model.get_state_machine_class()(model)
                return AIResponse(
                    session_id=event.session_id,
                    error=json.dumps(
                        dict(
                            session_id=model.session_id,
                            current_state=dict(
                                id=state_machine.current_state.id,
                                name=state_machine.current_state.name,
                            ),
                            possible_events=state_machine.current_state.transitions.unique_events,
                            received_event=event.event,
                        )
                    )
                )

    def get_task_state(self, model_key: str, session_id: str) -> AIStatusResponse:
        """
        Retrieves an instance of the model object and returns if that object has any running
        tasks against it. It obtains a lock on the given session id to ensure consistency of
        the model values.

        The `AIStatusResponse` that this method returns indicates if the task is currently running,
        or, if it is no longer running, what the possible next actions are.

        :param model_key: the key under which the model class is registered
        :param session_id: the id of the session that the model instance belongs to
        :return: an instance of `AIStatusResponse`, indicating if the task is ready and what
        possible next actions can be sent in the current state of the model.
        """
        if self.session_lock_manager.progress_exists(session_id):
            return AIStatusResponse(
                session_id=session_id,
                ready=False,
            )

        model_class = self.model_key_registry[model_key]
        model = self.session_lock_manager.get_model(session_id, model_class)
        state_machine = model.get_state_machine_class()(model=model)
        return AIStatusResponse(
            session_id=session_id,
            ready=True,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    def get_model(self, model_key: str, session_id: str) -> GenieModel:
        """
        Retrieve the entire model instance that belongs to the given session id. Obtains a lock
        on the session to ensure consistency of the model values.

        :param model_key: the key under which the model class is registered
        :param session_id: the session id to retrieve the model instance for
        :return: the model instance that belongs to the given session id
        """
        model_class = self.model_key_registry[model_key]
        return self.session_lock_manager.get_model(session_id, model_class)
