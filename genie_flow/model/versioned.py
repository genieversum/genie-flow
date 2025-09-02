from functools import cache

import snappy
from loguru import logger
from pydantic import BaseModel, ConfigDict
from pydantic.main import IncEx
from pydantic_core import from_json


class VersionedModel(BaseModel):
    """
    A base class for models that have a schema version.
    
    This model provides built-in serialization and deserialization capabilities:

    - Serialization: Converts model instances to bytes format with schema versioning and optional compression
    - Deserialization: Restores model instances from bytes, handling schema version compatibility through upgrades
    - Schema versioning: Ensures data compatibility across different model versions through version tracking
    """

    model_config = ConfigDict(json_schema_extra={"schema_version": 0})

    @classmethod
    @cache
    def get_schema_version(cls) -> int:
        return int(cls.model_json_schema()["schema_version"])

    def serialize(
        self,
        compression: bool = False,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
    ) -> bytes:
        """
        Creates a serialization of the object. Serialization results in a
        bytes object, containing the schema version number, a compression indicator and
        the serialized version of the model object. All separated by a ':' character.

        Computed fields will be excluded from serialization, except for those explicitly
        included.

        :param compression: a boolean indicating whether to use compression or not
        :param include: fields to include in the serialization
        :param exclude: fields to exclude from the serialization

        :return: a bytes with the serialized version of the model object
        """
        computed_fields_to_exclude = {
            field
            for field in self.__class__.model_computed_fields.keys()
            if include is None or field not in include
        }
        exclude = exclude.union(computed_fields_to_exclude) if exclude else computed_fields_to_exclude
        model_dump = self.model_dump_json(include=include, exclude=exclude)
        if compression:
            payload = snappy.compress(model_dump, encoding="utf-8")
        else:
            payload = model_dump.encode("utf-8")
        compression_flag = b"1" if compression else b"0"

        return b":".join(
            [str(self.get_schema_version()).encode("utf-8"), compression_flag, payload]
        )

    @classmethod
    def upgrade_schema(cls, from_version: int, model_data: dict) -> dict:
        """
        Upgrade the data in the model to the new schema version.

        **NOTE**: This method should be overridden by subclasses.

        :param from_version: the schema version to upgrade from
        :param model_data: the data that should be upgraded
        :return: the data that fits the current schema version
        :raises ValueError: if the schema version cannot be made compatible with the
        current schema version
        """
        logger.error(
            "Cannot deserialize a model with schema version {persisted_version} "
            "into a model with schema version {current_version} "
            "for model class {model_class}",
            persisted_version=int(from_version),
            current_version=cls.get_schema_version(),
            model_class=cls.__name__,
        )
        raise ValueError(f"Schema mis-match when deserializing a {cls.__name__} model")

    @classmethod
    def deserialize(cls, payload: bytes) -> "VersionedModel":
        persisted_version, compression, payload = payload.split(b":", maxsplit=2)
        persisted_version = int(persisted_version.decode("utf-8"))
        model_json = (
            snappy.decompress(payload, decoding="utf-8")
            if compression == b"1"
            else payload.decode("utf-8")
        )

        if persisted_version != cls.get_schema_version():
            model_data = from_json(model_json)
            model_data = cls.upgrade_schema(persisted_version, model_data)
            return cls.model_validate(model_data)

        return cls.model_validate_json(model_json, by_alias=True, by_name=True)
