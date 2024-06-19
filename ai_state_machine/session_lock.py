import redis_lock
from redis import Redis


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
