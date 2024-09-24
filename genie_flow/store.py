from typing import Type

from pydantic_redis import Model, Store

from genie_flow.genie import GenieModel, GenieTaskProgress
from genie_flow.model.dialogue import DialogueElement
from genie_flow.utils import get_class_from_fully_qualified_name


class StoreManager:

    def __init__(
        self,
        store: Store,
    ):
        self.store = store
        self.register_model(DialogueElement)
        self.register_model(GenieTaskProgress)
        self.register_model(GenieModel)

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
