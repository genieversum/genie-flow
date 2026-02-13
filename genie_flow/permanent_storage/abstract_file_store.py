import datetime
import hashlib
import json
import tarfile
import time
from abc import ABC
from dataclasses import dataclass, asdict
from functools import cache
from io import BytesIO
from threading import local
from typing import Optional, Dict, List, Tuple, NamedTuple

from loguru import logger
try:
    import fsspec
except ImportError:
    fsspec = None

from genie_flow.genie import GenieModel
from genie_flow.model.secondary_store import SecondaryStore
from genie_flow.model.user import User
from genie_flow.model.versioned import VersionedModel
from genie_flow.permanent_storage import PermanentStorageManager, RetrievableModel
from genie_flow.utils import (
    get_fully_qualified_name_from_class,
    get_class_from_fully_qualified_name,
)


_READ_ATTEMPTS = 3
_MANIFEST_NAME = "MANIFEST.json"


def _serialize_with_type(obj: VersionedModel, compress: bool) -> bytes:
    model_fqn = get_fully_qualified_name_from_class(obj)
    value_serialized = obj.serialize(compression=compress)
    return model_fqn.encode("utf-8") + b":" + value_serialized


def _deserialize_with_type(obj: bytes) -> VersionedModel:
    model_fqn_bytes, blob = obj.split(b":", 1)
    cls = get_class_from_fully_qualified_name(model_fqn_bytes.decode("utf-8"))
    if not issubclass(cls, VersionedModel):
        logger.error(
            "Stored model is not a VersionedModel subclass, it is a {cls}",
            cls=cls.__name__,
        )
        raise ValueError("Stored model is not a VersionedModel subclass")

    return cls.deserialize(blob)


class WriteResult(NamedTuple):
    succeeded: List[Tuple[str, str]]  # (session_id, email)
    failed: List[str]  # session_ids


@dataclass
class ManifestMember:
    name: str
    size: int


@dataclass
class Manifest:
    timestamp: str
    hash: str
    members: List[ManifestMember]

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            timestamp=data['timestamp'],
            hash=data['hash'],
            members=[ManifestMember(**m) for m in data['members']]
        )


@dataclass
class FileStorageConfig:
    """
    Configuration on how to store files.

    :param file_storage_url: URL to the place to store the files (using fsspec)
    :param compress: Whether or not to compress the content in the file
    :param shard_depth: How deep sharding directories should be created
    :param file_storage_options: a dictionary of additional storage options for the fs backend
    """
    file_storage_url: str
    compress: bool
    shard_depth: int
    file_storage_options: Optional[Dict]


class AbstractFileStorageManager(PermanentStorageManager, ABC):

    def __init__(
        self,
        critical_watermark: int | float,
        max_writes: int,
        file_storage_config: FileStorageConfig,
    ):
        """
        Abstract Permanent Store Manager that stores Genie Model objects into tar files.

        :param critical_watermark: A time to live below the watermark indicates it
            is critical to persist an object
        :param max_writes: the maximum number of objects to store in one batch
        :param file_storage_config: the configuration of where and how to store tar files
        """
        if fsspec is None:
            raise ImportError(
                "Permanent Storage uses fsspec. Install using `genie-flow[permanent]"
            )

        super().__init__(critical_watermark, max_writes)
        self.compress = file_storage_config.compress
        self.shard_depth = file_storage_config.shard_depth

        self.file_storage_url = file_storage_config.file_storage_url
        self._thread_local = local()
        self.fs_options = dict(timeout=10)
        if file_storage_config.file_storage_options:
            self.fs_options.update(file_storage_config.file_storage_options)

    def _make_fs(self):
        fs, base_path = fsspec.url_to_fs(
            self.file_storage_url,
            **self.fs_options
        )
        self._thread_local.fs = fs
        self._thread_local.base_path = base_path

    @property
    def fs(self) -> fsspec.AbstractFileSystem:
        if not hasattr(self._thread_local, "fs"):
            self._make_fs()
        return self._thread_local.fs

    @property
    def file_storage_base_path(self) -> str:
        if not hasattr(self._thread_local, "base_path"):
            self._make_fs()
        return self._thread_local.base_path

    @cache
    def _get_file_url(self, session_id: str) -> str:
        session_id_rev = session_id[::-1]
        shards = "/".join(
            session_id_rev[(i*2+1)] + session_id_rev[(i*2)]
            for i in range(self.shard_depth)
        )
        return f"{self.file_storage_base_path}/{shards}/{session_id}.tar"

    def _write_tar(self, model: GenieModel):
        file_url = self._get_file_url(model.session_id)
        now = time.time()

        try:
            parent = "/".join(file_url.split("/")[:-1])
            if parent:
                self.fs.makedirs(parent, exist_ok=True)
        except (NotImplementedError, OSError, IOError):
            # Some backends don't need explicit directory creation
            pass

        with self.fs.open(file_url, "wb") as out_f:
            content_hash = hashlib.sha256()
            manifest_members: List[ManifestMember] = list()

            def addfile(name: str, b: bytes):
                content_hash.update(b)

                info = tarfile.TarInfo(name=name)
                info.size = len(b)
                info.mtime = now

                tar.addfile(info, BytesIO(b))

                manifest_members.append(
                    ManifestMember(name=name, size=len(b))
                )

            # stream tar directly to destination
            with tarfile.open(fileobj=out_f, mode="w|") as tar:
                blob = _serialize_with_type(model, self.compress)
                addfile("_", blob)

                for key, value in model.secondary_storage.root.items():
                    blob = _serialize_with_type(value, self.compress)
                    addfile(key, blob)

                manifest = Manifest(
                    timestamp=datetime.datetime.fromtimestamp(now).isoformat(),
                    members=manifest_members,
                    hash=content_hash.hexdigest(),
                )
                blob = json.dumps(asdict(manifest)).encode()
                addfile(_MANIFEST_NAME, blob)

    def _read_tar(self, session_id: str) -> GenieModel:
        file_url = self._get_file_url(session_id)

        for attempt in range(_READ_ATTEMPTS):
            if attempt > 0:
                time.sleep(0.1 * 2**attempt)

            backlog: Optional[Dict[str, bytes]] = dict()
            model: Optional[GenieModel] = None
            manifest: Optional[Manifest] = None

            content_hash = hashlib.sha256()
            with self.fs.open(file_url, 'rb') as f:
                with tarfile.open(fileobj=f, mode='r|') as tar:
                    for member in tar:
                        file = tar.extractfile(member)
                        if file is None:
                            continue

                        blob = file.read()
                        if member.name == _MANIFEST_NAME:
                            manifest = Manifest.from_dict(json.loads(blob.decode()))
                            continue

                        content_hash.update(blob)

                        if member.name == "_":
                            model = _deserialize_with_type(blob)
                            if backlog:
                                model.secondary_storage = SecondaryStore.from_serialized(backlog)
                                backlog = None
                        else:
                            if model is None:
                                backlog[member.name] = blob
                            else:
                                model.secondary_storage[member.name] = _deserialize_with_type(blob)

            if model is None:
                logger.warning(
                    "Attempt {attempt}; file '{file_url}' does not contain GenieModel",
                    attempt=attempt + 1,
                    file_url=file_url,
                )
                continue

            if manifest is None:
                logger.warning(
                    "Attempt {attempt}; file '{file_url}' does not contain manifest",
                    attempt=attempt + 1,
                    file_url=file_url,
                )
                continue

            if content_hash.hexdigest() != manifest.hash:
                logger.warning(
                    "Attempt {attempt}; manifest hash of file {file_url} "
                    "does not correspond to file hash",
                    attempt=attempt + 1,
                    file_url=file_url,
                )
                continue

            return model

        logger.error(
            "Failed to read from file {file_url} after {attempt} attempts",
            file_url=file_url,
            attempt=_READ_ATTEMPTS,
        )
        raise ValueError("Failed to read file")

    def _delete_tar(self, session_id: str):
        file_url = self._get_file_url(session_id)
        if self.fs.exists(file_url):
            self.fs.rm(file_url)
        else:
            logger.error(
                "No file exists to delete, for session {session_id}",
                session_id=session_id,
            )
            FileNotFoundError(f"There is no file for session {session_id}")

    def _write_multi(
            self,
            models: List[GenieModel | RetrievableModel],
    ) -> WriteResult:
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
                    model = model.retrieve()
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
        return WriteResult(succeeded, failed)

    def retrieve(self, session_id: str) -> GenieModel:
        return self._read_tar(session_id)
