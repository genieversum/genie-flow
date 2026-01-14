import hashlib
import typing

from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from genie_flow.genie import GenieModel
from genie_flow.model.dialogue import StateType, DialoguePersistence
from genie_flow.model.template import CompositeTemplateType

if typing.TYPE_CHECKING:
    from genie_flow.celery import CeleryManager


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
        This hook determines how the transition will be started. Model properties managed:

        * actor - set to "user" if the previous state was a RENDERER, else "assistant"
        * actor_input - set to the event's data first element
        * source_type - the StateType of the source state
        * target_type - the StateType of the target state

        Also persists a DialogueElement into the model's dialogue list, based on
        the persistence logic.

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

        source_type, target_type = self._determine_transition_type(event_data)

        model: GenieModel = event_data.machine.model
        model.source_type = source_type
        model.target_type = target_type
        model.actor = "user" if source_type.RENDERER else "assistant"
        model.actor_input = actor_input

        persistence = DialoguePersistence.from_event(event_data, target_type)
        content = persistence.render_user(
            event_data.event.name,
            actor_input,
        )
        if content:
            logger.debug(
                "Adding input '{user_content}' from '{actor}', to dialogue for session {session_id}, "
                "from state '{from_state_name}' ({from_state_id}) "
                "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
                session_id=model.session_id,
                from_state_name=event_data.source.name,
                from_state_id=event_data.source.id,
                to_state_name=event_data.target.name,
                to_state_id=event_data.target.id,
                event_id=event_data.event.name,
                actor=model.actor,
                user_content=content[50:],
            )

            event_data.machine.model.add_dialogue_element(
                actor=model.actor,
                event=event_data.event.name,
                actor_text=content,
            )

    def after_transition(self, event_data: EventData):
        """
        This hook determines how the transition will be finished.
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

        persistence = DialoguePersistence.from_event(
            event_data,
            event_data.machine.model.target_state,
        )

        def render_template():
            target_template_path = event_data.machine.get_template_for_state(
                event_data.machine.current_state,
            )
            return self.celery_manager.genie_environment.render_template(
                template_path=target_template_path,
                data_context=event_data.machine.model.render_data,
            )

        content = persistence.render_assistant(
            event_data.event.name,
            event_data.args[0] if event_data.args else None,
            render_template,
        )

        if content:
            logger.debug(
                "recording content '{content}' for session {session_id}, "
                "from state '{from_state_name}' ({from_state_id}) "
                "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
                session_id=event_data.machine.model.session_id,
                from_state_name=event_data.source.name,
                from_state_id=event_data.source.id,
                to_state_name=event_data.target.name,
                to_state_id=event_data.target.id,
                event_id=event_data.event.name,
                content=(
                    f"{content[:50]}..."
                    if content is not None and len(content) > 50 else content
                ),
            )

            event_data.machine.model.add_dialogue_element(
                actor="assistant",
                event=event_data.event.name,
                actor_text=content,
            )
