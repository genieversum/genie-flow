import uuid

from fastapi import FastAPI

# from ai_state_machine.model import DialogueElement
# from ai_state_machine.store import STORE
from example_claims.claims import ClaimsModel, ClaimsMachine
from example_claims.model import AIResponse, EventInput, AIStatusResponse

app = FastAPI()

# STORE.register_model(ClaimsModel)
# STORE.register_model(DialogueElement)


@app.get("/")
def get_root():
    return "Hello World!"


@app.get("/v1/start_session/")
def start_session():
    session_id = str(uuid.uuid4().hex)

    model = ClaimsModel(session_id=session_id)
    state_machine = ClaimsMachine(model=model, new_session=True)
    ClaimsModel.insert(model)

    response = model.current_response.actor_text

    return AIResponse(
        session_id=session_id,
        response=response,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


@app.post("/v1/event/")
def start_event(event: EventInput):
    models = ClaimsModel.select(ids=[event.session_id])
    assert len(models) == 1
    model = models[0]

    if event.event == "poll":
        if model.running_task_id is not None:
            return AIResponse(session_id=event.session_id, next_actions=['poll'])

        state_machine = model.create_state_machine()
        return AIResponse(
            session_id=event.session_id,
            response=state_machine.model.current_response.actor_text,
            next_actions=state_machine.current_state.transitions.unique_events,
        )

    state_machine = model.create_state_machine()
    state_machine.send(event.event, event.event_input)
    ClaimsModel.insert(model)

    if model.running_task_id is not None:
        return AIResponse(session_id=event.session_id, next_actions=['poll'])
    return AIResponse(
        session_id=event.session_id,
        response=state_machine.model.current_response.actor_text,
        next_actions=state_machine.current_state.transitions.unique_events,
    )


@app.get("/v1/task_state/{session_id}")
def get_task_state(session_id: str):
    models = ClaimsModel.select(ids=[session_id])
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


@app.get("/v1/model/{session_id}")
def get_model(session_id: str):
    models = ClaimsModel.select(ids=[session_id])
    assert len(models) == 1
    model = models[0]

    return model
