import uuid

import redis_lock
from redis import Redis
from statemachine.exceptions import TransitionNotAllowed

from ai_state_machine.genie_model import GenieModel
from ai_state_machine.model import EventInput, AIResponse, AIStatusResponse
from ai_state_machine.registry import ModelKeyRegistryType


class SessionLockManager:

    def __init__(
            self,
            redis_lock_store: Redis,
            lock_expiration_seconds: int,
    ):
        self.redis_lock_store = redis_lock_store
        self.lock_expiration_seconds = lock_expiration_seconds

    def get_lock_for_session(self, session_id: str) -> redis_lock.Lock:
        """
        Retrieve the lock for the object for the given `session_id`. This ensures that only
        one process will have access to the model and potentially make changes to it.
        This lock can function as a context manager. See the documentation of `redis_lock.Lock`
        :param session_id: The session id that the object in question belongs to
        """
        lock = redis_lock.Lock(
            self.redis_lock_store,
            name=f"lock-{session_id}",
            expire=self.lock_expiration_seconds,
            auto_renewal=True,
        )
        return lock


class SessionManager:

    def __init__(
            self,
            session_lock_manager: SessionLockManager,
            model_key_registry: ModelKeyRegistryType
    ):
        self.session_lock_manager = session_lock_manager
        self.model_key_registry = model_key_registry

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
        state_machine = model.state_machine_class(model=model, new_session=True)
        model.__class__.insert(model)

        response = model.current_response.actor_text

        return AIResponse(
            session_id=session_id,
            response=response,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    @staticmethod
    def _handle_poll(model: GenieModel) -> AIResponse:
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
        if model.running_task_id is not None:
            return AIResponse(session_id=model.session_id, next_actions=['poll'])

        state_machine = model.create_state_machine()
        return AIResponse(
            session_id=model.session_id,
            response=state_machine.model.current_response.actor_text,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    @staticmethod
    def _handle_event(event: EventInput, model: GenieModel) -> AIResponse:
        """
        This method handels events from the client. It creates the state machine instance for the
        given object and sends the event to it. It then stores the model instance back into Redis.

        If the state machine, after processing the given event, has a currently running task,
        this method returns an AIResponse object with the only next actions to be `poll`.

        If the processing of the event by the state machine has not resulted in a task, this method
        returns an AIResponse object with the most recently recorded actor text and the events that
        can be sent from the current state.

        :param event: the event to process
        :param model: the model to process the event against
        :return: an instance of `AIResponse` with the appropriate values
        """
        state_machine = model.create_state_machine()
        state_machine.send(event.event, event.event_input)
        model.__class__.insert(model)

        if model.running_task_id is not None:
            return AIResponse(session_id=event.session_id, next_actions=['poll'])
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
        with self.session_lock_manager.get_lock_for_session(event.session_id):
            models = model_class.select(ids=[event.session_id])
            assert len(models) == 1
            model = models[0]

            if event.event == "poll":
                return self._handle_poll(model)

            try:
                return self._handle_event(event, model)
            except TransitionNotAllowed as e:
                return AIResponse(
                    session_id=event.session_id,
                    error=str(e),
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
        model_class = self.model_key_registry[model_key]
        with self.session_lock_manager.get_lock_for_session(session_id):
            models = model_class.select(ids=[session_id])
            assert len(models) == 1
            model = models[0]

            if model.running_task_id is not None:
                return AIStatusResponse(
                    session_id=session_id,
                    ready=False,
                )

            state_machine = model.create_state_machine()
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
        with self.session_lock_manager.get_lock_for_session(session_id):
            models = model_class.select(ids=[session_id])
            if len(models) == 0:
                raise KeyError(f"No model with id {session_id}")
            if len(models) > 1:
                raise RuntimeError(f"Multiple models with id {session_id}")
            return models[0]
