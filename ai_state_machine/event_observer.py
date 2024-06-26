from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from ai_state_machine import GenieEnvironment
from ai_state_machine.celery import CeleryManager
from ai_state_machine.genie import GenieStateMachine, GenieModel
from ai_state_machine.utils import get_fully_qualified_name_from_class


class GenieStateMachineObserver:

    def __init__(
            self,
            genie_environment: GenieEnvironment,
            celery_manager: CeleryManager,
    ):
        self._genie_environment = genie_environment
        self._celery_manager = celery_manager

    def _enqueue_task(
            self,
            state_machine: GenieStateMachine,
            model: GenieModel,
            target_state: State,
    ):
        task_id = self._celery_manager.enqueue_task(
            template=state_machine.get_template(target_state),
            session_id=model.session_id,
            render_data=state_machine.render_data,
            model_fqn=get_fully_qualified_name_from_class(model),
            event_to_send_after=target_state.transitions.unique_events[0],
        )
        model.add_running_task(task_id)

    def on_user_input(self, event_data: EventData):
        logger.debug("User input received")
        self._enqueue_task(event_data.machine, event_data.machine.model)

    def on_ai_extraction(self, event_data: EventData):
        logger.debug("AI extraction event received")
        event_data.machine.model.actor_input = self._genie_environment.render_template(
            template_path=event_data.machine.get_template(event_data.target),
            data_context=event_data.machine.render_data,
        )

    def on_advance(self, event_data: EventData):
        logger.debug("Advance event received")
        self._enqueue_task(event_data)
