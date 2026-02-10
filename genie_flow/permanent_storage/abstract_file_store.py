import os
import tarfile
import time
from abc import ABC
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List, Tuple, NamedTuple

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.secondary_store import SecondaryStore
from genie_flow.model.user import User
from genie_flow.model.versioned import VersionedModel
from genie_flow.permanent_storage import PermanentStorageManager, RetrievableModel
from genie_flow.utils import (
    get_fully_qualified_name_from_class,
    get_class_from_fully_qualified_name,
)


class AbstractFileStorageManager(PermanentStorageManager, ABC):

    def __init__(
        self,
        critical_watermark: int | float,
        max_writes: int,
        blob_path: str | Path | None,
        compress: bool,
        blob_directory_depth: int,
    ):
        super().__init__(critical_watermark, max_writes)
        self.blob_directory_depth = blob_directory_depth
        self.blob_path = Path(blob_path)
        self.compress = compress

    @cache
    def _get_blob_dir(self, session_id: str) -> Path:
        # Since session_id is a ULID, we find better sharding entropy from the tail
        session_id_rev = session_id[::-1]

        shards = "/".join(
            session_id_rev[(i*2+1)] + session_id_rev[(i*2)]
            for i in range(self.blob_directory_depth)
        )
        file_dir = self.blob_path / shards
        if not file_dir.exists():
            file_dir.mkdir(parents=True, exist_ok=True)
        return file_dir

    def _write_tar(self, model: GenieModel):
        file_dir = self._get_blob_dir(model.session_id)
        file_path = file_dir / model.session_id
        tmp_file = file_path.with_suffix(".tmp")
        now = time.time()
        with tarfile.open(tmp_file, "w") as tar:
            model_blob = _serialize_with_type(model, self.compress)
            info = tarfile.TarInfo(name="_")
            info.size = len(model_blob)
            info.mtime = now
            tar.addfile(info, BytesIO(model_blob))

            for key, value in model.secondary_storage.root.items():
                blob = _serialize_with_type(value, self.compress)
                info = tarfile.TarInfo(name=key)
                info.size = len(blob)
                info.mtime = now
                tar.addfile(info, BytesIO(blob))

        tmp_file.replace(file_path.with_suffix(".tar"))

    def _read_tar(self, session_id: str) -> GenieModel:
        model: Optional[GenieModel] = None
        secondary_storage_blobs: Dict[str, bytes] = dict()

        file_dir = self._get_blob_dir(session_id)
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

    def _delete_tar(self, session_id: str):
        file_dir = self._get_blob_dir(session_id)
        file_path = (file_dir / session_id).with_suffix(".tar")
        os.remove(file_path)

    def _write_multi(
            self,
            models: List[GenieModel | RetrievableModel],
    ) -> _WriteResult:
        """
        Write a list of GenieModel or RetrievableModel objects to files. Returns
        a tuple of lists. The first of that tuple being a list of tuples containing
        session_id and email address of the succeeded file writes. The second list being
        a list of string session id's.

        :param models: a list of GenieModel or RetrievableModel objects
        :return: a _WriteResult representing succeeded and failed writes
        """
        succeeded: List[Tuple[str, str]] = list()
        failed: List[str] = list()

        for model in models:
            try:
                if isinstance(model, RetrievableModel):
                    model = model.retriever()
                self._write_tar(model)
            except KeyError as e:
                logger.error(
                    "Failed to retrieve model for session {session_id}",
                    session_id=model.session_id,
                )
                failed.append(model.session_id)
            except Exception as e:
                logger.error(
                    "Failed to store file for model of session {session_id}, "
                    "with exception {exc}",
                    session_id=model.session_id,
                    exc=e.__class__.__name__,
                )
                failed.append(model.session_id)
            else:
                user_info: Optional[User] = model.secondary_storage.get("user_info", None)
                email_address = user_info.email if user_info else "dummy@dummy.com"
                succeeded.append((model.session_id, email_address))

        logger.debug(
            "Written {nr_succeeded} files; failed {nr_failed} write attempts",
            nr_succeeded=len(succeeded),
            nr_failed=len(failed),
        )
        return _WriteResult(succeeded, failed)


class _WriteResult(NamedTuple):
    succeeded: List[Tuple[str, str]]  # (session_id, email)
    failed: List[str]  # session_ids


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
