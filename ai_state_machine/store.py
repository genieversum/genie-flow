import json

from redis import Redis

from ai_state_machine.genie_model import GenieModel

_DB = Redis(host='localhost', port=6379, db=1)


def store_state_model(key: str, model: GenieModel):
    _DB.set(key, model.model_dump_json())


def retrieve_state_model(key: str, cls: type[GenieModel]) -> GenieModel:
    json_string = _DB.get(key)
    return cls(**json.loads(json_string))
