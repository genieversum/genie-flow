import uuid

from statemachine.exceptions import TransitionNotAllowed

from ai_state_machine.genie_state_machine import GenieModel
from ai_state_machine.model import EventInput, AIResponse, AIStatusResponse
from ai_state_machine.store import get_lock_for_session


def create_new_session(model_class: type[GenieModel]) -> AIResponse:
    session_id = str(str(uuid.uuid4()))

    model = model_class(session_id=session_id)
    state_machine = model.state_machine_class(model=model, new_session=True)
    model.__class__.insert(model)

    response = model.current_response.actor_text

    return AIResponse(
        session_id=session_id,
        response=response,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


def _handle_poll(event: EventInput, model: GenieModel) -> AIResponse:
    if model.running_task_id is not None:
        return AIResponse(session_id=event.session_id, next_actions=['poll'])

    state_machine = model.create_state_machine()
    return AIResponse(
        session_id=event.session_id,
        response=state_machine.model.current_response.actor_text,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


def _handle_event(event: EventInput, model: GenieModel) -> AIResponse:
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


def process_event(event: EventInput, cls: type[GenieModel]) -> AIResponse:
    with get_lock_for_session(event.session_id):
        models = cls.select(ids=[event.session_id])
        assert len(models) == 1
        model = models[0]

        if event.event == "poll":
            return _handle_poll(event, model)

        try:
            return _handle_event(event, model)
        except TransitionNotAllowed as e:
            return AIResponse(
                session_id=event.session_id,
                error=str(e),
            )


def get_task_state(session_id: str, model_class: type[GenieModel]) -> AIStatusResponse:
    with get_lock_for_session(session_id):
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


def get_model(session_id: str, model_class: type[GenieModel]) -> GenieModel:
    with get_lock_for_session(session_id):
        models = model_class.select(ids=[session_id])
        assert len(models) == 1
        model = models[0]

        return model
