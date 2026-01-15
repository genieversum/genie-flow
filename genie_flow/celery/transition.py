import hashlib
import typing

from loguru import logger
from statemachine import State
from statemachine.event_data import EventData

from genie_flow.genie import GenieModel, GenieStateMachine
from genie_flow.model.dialogue import StateType, DialoguePersistence
from genie_flow.model.template import CompositeTemplateType

if typing.TYPE_CHECKING:
    from genie_flow.celery import CeleryManager


_DEFAULT_PERSISTENCE = (
    DialoguePersistence.SOURCE_EVENT
    | DialoguePersistence.TARGET_RENDERED
)


def _determine_persistence(
        machine: GenieStateMachine,
        model: GenieModel,
        event_name: str,
) -> DialoguePersistence:
    """
    Determine what persistence flag to use.
    1. If the model has `dialogue_persistence` set, this trumps any other logic and that
       value is returned.
    2. If the target state type is not RENDERED, then returns NONE to persist.
    3. For anything else, follow the default that is set for the machine, based on the
       name of the event - or default to just recording the event

    :param machine: the `GenieStateMachine` that holds the defaults for different events
    :param model: the `GenieModel` that may hold a run-time override
    :param event_name: the name of the event that triggered the transition
    :return: the determined `DialoguePersistence` flags
    """
    if model.dialogue_persistence is not None:
        return model.dialogue_persistence

    return machine.persistence.get(event_name, _DEFAULT_PERSISTENCE)


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

        assert (
            isinstance(event_data.machine, GenieStateMachine),
            "State Machine is not a Genie state machine"
        )

        machine: GenieStateMachine = event_data.machine
        model: GenieModel = machine.model
        event_name: str = event_data.event.name

        model.source_type = source_type
        model.target_type = target_type
        model.actor = "user" if source_type.RENDERER else "assistant"
        model.actor_input = actor_input

        persistence = _determine_persistence(machine, model, event_name)
        dialogue_element = persistence.render_user(event_name, actor_input)
        if dialogue_element is None:
            return

        logger.debug(
            "Adding actor text '{actor_text}' from '{actor}', "
            "to dialogue for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}), "
            "with event '{event_id}'",
            session_id=model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_name,
            actor=model.actor,
            actor_text=(
                f"{dialogue_element.actor_text[50:]}..."
                if dialogue_element.actor_text is not None and len(dialogue_element.actor_text) > 50
                else dialogue_element.actor_text
            )
        )
        model.dialogue.append(dialogue_element)

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

        if not isinstance(event_data.machine, GenieStateMachine):
            raise ValueError("State Machine is not a Genie state machine")

        machine: GenieStateMachine = event_data.machine
        model: GenieModel = machine.model
        event_name: str = event_data.event.name

        if model.target_type != StateType.RENDERER:
            return

        persistence = _determine_persistence(machine, model, event_name)
        if not persistence & DialoguePersistence.TARGET:
            return

        def render_template():
            # we are _after_ the transition, so the current state is the target state
            target_template_path = machine.get_template_for_state(machine.current_state)
            return self.celery_manager.genie_environment.render_template(
                template_path=target_template_path,
                data_context=model.render_data,
            )

        dialogue_element = persistence.render_assistant(
            event_name,
            event_data.args[0] if event_data.args else None,
            render_template,
        )
        logger.debug(
            "recording actor text '{actor_text}' for session {session_id}, "
            "from state '{from_state_name}' ({from_state_id}) "
            "to state '{to_state_name}' ({to_state_id}) with event '{event_id}'",
            session_id=model.session_id,
            from_state_name=event_data.source.name,
            from_state_id=event_data.source.id,
            to_state_name=event_data.target.name,
            to_state_id=event_data.target.id,
            event_id=event_name,
            actor_text=(
                f"{dialogue_element.actor_text[:50]}..."
                if dialogue_element.actor_text is not None and len(dialogue_element.actor_text) > 50
                else dialogue_element.actor_text
            ),
        )
        model.dialogue.append(dialogue_element)
