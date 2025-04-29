from enum import Enum

from loguru import logger
from pydantic import BaseModel, Field, RootModel

from genie_flow.model.versioned import VersionedModel
from genie_flow.utils import get_fully_qualified_name_from_class


class _PersistedType(Enum):
    _token = 0


_Persisted = _PersistedType._token


class SecondaryStore(RootModel[dict[str, VersionedModel | _PersistedType]]):
    def __getitem__(self, key: str) -> BaseModel | _PersistedType:
        return self.root[key]

    def __setitem__(self, key: str, value: VersionedModel):
        self.root[key] = value

    def __delitem__(self, key: str):
        del self.root[key]

    @property
    def has_unpersisted_values(self) -> bool:
        for value in self.root.values():
            if not isinstance(value, _PersistedType):
                return True
        return False

    @property
    def unpersisted_values(self) -> dict[str, VersionedModel]:
        return {
            key: value
            for key, value in self.root.items()
            if not isinstance(value, _PersistedType)
        }

    def mark_persisted(self, key: str | list[str]):
        if isinstance(key, list):
            for k in key:
                self.mark_persisted(k)
            return

        if isinstance(self.root[key], _PersistedType):
            logger.error(
                "Trying to mark {key} as persisted, but it is already marked as such",
                key=key,
            )
            raise KeyError("Attempting to overwrite existing persisted id")
        self.root[key] = _Persisted

    def unpersisted_serialized(self, compression: bool) -> dict[str, bytes]:
        return {
            key: (
                "{get_fully_qualified_name_from_class(value)}:"
                "{value.serialize(compression)}"
            )
            for key, value in self.unpersisted_values.items()
            if not isinstance(value, _PersistedType)
        }

    @classmethod
    def unserialize(cls, payload: dict[str, bytes]) -> dict[str, VersionedModel]:
