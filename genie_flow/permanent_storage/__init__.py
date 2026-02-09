from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from typing import List, Tuple, Type, Dict, NamedTuple

from genie_flow.genie import GenieModel
from genie_flow.model.user import User


@dataclass
class RetrievableModel:
    """
    A reference to a GenieModel with a session. The reference will have a Callable
    that will retrieve the object from an external source.
    """
    session_id: str
    model_cls: Type[GenieModel]
    retriever: Callable[[], Dict[str, bytes]]


class PermanentStorageManager(ABC):

    def store_multi(
            self,
            models: List[GenieModel | RetrievableModel],
    ) -> Tuple[List[str], List[str]]:
        """
        Permanently store multiple models.

        :param models: A list of GenieModel or RetrievableModel objects
        :return: a tuple of lists, succeeded and failed session id's
        """
        pass

    def checkpoint(self):
        """
        Signal a checkpoint to the underlying system. This should indicate: we are done
        with a batch now, do some cleanup if you want before we come with a next batch.
        """
        pass

    def retrieve(self, session_id: str) -> GenieModel:
        """
        Retrieve a model from permanent storage. Will retrieve a subclass of a GenieModel,
        with the correct type. Will also retrieve and restore the secondary storage values.

        Will raise a KeyError if no GenieModel can be retrieved with the given session_id.

        :param session_id: the session_id of the GenieModel to retrieve
        :return: an instantiated GenieModel object
        :raises: KeyError if no GenieModel with the given session_id exists
        """
        pass

    def is_critical(self, ttl: int|float) -> bool:
        """
        Return a boolean indicating if an object with the given ttl is critical.

        :param ttl: an int or float for the time to live of a given object.
        :return: True when the ttl is within the critical watermark
        """
        ...

    def remaining_room(self, already_persisted: int) -> int:
        """
        Returns the number of objects that can still be persisted.

        :param already_persisted: the number of objects already persisted
        :return: the number of objects that can still be persisted, zero or more
        """
        ...

    def get_sessions_for_user(self, user: User) -> list[str]:
        """
        Returns a list of session_id's that are recorded in secondary storage as
        belonging to the given User.

        If no sessions exist for the given user, an empty list is returned.

        :param user: the User to retrieve the session ids for
        :return: a list of session ids
        """
        pass
