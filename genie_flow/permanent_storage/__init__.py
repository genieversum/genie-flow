from typing import Protocol, Optional

from genie_flow.genie import GenieModel
from genie_flow.model.user import User


class PermanentStorageManager(Protocol):

    def store(self, model: GenieModel):
        """
        Permanently persist the model.

        Persisting is idempotent and atomic; only the most recent version of the model
        will be stored.

        :param model: the GenieModel to persist
        :return:
        """
        pass

    def retrieve(self, session_id: str):
        """
        Retrieve a model from permanent storage. Will retrieve a subclass of a GenieModel,
        with the correct type. Will also retrieve and restore the secondary storage values.

        Will raise a KeyError if no GenieModel can be retrieved with the given session_id.

        :param session_id: the session_id of the GenieModel to retrieve
        :return: an instantiated GenieModel object
        :raises: KeyError if no GenieModel with the given session_id exists
        """
        pass

    def get_sessions_for_user(self, user: User) -> list[str]:
        """
        Returns a list of session_id's that are recorded in secondary storage as
        belonging to the given User.

        If no sessions exist for the given user, an empty list is returned.

        :param user: the User to retrieve the session ids for
        :return: a list of session ids
        """
        pass