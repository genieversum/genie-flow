import sqlite3
from functools import cache
from pathlib import Path
from typing import Optional, List

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.user import User
from genie_flow.permanent_storage.file_store import write, read, delete


_DATABASE_NAME = "permanent_store.db"


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
        file_dir = self._get_blob_dir(model.session_id)

        try:
            write(file_dir, model, self.compress)
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
                delete(file_dir, model.session_id)
            except Exception as file_remove_e:
                logger.warning(
                    "Failed to remove file for session {session_id} "
                    "with exception {exc}",
                    session_id=session_id,
                    exc=file_remove_e.__class__.__name__,
                )
            raise e

    def retrieve(self, session_id: str) -> GenieModel:
        file_path = self._get_blob_dir(session_id)
        return read(file_path, session_id)

    def get_sessions_for_user(self, user: Optional[User]) -> List[str]:
        if not user or not user.email:
            return list()

        cursor = self.conn.execute(
            "SELECT session_id FROM sessions WHERE email_address = ?",
            (user.email, ),
        )
        return [row[0] for row in cursor.fetchall()]
