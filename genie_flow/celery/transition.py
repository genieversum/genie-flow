import hashlib
import typing

from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from genie_flow.genie import StateType, DialoguePersistence
from genie_flow.model.template import CompositeTemplateType

if typing.TYPE_CHECKING:
    from genie_flow.celery import CeleryManager


_DIALOGUE_PERSISTENCE_MAP: dict[StateType, dict[StateType, DialoguePersistence]] = {
    StateType.USER: {
        StateType.USER: DialoguePersistence.RENDERED,
        StateType.INVOKER: DialoguePersistence.RAW,
    },
    StateType.INVOKER: {
        StateType.USER: DialoguePersistence.RENDERED,
        StateType.INVOKER: DialoguePersistence.NONE,
    }
}

class TransitionManager:

    def __init__(self, celery_manager: "CeleryManager"):
        self.celery_manager = celery_manager

    def _determine_transition_type(self, event_data: EventData) -> tuple[StateType, StateType]:
        def determine(state: State) -> StateType:
            state_template: CompositeTemplateType = event_data.machine.get_template_for_state(state)
            return (
                StateType.INVOKER
                if self.celery_manager.genie_environment.has_invoker(state_template)
                else StateType.USER
            )

        return determine(event_data.source), determine(event_data.target)

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

        source_type, target_type = self._determine_transition_type(event_data)
        event_data.machine.model.source_type = source_type
        event_data.machine.model.target_type = target_type
        event_data.machine.model.actor = source_type.as_actor
        logger.debug(
            "determined transition type for session {session_id}, "
            "to state {state_id} with event {event_id} "
            "to be from {source_type} to {target_type}, with actor {actor}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
            source_type=source_type.name,
            target_type=target_type.name,
            actor=event_data.machine.model.actor,
        )

        dialogue_persistence = (
            _DIALOGUE_PERSISTENCE_MAP[source_type][target_type]
        )
        event_data.machine.model.dialogue_persistence = dialogue_persistence
        logger.debug(
            "determined dialogue persistence for session {session_id}, "
            "to state {state_id} with event {event_id} "
            "to be {dialogue_persistence}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
            dialogue_persistence=dialogue_persistence.name,
        )

        actor_input : str = (
            event_data.args[0]
            if event_data.args is not None and len(event_data.args) > 0
            else None
        )
        logger.debug("set actor input to '{actor_input}'", actor_input=actor_input)
        logger.info(
            "set actor input to string of md5 hash {actor_input_hash}",
            actor_input_hash=(
                hashlib.md5(actor_input.encode("utf-8")).hexdigest()
                if actor_input is not None
                else None
            ),
        )
        event_data.machine.model.actor_input = actor_input

    def after_transition(self, event_data: EventData):
        logger.debug(
            "after transition for session {session_id}, "
            "to state {state_id} with event {event_id} "
            "and dialogue persistence: {dialogue_persistence}",
            session_id=event_data.machine.model.session_id,
            state_id=event_data.target.id,
            event_id=event_data.event,
            dialogue_persistence=event_data.machine.model.dialogue_persistence.name,
        )

        if event_data.machine.model.target_type == StateType.INVOKER:
            logger.info(
                "enqueueing task for session {session_id}, "
                "to state {state_id} with event {event_id}",
                session_id=event_data.machine.model.session_id,
                state_id=event_data.target.id,
                event_id=event_data.event,
            )
            self.celery_manager.enqueue_task(
                event_data.machine,
                event_data.machine.model,
                event_data.target,
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
            target_template_path = event_data.machine.get_template_for_state(
                event_data.machine.current_state,
            )
            actor_input = self.celery_manager.genie_environment.render_template(
                template_path=target_template_path,
                data_context=event_data.machine.model.render_data,
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
