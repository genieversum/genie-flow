from enum import Enum

from loguru import logger
from pydantic import BaseModel, Field, RootModel

from genie_flow.model.versioned import VersionedModel
from genie_flow.utils import get_fully_qualified_name_from_class, \
    get_class_from_fully_qualified_name


class PersistenceState(Enum):
    NEW_OBJECT = 0
    RETRIEVED_OBJECT = 1
    DELETED_OBJECT = 2


class SecondaryStore(RootModel[dict[str, VersionedModel]]):
    _states: dict[str, Enum] = Field(default_factory=dict)

    def __getitem__(self, key: str) -> VersionedModel:
        return self.root[key]

    def __setitem__(self, key: str, value: VersionedModel):
        self.root[key] = value
        self._states[key] = PersistenceState.NEW_OBJECT

    def __delitem__(self, key: str):
        del self.root[key]
        self._states[key] = PersistenceState.DELETED_OBJECT

    @classmethod
    def from_retrieved_values(cls, retrieved_values: dict[str, VersionedModel]):
        result = cls.model_validate(retrieved_values)
        for key in retrieved_values.keys():
            result._states[key] = PersistenceState.RETRIEVED_OBJECT
        return result

    @classmethod
    def from_serialized(cls, payloads: dict[str, bytes]) -> "SecondaryStore":
        key_values: dict[str, VersionedModel] = dict()
        for key, payload in payloads.items():
            payload_type, payload = payload.split(b":", maxsplit=1)
            model_class = get_class_from_fully_qualified_name(payload_type)
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
        return any(
            state == PersistenceState.NEW_OBJECT
            for state in self._states.values()
        )

    @property
    def deleted_values(self) -> set[str]:
        return {
            key
            for key, state in self._states.items()
            if state == PersistenceState.DELETED_OBJECT
        }

    @property
    def unpersisted_values(self) -> dict[str, VersionedModel]:
        return {
            key: self.root[key]
            for key, state in self._states.items()
            if state == PersistenceState.NEW_OBJECT
        }

    def mark_persisted(self, keys: str | list[str]):
        if isinstance(keys, str):
            keys = [keys]

        for key in keys:
            if self._states[key] == PersistenceState.RETRIEVED_OBJECT:
                logger.error(
                    "Trying to mark {key} as persisted, but it is already marked as such",
                    key=key,
                )
                raise KeyError("Attempting to overwrite existing persisted id")
            self._states[key] = PersistenceState.RETRIEVED_OBJECT

    def unpersisted_serialized(self, compression: bool) -> dict[str, bytes]:
        result: dict[str, bytes] = dict()
        for key, value in self.unpersisted_values.items():
            model_fqn = get_fully_qualified_name_from_class(value)
            value_serialized = value.serialize(compression)
            result[key] = f"{model_fqn}:{value_serialized}".encode("utf-8")
        return result
