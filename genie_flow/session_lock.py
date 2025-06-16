from typing import Type, Optional, Literal

import redis_lock
from loguru import logger
from redis import Redis

from genie_flow.genie import GenieModel
from genie_flow.model.persistence import Persistence, PersistenceLevel
from genie_flow.model.secondary_store import SecondaryStore
from genie_flow.model.versioned import VersionedModel
from genie_flow.model.user import User
from genie_flow.mongo import retrieve_model
from genie_flow.utils import get_class_from_fully_qualified_name, get_fully_qualified_name_from_class


StoreType = Literal["object", "secondary", "lock", "progress"]


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
            self.model = self.lock_manager._retrieve_model(self.session_id, self.model_class)
            return self.model

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.lock_manager._store_model(self.model)
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
        session, this manager deals with locking multithreaded access to it when it retrieves
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
        self.update_set_key="update:session"
       
    def _create_lock_for_session(self, session_id: str) -> redis_lock.Lock:
        """
        Retrieve the lock for the object for the given `session_id`. This ensures that only
        one process will have access to the model and potentially make changes to it.
        This lock can function as a context manager. See the documentation of `redis_lock.Lock`
        :param session_id: The session id that the object in question belongs to
        """
        lock = redis_lock.Lock(
            self.redis_lock_store,
            name=session_id,
            expire=self.lock_expiration_seconds,
            auto_renewal=True,
        )
        return lock

    def _create_key(
            self,
            store: StoreType,
            model: GenieModel | type[GenieModel] | None,
            *args: str,
    ) -> str:
        key = f"{self.application_prefix}:{store}"
        if model is None:
            model_indicator = ""
        elif isinstance(model, GenieModel):
            model_indicator = model.__class__.__name__
        else:
            model_indicator = model.__name__
        return key + f":{model_indicator}:" + ":".join([arg for arg in args if arg is not None])

    def _retrieve_secondary_storage(
            self,
            session_id: str,
            model_cls: Type[GenieModel],
    ) -> SecondaryStore:
        """
        Retrieve the secondary storage for the given session id and model class.
        Not protected by a lock, and the user should ensure that no other process is accessing
        the model's secondary storage at the same time.
        :param session_id: the session id for which to retrieve the secondary storage
        :param model_cls: the model class for which to retrieve the secondary storage
        :return: a newly instantiated SecondaryStore object for the given session id and model class
        """
        secondary_key = self._create_key("secondary", model_cls, session_id)
        serialized_values = self.redis_object_store.hgetall(secondary_key)
        return SecondaryStore.from_serialized(serialized_values)

    def _retrieve_model(self, session_id: str, model_class: Type[GenieModel]) -> GenieModel:
        """
        Retrieve the GenieModel for the object for the given `session_id`. This retrieval is
        not protected by a lock, and the user should ensure that no other process is accessing
        the model at the same time.
        :param session_id: the session id that the object in question belongs to
        :param model_class: the GenieModel class to retrieve
        :return: a retrieved GenieModel object for the given `session_id`
        """
        model_key = self._create_key("object", model_class, session_id)
        payload = self.redis_object_store.get(model_key)
        if payload is None:
            logger.error("No model with id {session_id} found in object store, trying mongodb", session_id=session_id)
            try:
                mongo_data = retrieve_model(session_id)
                payload = mongo_data['model']
            except:
                raise KeyError(f"No model with id {session_id}")

        model = model_class.deserialize(payload)
        model.secondary_storage = self._retrieve_secondary_storage(session_id, model_class)
        return model

    def get_model(self, session_id: str, model_class: str | Type[GenieModel]) -> GenieModel:
        """
        Retrieve the GenieModel for the object for the given `session_id`. This retrieval is
        done inside a locked context, so no writing of the GenieModel can happen when this
        retrieval is done.

        :param session_id: The session id that the object in question belongs to
        :param model_class: The GenieModel class to retrieve or the fqn of the class
        :return: The GenieModel object for the given `session_id`
        """
        if isinstance(model_class, str):
            model_class = get_class_from_fully_qualified_name(model_class)
        with self._create_lock_for_session(session_id):
            return self._retrieve_model(session_id, model_class)

    def _store_secondary_storage(self, model: GenieModel):
        """
        Store the secondary storage values from the given Genie Model.
        Will only persist properties that have not yet been stored before.

        :param model: The Genie Model containing the secondary store to persist
        """
        secondary_key = self._create_key("secondary", model, model.session_id)

        if model.secondary_storage.has_unpersisted_values:
            unpersisted_serialized = model.secondary_storage.unpersisted_serialized(
                self.compression,
            )
            logger.debug(
                "Writing unpersisted field(s) [{field_list}] to secondary storage "
                "for session {session_id}",
                field_list=", ".join(unpersisted_serialized.keys()),
                session_id=model.session_id,
            )
            self.redis_object_store.hset(secondary_key, mapping=unpersisted_serialized)
            model.secondary_storage.mark_persisted(unpersisted_serialized.keys())

        if model.secondary_storage.has_deleted_values:
            deleted_fields = model.secondary_storage.deleted_keys
            logger.debug(
                "Removing deleted field(s) [{fields}] from secondary storage "
                "for session {session_id}",
                fields=", ".join(deleted_fields),
                session_id=model.session_id,
            )
            self.redis_object_store.hdel(secondary_key, *deleted_fields)

    def _store_model(self, model: GenieModel):
        """
        Underlying logic of writing a Genie Model to the object store.
        No locking happens in this method, so user is responsible for
        making sure no parallel reading or writing is done.

        :param model: the GenieModel to store
        """
        model_key = self._create_key("object", model, model.session_id)
        logger.debug(
            "Storing model for session {session_id} in object store",
            session_id=model.session_id,
        )

        self._store_secondary_storage(model)

        self.redis_object_store.set(
            model_key,
            model.serialize(self.compression, exclude={"secondary_storage"}),
            ex=self.object_expiration_seconds,
        )
        model_fqn = get_fully_qualified_name_from_class(model)
        if "persistence" not in  model.secondary_storage or \
            model.secondary_storage["persistence"].level == PersistenceLevel.LONG_TERM_PERSISTENCE:
            self.redis_object_store.sadd(
                self.update_set_key,
                f"{model_fqn}:{model.session_id}"
            )
            logger.debug(f"{self.redis_object_store.smembers(self.update_set_key)}")

    def store_model(self, model: GenieModel):
        """
        Store a model into the object store. Also stores the secondary storage of the model.
        Storing happens inside a locked context, so no reading or writing of the GenieModel
        can happen when this method is executing.

        :param model: the object to store
        """
        with self._create_lock_for_session(model.session_id):
            self._store_model(model)

    def get_locked_model(
            self,
            session_id: str,
            model_class: str | Type[GenieModel],
    ) -> ModelContextManager:
        if isinstance(model_class, str):
            model_class = get_class_from_fully_qualified_name(model_class)
        return SessionLockManager.ModelContextManager(self, session_id, model_class)

    @staticmethod
    def _create_field_key(field: str, invocation_id: str) -> str:
        return f"{invocation_id}:{field}"

    def _create_existing_progress_key(
            self,
            action: str,
            session_id: str,
            invocation_id: str
    ) -> str:
        progress_key = self._create_key("progress", None, session_id)
        if not self.redis_progress_store.exists(progress_key):
            logger.error(
                "Action {action} but no progress record for session {session_id}",
                action=action,
                session_id=session_id,
            )
            raise KeyError("No progress record for session")
        if not self.redis_progress_store.hexists(
            progress_key,
            self._create_field_key("todo", invocation_id),
        ):
            logger.error(
                "Action {action} but no progress record for session {session_id} "
                "and invocation {invocation_id}",
                action=action,
                session_id=session_id,
                invocation_id=invocation_id,
            )
            raise KeyError("No progress record for session and invocation")

        logger.info(
            "Starting {action} for session {session_id} and invocation {invocation_id}",
            action=action,
            session_id=session_id,
            invocation_id=invocation_id,
        )
        return progress_key

    def progress_start(
            self,
            session_id: str,
            invocation_id: str,
            nr_tasks_todo: int,
    ):
        progress_key = self._create_key(
            "progress",
            None,
            session_id,
        )
        if (
            self.redis_progress_store.exists(progress_key) > 0
            and self.redis_progress_store.hexists(
                progress_key,
                self._create_field_key("todo", invocation_id),
            )
        ):
            logger.error(
                "Progress record for session {session_id} and invocation {invocation_id} already exists",
                session_id=session_id,
                invocation_id=invocation_id,
            )
            raise ValueError("Progress record already exists for session and invocation")

        logger.info(
            "Starting progress record for session {session_id} and invocation {invocation_id}, "
            "with {nr_todo} tasks",
            session_id=session_id,
            invocation_id=invocation_id,
            nr_todo=nr_tasks_todo,
        )
        self.redis_progress_store.hset(
            progress_key,
            mapping={
                self._create_field_key("todo", invocation_id): nr_tasks_todo,
                self._create_field_key("done", invocation_id): 0,
                self._create_field_key("tombstone", invocation_id): "f",
            },
        )

    def progress_exists(self, session_id: str, invocation_id: Optional[str] = None) -> bool:
        progress_key = self._create_key(
            "progress",
            None,
            session_id,
        )
        if invocation_id is None:
            return self.redis_progress_store.exists(progress_key) == 1

        return self.redis_progress_store.hexists(
            progress_key,
            self._create_field_key("todo", invocation_id),
        )

    def progress_update_todo(
            self,
            session_id: str,
            invocation_id: str,
            nr_increase: int,
    ) -> int:
        progress_key = self._create_existing_progress_key(
            "Update To Do Count",
            session_id,
            invocation_id,
        )
        new_todo = self.redis_progress_store.hincrby(
            progress_key,
            self._create_field_key("todo", invocation_id),
            nr_increase,
        )
        logger.debug(
            "New: {new_todo} tasks to do for session {session_id}, invocation {invocation_id}",
            new_todo=new_todo,
            session_id=session_id,
            invocation_id=invocation_id,
        )
        return new_todo

    def progress_update_done(
            self,
            session_id: str,
            invocation_id: str,
            nr_done: int = 1,
    ) -> int:
        progress_key = self._create_existing_progress_key(
            "Update Done Count",
            session_id,
            invocation_id,
        )

        new_done = self.redis_progress_store.hincrby(
            progress_key,
            self._create_field_key("done", invocation_id),
            nr_done,
        )
        logger.debug(
            "New: {new_done} tasks done for session {session_id}, invocation {invocation_id}",
            new_done=new_done,
            session_id=session_id,
            invocation_id=invocation_id,
        )
        tombstone, todo_str = self.redis_progress_store.hmget(
            progress_key,
            [
                self._create_field_key("tombstone", invocation_id),
                self._create_field_key("todo", invocation_id),
            ],
        )
        todo = int(todo_str)
        
        if tombstone == b"t":
            if todo > new_done:
                logger.warning(
                    "Got an update for session {session_id} and invocation {invocation_id} "
                    "with a tombstoned progress record, with tasks to do {todo} > {done} done",
                    session_id=session_id,
                    invocation_id=invocation_id,
                    todo=todo,
                    done=new_done,
                )
            logger.info(
                "Removing progress record for session {session_id} and invocation {invocation_id}",
                session_id=session_id,
                invocation_id=invocation_id,
            )
            self.redis_progress_store.hdel(
                progress_key,
                self._create_field_key("todo", invocation_id),
                self._create_field_key("done", invocation_id),
                self._create_field_key("tombstone", invocation_id),
            )
        elif new_done >= todo:
            logger.warning(
                "Progress record for session {session_id} and invocation {invocation_id} "
                "indicates done {done} tasks >= {todo} tasks to do",
                session_id=session_id,
                invocation_id=invocation_id,
                done=new_done,
                todo=todo,
            )
        return todo - new_done

    def progress_tombstone(self, session_id: str, invocation_id: str):
        progress_key = self._create_existing_progress_key(
            "Tombstone Progress Record",
            session_id,
            invocation_id,
        )
        self.redis_progress_store.hset(
            progress_key,
            self._create_field_key("tombstone", invocation_id),
            "t"
        )

    def progress_status(self, session_id: str) -> tuple[int, int]:
        progress_key = self._create_key("progress", None, session_id)
        if not self.redis_progress_store.exists(progress_key):
            return 0, 0

        invocations_to_ignore = set()
        field_values = self.redis_progress_store.hgetall(progress_key)
        for field_name, value in field_values.items():
            if field_name.endswith(b"tombstone") and value == b"t":
                invocations_to_ignore.add(field_name.split(b":")[0])

        todo, done = 0, 0
        for field_name, value in field_values.items():
            invocation_id, field = field_name.split(b":")
            if invocation_id in invocations_to_ignore:
                continue
            if field == b"todo":
                todo += int(value)
            elif field == b"done":
                done += int(value)

        logger.debug(
            "Found there are {todo} - {done} = {nr_left} tasks left to do for "
            "session {session_id}",
            todo=todo,
            done=done,
            nr_left=todo - done,
            session_id=session_id,
        )
        return todo, done
