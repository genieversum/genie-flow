import datetime
import sqlite3
from functools import cache
from pathlib import Path
from typing import Optional, Type, Protocol

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.user import User
from genie_flow.utils import (
    get_fully_qualified_name_from_class,
    get_class_from_fully_qualified_name,
)


class PermanentStorageManagerProtocol(Protocol):
    def store(self, model: GenieModel): ...
    def retrieve(self, session_id: str) -> GenieModel: ...


class DummyStorageManager:

    def store(self, model: GenieModel):
        pass

    def retrieve(self, session_id: str) -> GenieModel:
        raise KeyError("Cannot retrieve session with id "+session_id)


class PermanentStorageManager:

    def __init__(
        self,
        database_path: str | Path | None,
        blob_path: str | Path | None,
        compress: bool = False,
        blob_directory_depth: int = 2
    ):
        self.database_path = Path(database_path)
        self.blob_path = Path(blob_path)
        self.compress = compress
        self.blob_directory_depth = blob_directory_depth

        self.conn = self._create_connection()
        self._init_database()

    def _create_connection(self):
        conn = sqlite3.connect(
            self.database_path,
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
                email TEXT NOT NULL,
                model_fqn TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_email 
            ON sessions(email);

            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at 
            ON sessions(updated_at);
        """)

    @cache
    def _get_blob_path(self, session_id: str) -> Path:
        # Since session_id is a ULID, we find better sharding entropy from the tail
        session_id_rev = session_id[::-1]

        directory = "/".join(
            session_id_rev[(i*2+1)] + session_id_rev[(i*2)]
            for i in range(self.blob_directory_depth)
        )
        return self.blob_path / directory / f"{session_id}"

    def _write_session_blob(self, model: GenieModel):
        file_path = self._get_blob_path(model.session_id)
        file_path.mkdir(parents=True, exist_ok=True)
        blob = model.serialize(compression=self.compress, exclude={"secondary_storage"})
        file_path.write_bytes(blob)

        # write serializations of secondary storage into separate files
        for key, value in model.secondary_storage.root.items():
            model_fqn = get_fully_qualified_name_from_class(value)
            value_serialized = value.serialize(compression=self.compress)
            blob = model_fqn.encode("utf-8") + b":" + value_serialized

            ss_file = file_path.parent / f"{model.session_id}-{key}"
            ss_file.write_bytes(blob)

    def _upsert_session_index(self, model: GenieModel):
        now = datetime.datetime.now(tz=datetime.timezone.utc).timestamp()
        session_id = model.session_id
        model_fqn = get_fully_qualified_name_from_class(model)

        user_info: Optional[User] = model.secondary_storage.get("user_info", None)
        email_address = user_info.email if user_info else "dummy@dummy.com"

        self.conn.execute(
            """
INSERT INTO sessions (
    session_id,
    email,
    model_fqn,
    created_at,
    updated_at
) VALUES (?, ?, ?, ?, ?)
ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
              """,
            (
                session_id,
                email_address,
                model_fqn,
                now,
                now,
            ),
        )

    def _get_model_class(self, session_id: str) -> Type[GenieModel]:
        cursor = self.conn.execute(
            "SELECT model_fqn FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            logger.error(
                "Session does not exist with id 'session_id'",
                session_id=session_id,
            )
            raise KeyError(session_id)

        try:
            cls = get_class_from_fully_qualified_name(row[0])
        except ValueError:
            logger.error("Failed to get class for fqn 'fqn'", fqn=row[0])
            raise ValueError("Unknown class "+row[0])

        if not issubclass(cls, GenieModel):
            logger.error(
                "Registered model class 'cls' is not a GenieModel",
                cls=cls,
            )
            raise ValueError("Not a GenieModel class "+row[0])

        return cls

    def store(self, model: GenieModel):
        self._write_session_blob(model)
        self._upsert_session_index(model)

    def retrieve(self, session_id: str) -> GenieModel:
        file_path = self._get_blob_path(session_id)
        try:
            blob = file_path.read_bytes()
        except FileNotFoundError:
            logger.error(
                "No blob stored for session with id 'session_id'",
                session_id=session_id,
            )
            raise KeyError(session_id)

        cls = self._get_model_class(session_id)
        model = cls.deserialize(blob)

        # retrieve secondary storage from separate files
        secondary_storage_data: dict[str, bytes] = dict()
        for ss_file in file_path.parent.glob(f"session_id-*"):
            _, key = ss_file.root.split("-")
            secondary_storage_data[key] = ss_file.read_bytes()
        model.secondary_storage.from_serialized(secondary_storage_data)
        return model
