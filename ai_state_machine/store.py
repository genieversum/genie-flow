import builtins
import importlib
import json

from redis import Redis

from ai_state_machine.genie_model import GenieModel

_DB = Redis(host='localhost', port=6379, db=1)


def full_class_ame(o):
    klass = o.__class__
    module = klass.__module__
    if module == 'builtins':
        return klass.__qualname__ # avoid outputs like 'builtins.str'
    return module + '.' + klass.__qualname__


def get_class_from_fully_qualified_name(class_path):
    if class_path.contains("."):
        module_name, class_name = class_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
    else:
        class_name = class_path
        module = builtins

    return getattr(module, class_name)


def store_state_model(key: str, model: GenieModel):
    json_string = model.model_dump_json()
    class_name = full_class_ame(model.__class__)
    _DB.set(key, f"{class_name}|{json_string}")


def retrieve_state_model(key: str) -> GenieModel:
    value = _DB.get(key)
    class_path, json_string = value.split("|")

    cls = get_class_from_fully_qualified_name(class_path)
    if not issubclass(cls, GenieModel):
        raise ValueError(f"Class {class_path} is not a subclass of GenieModel")

    return cls(**json.loads(json_string))
