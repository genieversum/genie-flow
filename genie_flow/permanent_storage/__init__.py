import datetime
import os
import sqlite3
from functools import cache
from pathlib import Path
from typing import Optional, Protocol, List, Iterator

from loguru import logger
from redis import Redis

from genie_flow.genie import GenieModel
from genie_flow.model.user import User
from genie_flow.permanent_storage.file_store import write, read




class PermanentStorageManagerProtocol(Protocol):
    def store(self, model: GenieModel): ...
    def retrieve(self, session_id: str) -> GenieModel: ...
    def get_sessions_for_user(self, user: User) -> List[str]: ...


class DummyStorageManager(PermanentStorageManagerProtocol):

    def mark_dirty(self, model: GenieModel):
        pass

    def store(self, model: GenieModel):
        pass

    def retrieve(self, session_id: str) -> GenieModel:
        raise KeyError("Cannot retrieve session with id "+session_id)

    def get_sessions_for_user(self, user: User) -> List[str]:
        return list()


class PermanentStorageManager(PermanentStorageManagerProtocol):

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
                email_address TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_email 
            ON sessions(email_address);

            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at 
            ON sessions(updated_at);
        """)

    @cache
    def _get_blob_path(self, session_id: str) -> Path:
        # Since session_id is a ULID, we find better sharding entropy from the tail
        session_id_rev = session_id[::-1]

        shards = "/".join(
            session_id_rev[(i*2+1)] + session_id_rev[(i*2)]
            for i in range(self.blob_directory_depth)
        )
        return self.blob_path / shards / f"{session_id}"

    def _upsert_session_index(self, model: GenieModel):
        now = datetime.datetime.now(tz=datetime.timezone.utc).timestamp()
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
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO
                        UPDATE SET updated_at = excluded.updated_at
              """,
            (
                session_id,
                email_address,
                now,
                now,
            ),
        )

    def store(self, model: GenieModel):
        file_path = self._get_blob_path(model.session_id)

        try:
            write(file_path, model, self.compress)
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
                "deleting file {file_path}",
                session_id=model.session_id,
                exc=e.__class__.__name__,
                file_path=file_path,
            )
            try:
                os.remove(file_path)
            except Exception as file_remove_e:
                logger.warning(
                    "Failed to remove file {file_path} with exception {exc}",
                    file_path=file_path,
                    exc=file_remove_e.__class__.__name__,
                )
            raise e

    def retrieve(self, session_id: str) -> GenieModel:
        file_path = self._get_blob_path(session_id)
        return read(file_path)

    def get_sessions_for_user(self, user: Optional[User]) -> List[str]:
        if not user or not user.email:
            return list()

        cursor = self.conn.execute(
            "SELECT session_id FROM sessions WHERE email_address = ?",
            (user.email, ),
        )
        return [row[0] for row in cursor.fetchall()]
