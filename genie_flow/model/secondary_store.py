import hashlib
from enum import Enum

from loguru import logger
from pydantic import BaseModel, Field, RootModel

from genie_flow.model.versioned import VersionedModel
from genie_flow.utils import get_fully_qualified_name_from_class, \
    get_class_from_fully_qualified_name


class PersistenceState(Enum):
    NEW_OBJECT = 0  # new object that should be persisted
    RETRIEVED_OBJECT = 1  # existing object that should NOT be persisted
    DELETED_OBJECT = 2  # old object that should be removed


class SecondaryStore(RootModel[dict[str, VersionedModel]]):
    """
    Represents a secondary data storage model that acts as a dict of str to `VersionedModel`
    instances. It tracks the state of its items for persistence purposes, ensuring that only
    values that are marked as NEW_OBJECT are stored.
    """
    root: dict[str, VersionedModel] = Field(default_factory=dict)
    _states: dict[str, Enum] = dict()

    def __getitem__(self, key: str) -> VersionedModel:
        return self.root[key]

    def __setitem__(self, key: str, value: VersionedModel):
        if not isinstance(value, VersionedModel):
            logger.error(
                "Cannot set a value for key {key} that is not a VersionedModel",
                key=key,
            )
            raise ValueError("Invalid data type for secondary store: must be a VersionedModel")

        self.root[key] = value
        self._states[key] = PersistenceState.NEW_OBJECT

    def __delitem__(self, key: str):
        del self.root[key]
        self._states[key] = PersistenceState.DELETED_OBJECT

    @classmethod
    def from_retrieved_values(cls, retrieved_values: dict[str, VersionedModel]) -> "SecondaryStore":
        """
        Create a SecondaryStore from retrieved values. This ensures that the state of
        all properties is set to RETRIEVED_OBJECT.

        :param retrieved_values: a dictionary that this SecondaryStore should encapsulate
        :return: a new SecondaryStore with the retrieved values as root values,
        and all states set to RETRIEVED_OBJECT
        """
        result = cls.model_validate(retrieved_values)
        for key in retrieved_values.keys():
            result._states[key] = PersistenceState.RETRIEVED_OBJECT
        return result

    @classmethod
    def from_serialized(cls, payloads: dict[str, bytes]) -> "SecondaryStore":
        """
        Create a SecondaryStore from serialized values. This ensures that the state of
        all properties states are set to RETRIEVED_OBJECT.

        :param payloads: a dictionary where the values for each key are serialized objects
        :return: a new SecondaryStore with the retrieved values as root values,
        and all states set to RETRIEVED_OBJECT
        """
        key_values: dict[str, VersionedModel] = dict()
        for key, payload in payloads.items():
            payload_type, payload = payload.split(b":", maxsplit=1)
            model_class = get_class_from_fully_qualified_name(payload_type.decode("utf-8"))
            if not issubclass(model_class, VersionedModel):
                logger.error(
                    "Cannot unserialize a payload with type {payload_type} that "
                    "is not a VersionedModel",
                    payload_type=payload_type,
                )
                raise ValueError(
                    f"Cannot unserialize a payload with type {payload_type} that "
                    f"is not a VersionedModel",
                )
            key_values[key] = model_class.deserialize(payload)
        return cls.from_retrieved_values(key_values)

    @property
    def has_unpersisted_values(self) -> bool:
        """Does this SecondaryStore have any unpersisted values?"""
        return any(
            state == PersistenceState.NEW_OBJECT
            for state in self._states.values()
        )

    @property
    def has_deleted_values(self) -> bool:
        """Does this SecondaryStore have any deleted values?"""
        return any(
            state == PersistenceState.DELETED_OBJECT
            for state in self._states.values()
        )

    @property
    def deleted_keys(self) -> set[str]:
        """Returns a set of keys that are marked as deleted"""
        return {
            key
            for key, state in self._states.items()
            if state == PersistenceState.DELETED_OBJECT
        }

    @property
    def unpersisted_values(self) -> dict[str, VersionedModel]:
        """Returns a dictionary of keys and values that are marked as new"""
        return {
            key: self.root[key]
            for key, state in self._states.items()
            if state == PersistenceState.NEW_OBJECT
        }

    @property
    def transfer_key(self) -> str:
        key = hashlib.sha256()
        for value in self.root.values():
            key.update(value.serialize(compression=True))
        return key.hexdigest()

    def mark_persisted(self, keys: str | list[str]):
        """
        Marks the provided keys as persisted in the internal state dictionary. If any key is
        already marked as persisted, a KeyError is raised.

        :param keys: A string representing a single key or a list of strings representing
                     multiple keys to be marked as persisted.
        :raises KeyError: If attempting to mark a key as persisted when it is already marked
                          as such.
        """
        if isinstance(keys, str):
            keys = [keys]

        for key in keys:
            if self._states[key] == PersistenceState.RETRIEVED_OBJECT:
                logger.error(
                    "Trying to mark {key} as persisted, but it is already marked as such",
                    key=key,
                )
                raise KeyError("Attempting to overwrite existing persisted id")
            logger.debug("Marking {key} as persisted", key=key)
            self._states[key] = PersistenceState.RETRIEVED_OBJECT

    def unpersisted_serialized(self, compression: bool) -> dict[str, bytes]:
        """
        Serializes unpersisted values in the instance to a dictionary, encoding them with
        the proper format and optionally applying compression.

        The function iterates over the `unpersisted_values` attribute, retrieves the fully
        qualified name (FQN) of each value's class, serializes the value itself, and combines
        the FQN with the serialized data. It then stores the result in a dictionary where
        keys are the original keys, and values are the encoded serialized results.

        :param compression: Flag indicating whether to apply compression during serialization.
        :type compression: bool
        :return: A dictionary mapping the original keys to the encoded serialized data.
        :rtype: dict[str, bytes]
        """
        result: dict[str, bytes] = dict()
        for key, value in self.unpersisted_values.items():
            model_fqn = get_fully_qualified_name_from_class(value)
            value_serialized = value.serialize(compression)
            result[key] = model_fqn.encode("utf-8") + b":" + value_serialized
        return result
