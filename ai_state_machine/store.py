import builtins
import importlib
import logging
from types import ModuleType
from typing import Any

import redis_lock
from dependency_injector.wiring import inject, Provide
from pydantic_redis import Model, Store, RedisConfig
from redis import Redis

from ai_state_machine.containers import GenieFlowContainer

# STORE = Store(
#     name="genie",
#     redis_config=RedisConfig(db=1),
#     life_span_in_seconds=86400,
# )


def get_fully_qualified_name_from_class(o: Any) -> str:
    """
    Creates the fully qualified name of the class of the given object.
    :param o: The object of which to obtain the FQN form
    :return: The fully qualified name of the class of the given object
    """
    cls = o.__class__
    module = cls.__module__
    if module == 'builtins':
        return cls.__qualname__  # we do builtins without the module path
    return module + '.' + cls.__qualname__


def get_class_from_fully_qualified_name(class_path):
    """
    Get the actual class of the given fully qualified name.
    :param class_path: The FQN of the class to retrieve
    :return: The actual class that is referred to by the given FQN
    """
    try:
        module_name, class_name = class_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
    except ValueError:
        class_name = class_path
        module = builtins

    return getattr(module, class_name)


def get_module_from_fully_qualified_name(class_fqn: str) -> ModuleType:
    """
    Get the module of the given fully qualified name of a class.
    :param class_fqn: The FQN of a class to retrieve the module from
    :return: The module that the class of the given FQN is in
    """
    try:
        module_name, class_name = class_fqn.rsplit('.', 1)
        return importlib.import_module(module_name)
    except ValueError:
        logging.error(f"Failed to get module from fqn {class_fqn}")
        raise


def store_model(model: Model) -> None:
    """
    Stores the given model into the configured Redis store.
    :param model: The object to store
    """
    model.__class__.insert(model)


def retrieve_model(class_fqn: str, session_id: str = None) -> Model:
    """
    Retrieves the `GenieModel` that the given FQN refers to, from the configured Redis store
    :param class_fqn: The FQN of the class to retrieve the model from
    :param session_id: The id of the session that the object to retrieve belongs to
    :raises ValueError: If there is zero or more than one instances with the given session_id
    """
    cls = get_class_from_fully_qualified_name(class_fqn)
    models = cls.select(ids=[session_id])
    assert len(models) == 1
    return models[0]


@inject
def get_lock_for_session(
        session_id: str,
        redis_store: Redis = Provide[GenieFlowContainer.redis_lock_store],
        lock_expiration: int = Provide[GenieFlowContainer.config.lock_expiration],
) -> redis_lock.Lock:
    """
    Retrieve the lock for the object for the given `session_id`. This ensures that only
    one process will have access to the model and potentially make changes to it.
    This lock can function as a context manager. See the documentation of `redis_lock.Lock`
    :param session_id: The session id that the object in question belongs to
    :param redis_store: The Redis client that should be used to create the lock in
    :param lock_expiration: The expiration time of the lock in seconds.
    """
    lock = redis_lock.Lock(
        redis_store,
        name=f"lock-{session_id}",
        expire=lock_expiration,
        auto_renewal=True,
    )
    return lock
