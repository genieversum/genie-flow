from typing import Type, Optional, overload

import redis_lock
from redis import Redis
from snappy import snappy

from genie_flow.genie import GenieModel
from genie_flow.utils import get_class_from_fully_qualified_name


class SessionLockManager:

    class ModelContextManager:

        def __init__(
                self,
                lock_manager: "SessionLockManager",
                session_id: str,
                model_class: Type[GenieModel]
        ):
            """
            A Context Manager for obtaining a locked `GenieModel`. This context manager obtains
            a lock for a particular session, then retrieves the GenieModel from store. Upon the
            exit of the context, that GenieModel is stored back into store and the lock is released.
            """
            self.lock_manager = lock_manager
            self.model_class = model_class
            self.session_id = session_id
            self.lock = lock_manager._create_lock_for_session(session_id)
            self.model: Optional[GenieModel] = None

        def __enter__(self) -> GenieModel:
            self.lock.acquire()
            self.model = self.lock_manager.get_model(self.session_id, self.model_class)
            return self.model

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.lock_manager.store_model(self.model)
            self.lock.release()

    def __init__(
        self,
        redis_object_store: Redis,
        redis_lock_store: Redis,
        lock_expiration_seconds: int,
        compression: bool,
        application_prefix: str,
    ):
        """
        The `SessionLockManager` manages the session lock as well as the retrieval and persisting
        of model objects. When changes are (expected to be) made to the model of a particular
        session, this manager deals with locking multithreaded access to it when it gets retrieves
        from Store, and before it gets written back to it.
        :param redis_object_store: The Redis object store
        :param redis_lock_store: The Redis lock store
        :param lock_expiration_seconds: The expiration time of the lock in seconds
        :param compression: Whether or not to compress the model when persisting
        :param application_prefix: The application prefix used to create the key for an object
        """
        self.redis_object_store = redis_object_store
        self.redis_lock_store = redis_lock_store
        self.lock_expiration_seconds = lock_expiration_seconds
        self.compression = compression
        self.application_prefix = application_prefix

    def _create_lock_for_session(self, session_id: str) -> redis_lock.Lock:
        """
        Retrieve the lock for the object for the given `session_id`. This ensures that only
        one process will have access to the model and potentially make changes to it.
        This lock can function as a context manager. See the documentation of `redis_lock.Lock`
        :param session_id: The session id that the object in question belongs to
        """
        lock = redis_lock.Lock(
            self.redis_lock_store,
            name=f"lock-{session_id}",
            expire=self.lock_expiration_seconds,
            auto_renewal=True,
        )
        return lock

    @overload
    def _create_key(self, model: type[GenieModel], session_id: str) -> str: ...

    @overload
    def _create_key(self, model: GenieModel, session_id: Optional[str]=None) -> str:...

    def _create_key(
            self,
            model: GenieModel | type[GenieModel],
            session_id: Optional[str]=None
    ) -> str:
        if isinstance(model, GenieModel):
            return f"{self.application_prefix}:{model.__class__.__name__}:{model.session_id}"
        return f"{self.application_prefix}:{model.__name__}:{session_id}"

    def _serialize(self, model: GenieModel) -> bytes:
        model_dump = model.model_dump_json(exclude_defaults=True, exclude_unset=True)
        if self.compression:
            return snappy.compress(model_dump, encoding="utf-8")
        return model_dump.encode("utf-8")

    def _deserialize(self, payload: bytes, model_cls: str | Type[GenieModel]) -> GenieModel:
        if isinstance(model_cls, str):
            model_cls: GenieModel = get_class_from_fully_qualified_name(model_cls)

        if self.compression:
            model_json = snappy.decompress(payload, decoding="utf-8")
        else:
            model_json = payload.decode("utf-8")
        return model_cls.model_validate_json(model_json)

    def get_model(self, session_id: str, model_class: Type[GenieModel]) -> GenieModel:
        """
        Retrieve the GenieModel for the object for the given `session_id`. This retrieval is
        done inside a locked context, so no writing of the GenieModel can happen when this
        retrieval is done.

        :param session_id: The session id that the object in question belongs to
        :param model_class: The GenieModel class to retrieve
        :return: The GenieModel object for the given `session_id`
        """
        with self._create_lock_for_session(session_id):
            model_key = self._create_key(model_class, session_id)
            payload = self.redis_object_store.get(model_key)
            if payload is None:
                raise KeyError(f"No model with id {session_id}")
            return self._deserialize(payload, model_class)

    def store_model(self, model: GenieModel):
        """
        Store a model into the object store.

        :param model: the object to store
        """
        model_key = self._create_key(model)
        self.redis_object_store.set(model_key, self._serialize(model))

    def get_locked_model(
            self,
            session_id: str,
            model_class: str | Type[GenieModel],
    ) -> ModelContextManager:
        if isinstance(model_class, str):
            model_class = get_class_from_fully_qualified_name(model_class)
        return SessionLockManager.ModelContextManager(self, session_id, model_class)
