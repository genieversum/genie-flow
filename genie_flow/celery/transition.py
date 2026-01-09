import hashlib
import typing

from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from genie_flow.genie import StateType, DialoguePersistence
from genie_flow.model.template import CompositeTemplateType

if typing.TYPE_CHECKING:
    from genie_flow.celery import CeleryManager


def _determine_persistence_flags(event_data: EventData) -> DialoguePersistence:
    if event_data.machine.model.dialogue_persistence:
        return event_data.machine.model.dialogue_persistence

    default = (
        DialoguePersistence.USER_EVENT
        | DialoguePersistence.ASSISTANT_EVENT
    )
    return event_data.machine.persistence.get(
        event_data.event.name,
        default
    )


class TransitionManager:

    def __init__(self, celery_manager: "CeleryManager"):
        self.celery_manager = celery_manager

    def _determine_transition_type(self, event_data: EventData) -> tuple[StateType, StateType]:
        def determine(state: State) -> StateType:
            state_template: CompositeTemplateType = event_data.machine.get_template_for_state(state)
            return (
                StateType.INVOKER
                if self.celery_manager.genie_environment.has_invoker(state_template)
                else StateType.RENDERER
            )

        return determine(event_data.source), determine(event_data.target)

    def before_transition(self, event_data: EventData):
        """
        This hook determines how the transition will be started.

        The logic comes down to the following.

        `before_transition()`:
        * before we leave, we set actor_input to RAW
        * when we leave a RENDERED state, the actor is "user" and we persist RAW

        `after_transition()`:
        * when we enter a RENDERED state, the actor is "assistant" and we set actor_input
          to, and persist RENDERED

        * in all other cases we do nothing

        :param event_data: The event data object provided by the state machine
        """
        logger.debug(
            "starting transition for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=event_data.machine.model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_data.event.name,
        )

        actor_input : str = (
            event_data.args[0]
            if event_data.args is not None and len(event_data.args) > 0
            else None
        )
        logger.debug(
            "set actor input to '{actor_input}' for session {session_id}, ",
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=event_data.machine.model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_data.event.name,
            actor_input=actor_input[50:] if actor_input is not None else "None",
        )
        logger.info(
            "set actor input to string of md5 hash {actor_input_hash} "
            "for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=event_data.machine.model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_data.event.name,
            actor_input_hash=(
                hashlib.md5(actor_input.encode("utf-8")).hexdigest()
                if actor_input is not None
                else None
            ),
        )
        event_data.machine.model.actor_input = actor_input

        source_type, target_type = self._determine_transition_type(event_data)
        event_data.machine.model.source_type = source_type
        event_data.machine.model.target_type = target_type

        if source_type != StateType.RENDERER:
            return

        persistence = _determine_persistence_flags(event_data)

        user_event = (
            event_data.event.name
            if persistence & DialoguePersistence.USER_EVENT
            else None
        )
        user_content = (
            actor_input
            if persistence & DialoguePersistence.USER_CONTENT
            else None
        )
        if not (user_event or user_content):
            return

        logger.debug(
            "Adding user input '{actor_input}' to dialogue for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=event_data.machine.model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_data.event.name,
            actor_input=user_content[50:] if user_content is not None else "None",
        )

        event_data.machine.model.actor = "user"
        event_data.machine.model.add_dialogue_element(
            actor="user",
            event=user_event,
            actor_text=user_content,
        )

    def after_transition(self, event_data: EventData):
        """
        This hook determines how the transition will be finished.

        The logic comes down to the following.

        `before_transition()`:
        * before we leave, we set actor_input to RAW
        * when we leave a RENDERED state, the actor is "user" and we persist RAW

        `after_transition()`:
        * when we enter a RENDERED state, the actor is "assistant" and we set actor_input
          to, and persist RENDERED

        * in all other cases we do nothing

        :param event_data: The event data object provided by the state machine
        """
        logger.debug(
            "after transition for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=event_data.machine.model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_data.event.name,
        )

        if event_data.machine.model.target_type != StateType.RENDERER:
            return

        persistence = _determine_persistence_flags(event_data)
        assistant_event = (
            event_data.event.name
            if persistence & DialoguePersistence.ASSISTANT_EVENT
            else None
        )
        assistant_raw = (
            event_data.args[0]
            if persistence & DialoguePersistence.ASSISTANT_RAW
            else None
        )
        assistant_rendered = None
        if persistence & DialoguePersistence.ASSISTANT_RENDERED:
            target_template_path = event_data.machine.get_template_for_state(
                event_data.machine.current_state,
            )
            assistant_rendered = self.celery_manager.genie_environment.render_template(
                template_path=target_template_path,
                data_context=event_data.machine.model.render_data,
            )
        actor_input = "\n".join(
            i
            for i in [assistant_raw, assistant_rendered]
            if i is not None
        )

        logger.debug(
            "recording actor input '{actor_input}' for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=event_data.machine.model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_data.event.name,
            actor_input=(
                f"{actor_input[:50]}..."
                if actor_input is not None and len(actor_input) > 50 else actor_input
            ),
        )
        event_data.machine.model.actor = "assistant"
        event_data.machine.model.actor_input = actor_input
        event_data.machine.model.add_dialogue_element(
            actor="assistant",
            event=assistant_event,
            actor_text=actor_input,
        )
