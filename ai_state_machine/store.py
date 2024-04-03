import base64
import pickle

from redis import Redis
from statemachine import StateMachine

from ai_state_machine.genie_state_machine import GenieStateMachine

_DB = Redis(host='localhost', port=6379, db=1)


def store_state_machine(state_machine: GenieStateMachine):
    key = state_machine.model.session_id
    blob = base64.b64encode(pickle.dumps(state_machine))
    _DB.set(key, blob)


def retrieve_state_machine(session_id: str) -> GenieStateMachine:
    blob = _DB.get(session_id)
    state_machine = pickle.loads(base64.b64decode(blob))
    return state_machine
