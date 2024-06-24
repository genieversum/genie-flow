from typing import Type, Optional

import redis_lock
from redis import Redis

from ai_state_machine.genie import GenieModel


class LockedGenieModel:
    """
    A Context Manager for obtaining a locked `GenieModel`. This context manager obtains
    a lock for a particular session, then retrieves the GenieModel from store. Upon the
    exit of the context, that GenieModel is stored back into store and the lock is released.
    """

    def __init__(
            self,
            session_id: str,
            model_class: Type[GenieModel],
            lock: redis_lock.Lock
    ):
        self.session_id = session_id
        self.model_class = model_class
        self.lock = lock
        self.model: Optional[GenieModel] = None

    def __enter__(self) -> GenieModel:
        self.lock.acquire()

        models = self.model_class.select(ids=[self.session_id])
        if len(models) == 0:
            raise KeyError(f"No model with id {self.session_id}")
        if len(models) > 1:
            raise RuntimeError(f"Multiple models with id {self.session_id}")
        self.model = models[0]

        return self.model

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.model_class.insert(self.model)
        self.lock.release()


class SessionLockManager:
    """
    The `SessionLockManager` manages the session lock. When changes are (expected to be) made to
    the model of a particular session, this manager deals with locking multithreaded access to
    it when it gets retrieve from Store, and before it gets written back to it.
    """

    def __init__(
        self,
        redis_lock_store: Redis,
        lock_expiration_seconds: int,
    ):
        self.redis_lock_store = redis_lock_store
        self.lock_expiration_seconds = lock_expiration_seconds

    def get_lock_for_session(self, session_id: str) -> redis_lock.Lock:
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

    def get_model(self, session_id: str, model_class: Type[GenieModel]) -> GenieModel:
        """
        Retrieve the GenieModel for the object for the given `session_id`. This retrieval is
        done inside a locked context, so no writing of the GenieModel can happen when this
        retrieval is done.

        :param session_id: The session id that the object in question belongs to
        :param model_class: The GenieModel class to retrieve
        :return: The GenieModel object for the given `session_id`
        """
        with self.get_lock_for_session(session_id):
            models = model_class.select(ids=[session_id])
            if len(models) == 0:
                raise KeyError(f"No model with id {session_id}")
            if len(models) > 1:
                raise RuntimeError(f"Multiple models with id {session_id}")
            return models[0]

    def get_locked_model(
            self,
            session_id: str,
            model_class: Type[GenieModel],
    ) -> LockedGenieModel:
        return LockedGenieModel(
            session_id,
            model_class,
            self.get_lock_for_session(session_id)
        )
