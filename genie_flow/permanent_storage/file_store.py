import os
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.secondary_store import SecondaryStore
from genie_flow.model.versioned import VersionedModel
from genie_flow.utils import get_fully_qualified_name_from_class, \
    get_class_from_fully_qualified_name


def _serialize_with_type(obj: VersionedModel, compress: bool) -> bytes:
    model_fqn = get_fully_qualified_name_from_class(obj)
    value_serialized = obj.serialize(compression=compress)
    return model_fqn.encode("utf-8") + b":" + value_serialized


def _deserialize_with_type(obj: bytes) -> GenieModel:
    model_fqn_bytes, blob = obj.split(b":", 1)
    cls = get_class_from_fully_qualified_name(model_fqn_bytes.decode("utf-8"))
    if not issubclass(cls, GenieModel):
        logger.error(
            "Stored model is not a GenieModel subclass, it is a {cls}",
            cls=cls.__name__,
        )
        raise ValueError("Stored model is not a GenieModel subclass")

    return cls.deserialize(blob)


def write(file_dir: Path, model: GenieModel, compress: bool):
    file_path = file_dir / model.session_id
    tmp_file = file_path.with_suffix(".tmp")
    with tarfile.open(tmp_file, "w") as tar:
        model_blob = _serialize_with_type(model, compress)
        info = tarfile.TarInfo(name="_")
        info.size = len(model_blob)
        tar.addfile(info, BytesIO(model_blob))

        for key, value in model.secondary_storage.root.items():
            blob = _serialize_with_type(value, compress)
            info = tarfile.TarInfo(name=key)
            info.size = len(blob)
            tar.addfile(info, BytesIO(blob))

    tmp_file.rename(file_path.with_suffix(".tar"))


def read(file_dir: Path, session_id: str) -> GenieModel:
    model: Optional[GenieModel] = None
    secondary_storage_blobs: Dict[str, bytes] = dict()

    file_path = (file_dir / session_id).with_suffix(".tar")
    with tarfile.open(file_path, "r|") as tar:
        for member in tar:
            file = tar.extractfile(member)
            if file is None:
                continue

            file_bytes = file.read()
            if member.name == "_":
                model = _deserialize_with_type(file_bytes)
            else:
                secondary_storage_blobs[member.name] = file_bytes

    if model is None:
        logger.error(
            "File '{file_path}' does not contain data of the GenieModel",
            file_path=file_path,
        )
        raise ValueError("No GenieModel in file")

    model.secondary_storage = SecondaryStore.from_serialized(secondary_storage_blobs)
    return model


def delete(file_dir: Path, session_id: str) -> bool:
    file_path = (file_dir / session_id).with_suffix(".tar")
    os.remove(file_path)