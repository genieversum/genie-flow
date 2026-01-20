import sqlite3
from os import PathLike
from pathlib import Path
from typing import Optional

from genie_flow.genie import GenieModel
from genie_flow.model.user import User


class PermanentStorageManager:

    def __init__(
        self,
        database_path: str | PathLike,
        blob_path: str | PathLike,
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
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_email 
            ON sessions(email);

            CREATE INDEX IF NOT EXISTS idx_sessions_updated_at 
            ON sessions(updated_at);
        """)

    def _get_blob_path(self, session_id: str) -> Path:
        directory = "/".join(
            session_id[(i*2):((i*2)+2)]
            for i in range(self.blob_directory_depth)
        )
        return self.blob_path / directory / f"{session_id}.blob"

    def _write_session_blob(self, model: GenieModel):
        file_path = self._get_blob_path(model.session_id)
        file_path.mkdir(parents=True, exist_ok=True)
        blob = model.serialize(compression=self.compress)
        tmp_file = file_path.with_suffix(".tmp")
        tmp_file.write_bytes(blob)
        tmp_file.rename(file_path)

    def _upsert_session_index(self, model: GenieModel):


    def store(self, model: GenieModel):
        session_id = model.session_id
        user_info: Optional[User] = model.secondary_storage.get("user_info", None)
        email_address = user_info.email if user_info else "dummy@dummy.com"



        self.conn