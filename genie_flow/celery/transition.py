from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from genie_flow.celery import CeleryManager
from genie_flow.genie import StateType, TransitionType, DialoguePersistence
from genie_flow.model.template import CompositeTemplateType


_DIALOGUE_PERSISTENCE_MAP: dict[StateType, dict[StateType, DialoguePersistence]] = {
    StateType.USER: {
        StateType.USER: DialoguePersistence.RAW,
        StateType.INVOKER: DialoguePersistence.RAW,
    },
    StateType.INVOKER: {
        StateType.USER: DialoguePersistence.RENDERED,
        StateType.INVOKER: DialoguePersistence.NONE,
    }
}

class TransitionManager:

    def __init__(self, celery_manager: CeleryManager):
        self.celery_manager = celery_manager

    def _determine_transition_type(self, event_data: EventData):
        def determine_type(state: State) -> StateType:
            state_template: CompositeTemplateType = event_data.machine.get_template_for_state(state)
            return (
                StateType.INVOKER
                if self.celery_manager.genie_environment.has_invoker(state_template)
                else StateType.USER
            )

        return TransitionType(
            determine_type(event_data.source),
            determine_type(event_data.target),
        )

    def before_transition(self, event_data: EventData):
        """
        This hook determines how the transition will be conducted. It will
        set the property `transition_type` to a tuple containing the source type
        and the destination type. This hook also determines if and how the event
        argument should be stored as part of the dialogue. The property
        `dialogue_persistence` is set to "NONE", "RAW" or "RENDERED". Finally, this
        hook also sets the `actor_input` property to the first argument that was
        passed with the triggering event.

        :param event_data: The event data object provided by the state machine
        """
        logger.debug(
            "starting transition for session {session_id}, "
            "to state {state_id} with event {event_id}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
        )

        transition_type = self._determine_transition_type(event_data)
        event_data.machine.model.transition_type = transition_type
        event_data.machine.model.actor = transition_type.target.as_actor
        logger.debug(
            "determined transition type for session {session_id}, "
            "to state {state_id} with event {event_id} "
            "to be {transition_type} with actor {actor}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
            transition_type=transition_type,
            actor=event_data.machine.model.actor,
        )

        dialogue_persistence = (
            _DIALOGUE_PERSISTENCE_MAP[transition_type.source][transition_type.target]
        )
        event_data.machine.model.dialogue_persistence = dialogue_persistence
        logger.debug(
            "determined dialogue persistence for session {session_id}, "
            "to state {state_id} with event {event_id} "
            "to be {dialogue_persistence}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
            dialogue_persistence=dialogue_persistence,
        )

        actor_input = (
            event_data.args[0]
            if event_data.args is not None and len(event_data.args) > 0
            else None
        )
        logger.debug("set actor input to {actor_input}", actor_input=actor_input)
        logger.info(
            "set actor input to string of size {actor_input_size}",
            actor_input_size=len(actor_input) if actor_input is not None else None,
        )
        event_data.machine.model.actor_input = actor_input

    def on_transition(self, event_data: EventData):
        """
        this hook is used to trigger the Celery task, if the target state is
        an "invoker" state.

        :param event_data: The event data object provided by the state machine
        """
        logger.debug(
            "on transition for session {session_id}, "
            "to state {state_id} with event {event_id}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
        )
        if event_data.machine.model.transition_type.target != StateType.INVOKER:
            logger.debug(
                "no need to enqueue task for session {session_id}, "
                "to state {state_id} with event {event_id}",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
            )
            return

        logger.info(
            "enqueueing task for session {session_id}, "
            "to state {state_id} with event {event_id}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
        )
        self._enqueue_task(
            event_data.machine,
            event_data.machine.model,
            event_data.target,
        )

    def after_transition(self, event_data: EventData):
        logger.debug(
            "after transition for session {session_id}, "
            "to state {state_id} with event {event_id} "
            "and dialogue persistence: {dialogue_persistence}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
            dialogue_persistence=event_data.machine.model.dialogue_persistence,
        )

        if event_data.machine.model.dialogue_persistence == DialoguePersistence.NONE:
            logger.info(
                "not recording dialogue for session {session_id}, "
                "to state {state_id} with event {event_id}",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
            )
            return

        if event_data.machine.model.dialogue_persistence == DialoguePersistence.RENDERED:
            logger.info(
                "rendering template for session {session_id}, "
                "to state {state_id} with event {event_id}",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
            )
            target_template_path = event_data.machine.model.get_template_for_state(
                event_data.machine.current_state,
            )
            actor_input = self.celery_manager.genie_environment.render_template(
                template_path=target_template_path,
                data_context=event_data.machine.render_data,
            )
            logger.debug(
                "recording rendered output for session {session_id}, "
                "to state {state_id} with event {event_id} "
                "as: '{actor_input}'",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
                actor_input=(
                    f"{actor_input[:50]}..."
                    if len(actor_input) > 50 else actor_input
                ),
            )
            event_data.machine.model.actor_input = actor_input
        else:
            logger.debug(
                "recording raw output for session {session_id}, "
                "to state {state_id} with event {event_id} "
                "as: '{actor_input}'",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
                actor_input=(
                    f"{event_data.machine.model.actor_input[:50]}..."
                    if len(event_data.machine.model.actor_input) > 50
                    else event_data.machine.model.actor_input
                ),
            )
            logger.info(
                "adding raw actor input to dialogue for session {session_id}, "
                "to state {state_id} with event {event_id}",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
            )

        event_data.machine.model.record_dialogue_element()
