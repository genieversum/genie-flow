from functools import cache

import snappy
from loguru import logger
from pydantic import BaseModel, ConfigDict
from pydantic.main import IncEx


class VersionedModel(BaseModel):
    """
    A base class for models that have a schema version.
    """

    model_config = ConfigDict(
        json_schema_extra={"schema_version": 0}
    )

    @classmethod
    @property
    @cache
    def schema_version(cls) -> int:
        return int(cls.model_json_schema()["schema_version"])

    def serialize(
            self,
            compression: bool,
            include: IncEx | None = None,
            exclude: IncEx | None = None,
    ) -> bytes:
        """
        Creates a serialization of the object. Serialization results in a
        bytes object, containing the schema version number, a compression indicator and
        the serialized version of the model object. All separated by a ':' character.

        :param compression: a boolean indicating whether to use compression or not
        :param include: fields to include in the serialization
        :param exclude: fields to exclude from the serialization
        
        :return: a bytes with the serialized version of the model object
        """
        model_dump = self.model_dump_json(include=include, exclude=exclude)
        if compression:
            payload = snappy.compress(model_dump, encoding="utf-8")
        else:
            payload = model_dump.encode("utf-8")
        compression_flag = b"1" if self.compression else b"0"

        return b":".join(
            [
                str(self.schema_version).encode("utf-8"), 
                compression_flag,
                payload
            ]
        )

    @classmethod
    def deserialize(cls, payload: bytes) -> "VersionedModel":
        persisted_version, compression, payload = payload.split(b":", maxsplit=2)
        if int(persisted_version) != cls.schema_version:
            logger.error(
                "Cannot deserialize a model with schema version {persisted_version} "
                "into a model with schema version {current_version} "
                "for model class {model_class}",
                persisted_version=int(persisted_version),
                current_version=cls.schema_version,
                model_class=cls.__name__,
            )
            raise ValueError(
                f"Schema mis-match when deserializing a {cls.__name__} model"
            )

        if compression == b"1":
            model_json = snappy.decompress(payload, decoding="utf-8")
        else:
            model_json = payload.decode("utf-8")

        return cls.model_validate_json(model_json, by_alias=True, by_name=True)
