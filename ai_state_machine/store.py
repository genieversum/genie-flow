import builtins
import importlib
import logging
from types import ModuleType
from typing import Any

import redis_lock
from pydantic_redis import Model, Store, RedisConfig

STORE = Store(
    name="genie",
    redis_config=RedisConfig(db=1),
    life_span_in_seconds=86400,
)


def get_fully_qualified_name_from_class(o: Any) -> str:
    cls = o.__class__
    module = cls.__module__
    if module == 'builtins':
        return cls.__qualname__  # we do builtins without the module path
    return module + '.' + cls.__qualname__


def get_class_from_fully_qualified_name(class_path):
    try:
        module_name, class_name = class_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
    except ValueError:
        class_name = class_path
        module = builtins

    return getattr(module, class_name)


def get_module_from_fully_qualified_name(class_fqn: str) -> ModuleType:
    try:
        module_name, class_name = class_fqn.rsplit('.', 1)
        return importlib.import_module(module_name)
    except ValueError:
        logging.error(f"Failed to get module from fqn {class_fqn}")
        raise


def store_model(model: Any) -> None:
    model.__class__.insert(model)


def retrieve_model(class_fqn: str, session_id: str = None) -> Model:
    cls = get_class_from_fully_qualified_name(class_fqn)
    models = cls.select(ids=[session_id])
    assert len(models) == 1
    return models[0]


def get_lock_for_session(session_id: str) -> redis_lock.Lock:
    lock = redis_lock.Lock(
        STORE.redis_store,
        name=f"lock-{session_id}",
        expire=60,
        auto_renewal=True,
    )
    return lock
