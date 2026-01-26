import os
import sqlite3
import tarfile
import time
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.secondary_store import SecondaryStore
from genie_flow.model.user import User
from genie_flow.model.versioned import VersionedModel
from genie_flow.permanent_storage import PermanentStorageManager
from genie_flow.utils import get_fully_qualified_name_from_class, \
    get_class_from_fully_qualified_name


_DATABASE_NAME = "permanent_store.db"


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


class FileStorageManager(PermanentStorageManager):

    def __init__(
        self,
        database_path: str | Path | None,
        blob_path: str | Path | None,
        compress: bool = False,
        blob_directory_depth: int = 2
    ):
        """
        This perma

        :param database_path: Path to the database file. Accepts a string or Path object.
            Can be None if no database is required.
        :param blob_path: Path to the blob storage directory. Accepts a string or Path
            object. Can be None if no blob storage is required.
        :param compress: Boolean flag to enable or disable compression for blob storage.
        :param blob_directory_depth: Integer specifying the depth of the directory
            structure for organizing blob storage. Defaults to 2.
        """
        self.database_path = Path(database_path)
        self.blob_path = Path(blob_path)
        self.compress = compress
        self.blob_directory_depth = blob_directory_depth

        self.conn = self._create_connection()
        self._init_database()

    def _create_connection(self):
        self.database_path.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.database_path / _DATABASE_NAME,
            timeout=30.0,
            isolation_level=None
        )
        conn.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
        """)
        return conn

    def _init_database(self):
        """Initialize the database with WAL mode and proper settings"""
        self.conn.executescript("""
            -- Enable WAL mode (allows concurrent reads + single writer)
            PRAGMA journal_mode = WAL;

            -- Safer durability for batch writes
            PRAGMA synchronous = NORMAL;

            -- Larger cache
            PRAGMA cache_size = -64000;

            -- Create schema if not exists
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                email_address TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_email 
            ON sessions(email_address);

            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at 
            ON sessions(updated_at);
        """)

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

    def _upsert_session_index(self, model: GenieModel):
        session_id = model.session_id
        user_info: Optional[User] = model.secondary_storage.get("user_info", None)
        email_address = user_info.email if user_info else "dummy@dummy.com"

        self.conn.execute(
            """
                    INSERT INTO sessions (
                        session_id,
                        email_address,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(session_id) DO
                        UPDATE SET updated_at = datetime('now')
              """,
            (session_id, email_address),
        )

    def store(self, model: GenieModel):
        try:
            self._write_tar(model)
        except Exception as e:
            logger.error(
                "Failed to store model for session {session_id}, with exception {exc}",
                session_id=model.session_id,
                exc=e.__class__.__name__,
            )
            raise e

        try:
            self._upsert_session_index(model)
        except Exception as e:
            logger.error(
                "Failed to upsert session {session_id}, with exception {exc}, "
                "deleting file",
                session_id=model.session_id,
                exc=e.__class__.__name__,
            )
            try:
                self._delete_tar(model.session_id)
            except Exception as file_remove_e:
                logger.warning(
                    "Failed to remove file for session {session_id} "
                    "with exception {exc}",
                    session_id=model.session_id,
                    exc=file_remove_e.__class__.__name__,
                )
            raise e

    def retrieve(self, session_id: str) -> GenieModel:
        return self._read_tar(session_id)

    def get_sessions_for_user(self, user: Optional[User]) -> List[str]:
        if not user or not user.email:
            return list()

        cursor = self.conn.execute(
            "SELECT session_id FROM sessions WHERE email_address = ?",
            (user.email, ),
        )
        return [row[0] for row in cursor.fetchall()]
