from typing import Type, Optional, overload, Literal

import redis_lock
from loguru import logger
from redis import Redis
from snappy import snappy

from genie_flow.genie import GenieModel
from genie_flow.utils import get_class_from_fully_qualified_name


StoreType = Literal["object", "lock", "progress"]


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
        redis_progress_store: Redis,
        object_expiration_seconds: int,
        lock_expiration_seconds: int,
        progress_expiration_seconds: int,
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
        :param redis_progress_store: The Redis progress store
        :param object_expiration_seconds: The expiration time for objects in seconds
        :param lock_expiration_seconds: The expiration time of the lock in seconds
        :param progress_expiration_seconds: The expiration time of the progress object in seconds
        :param compression: Whether or not to compress the model when persisting
        :param application_prefix: The application prefix used to create the key for an object
        """
        self.redis_object_store = redis_object_store
        self.redis_lock_store = redis_lock_store
        self.redis_progress_store = redis_progress_store
        self.object_expiration_seconds = object_expiration_seconds
        self.lock_expiration_seconds = lock_expiration_seconds
        self.progress_expiration_seconds = progress_expiration_seconds
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
    def _create_key(
            self,
            store: StoreType,
            model: None,
            session_id: str
    ) -> str: ...

    @overload
    def _create_key(
            self,
            store: StoreType,
            model: type[GenieModel],
            session_id: str
    ) -> str: ...

    @overload
    def _create_key(
            self,
            store: StoreType,
            model: GenieModel,
            session_id: Optional[str]=None
    ) -> str:...

    def _create_key(
            self,
            store: StoreType,
            model: GenieModel | type[GenieModel] | None,
            session_id: Optional[str]=None
    ) -> str:
        if model is None:
            return f"{self.application_prefix}:{store}::{session_id}"

        if isinstance(model, GenieModel):
            return f"{self.application_prefix}:{store}:{model.__class__.__name__}:{model.session_id}"

        return f"{self.application_prefix}:{store}:{model.__name__}:{session_id}"

    def _serialize(self, model: GenieModel) -> bytes:
        """
        Creates a serialization of the given model object. Serialization results in a
        bytes object, containing the schema version number, a compression indicator and
        the serialized version of the model object. All seperated by a ':' character.

        :param model: the GenieModel to serialize
        :return: a bytes with the serialized version of the model object
        """
        model_dump = model.model_dump_json(exclude_defaults=True, exclude_unset=True)
        if self.compression:
            payload = snappy.compress(model_dump, encoding="utf-8")
        else:
            payload = model_dump.encode("utf-8")
        compression = b"1" if self.compression else b"0"

        return b":".join([str(model.schema_version).encode("utf-8"), compression, payload])

    def _deserialize(self, payload: bytes, model_cls: str | Type[GenieModel]) -> GenieModel:
        if isinstance(model_cls, str):
            model_cls: GenieModel = get_class_from_fully_qualified_name(model_cls)

        persisted_version, compression, payload = payload.split(b":", maxsplit=3)
        if int(persisted_version) != model_cls.schema_version:
            logger.error(
                "Trying to deserialize a model with schema version {persisted_version} "
                "into a model with schema version {current_version} "
                "for model class {model_class}",
                persisted_version=persisted_version,
                model_version=model_cls.schema_version,
                model_class=model_cls.__name__,
            )
            raise ValueError(
                f"Schema mis-match when deserializing a {model_cls.__name__} model"
            )

        if compression == b"1":
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
            model_key = self._create_key("object", model_class, session_id)
            payload = self.redis_object_store.get(model_key)
            if payload is None:
                raise KeyError(f"No model with id {session_id}")
            return self._deserialize(payload, model_class)

    def store_model(self, model: GenieModel):
        """
        Store a model into the object store.

        :param model: the object to store
        """
        model_key = self._create_key("object", model)
        self.redis_object_store.set(
            model_key,
            self._serialize(model),
            ex=self.object_expiration_seconds,
        )

    def get_locked_model(
            self,
            session_id: str,
            model_class: str | Type[GenieModel],
    ) -> ModelContextManager:
        if isinstance(model_class, str):
            model_class = get_class_from_fully_qualified_name(model_class)
        return SessionLockManager.ModelContextManager(self, session_id, model_class)

    def progress_start(
            self,
            session_id: str,
            task_id: str,
            total_nr_subtasks: int,
    ):
        progress_key = self._create_key("progress", None, session_id)
        logger.info(
            "Starting progress record for session {session_id} with {nr_todo} tasks",
            session_id=session_id,
            nr_todo=total_nr_subtasks,
        )
        self.redis_progress_store.hset(
            progress_key,
            mapping={
                "task_id": task_id,
                "total_nr_subtasks": total_nr_subtasks,
                "nr_subtasks_executed": 0,
            },

        )

    def progress_exists(self, session_id: str) -> bool:
        progress_key = self._create_key("progress", None, session_id)
        nr_exists = self.redis_progress_store.exists(progress_key)
        if nr_exists == 0:
            return False
        if nr_exists == 1:
            return True
        logger.error(
            "Found that {nr_exists} progress records exist for session {session_id}",
            nr_exists=nr_exists,
            session_id=session_id,
        )
        return True

    def progress_update_todo(
            self,
            session_id: str,
            nr_increase: int,
    ) -> int:
        progress_key = self._create_key("progress", None, session_id)
        logger.info(
            "Adding {nr_increase} tasks to do for session {session_id}",
            nr_increase=nr_increase,
            session_id=session_id,
        )
        return self.redis_progress_store.hincrby(
            progress_key,
            "total_nr_subtasks",
            nr_increase,
        )

    def progress_update_done(
            self,
            session_id: str,
            nr_done: int = 1,
    ) -> int:
        progress_key = self._create_key("progress", None, session_id)
        logger.info(
            "Adding {nr_done} tasks done for session {session_id}",
            nr_done=nr_done,
            session_id=session_id,
        )
        return self.redis_progress_store.hincrby(
            progress_key,
            "nr_subtasks_executed",
            nr_done,
        )

    def progress_done(self, session_id: str):
        progress_key = self._create_key("progress", None, session_id)
        logger.info(
            "Removing progress record for session {session_id}",
            session_id=session_id,
        )
        self.redis_progress_store.delete(progress_key)

    def progress_status(self, session_id: str) -> tuple[int, int]:
        progress_key = self._create_key("progress", None, session_id)
        todo_str, done_str = self.redis_progress_store.hmget(
            progress_key,
            ["total_nr_subtasks", "nr_subtasks_executed"],
        )
        if todo_str is None or done_str is None:
            raise KeyError(f"No progress for session id {session_id}")

        todo, done = int(todo_str), int(done_str)
        logger.debug(
            "Found there are {nr_left} tasks left to do for session {session_id}",
            nr_left=todo - done,
            session_id=session_id,
        )
        return todo, done
