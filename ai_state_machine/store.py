import builtins
import importlib
import logging
from types import ModuleType
from typing import Any, Type

from pydantic_redis import Model, Store


def get_fully_qualified_name_from_class(o: Any) -> str:
    """
    Creates the fully qualified name of the class of the given object.
    :param o: The object of which to obtain the FQN form
    :return: The fully qualified name of the class of the given object
    """
    cls = o.__class__
    module = cls.__module__
    if module == "builtins":
        return cls.__qualname__  # we do builtins without the module path
    return module + "." + cls.__qualname__


def get_class_from_fully_qualified_name(class_path):
    """
    Get the actual class of the given fully qualified name.
    :param class_path: The FQN of the class to retrieve
    :return: The actual class that is referred to by the given FQN
    """
    try:
        module_name, class_name = class_path.rsplit(".", 1)
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
        module_name, class_name = class_fqn.rsplit(".", 1)
        return importlib.import_module(module_name)
    except ValueError:
        logging.error(f"Failed to get module from fqn {class_fqn}")
        raise


class StoreManager:

    def __init__(
        self,
        store: Store,
    ):
        self.store = store

    def register_model(self, model_class: Type[Model]):
        """
        Register a model class, so it can be stored in the object store.
        :param model_class: the class of the model that needs to be registered
        """
        self.store.register_model(model_class)

    def store_model(self, model: Model) -> None:
        """
        Stores the given model into the configured Redis store.
        :param model: The object to store
        """
        model.__class__.insert(model)

    def retrieve_model(self, class_fqn: str, session_id: str = None) -> Model:
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
