import sqlite3
from threading import local
import time
from pathlib import Path
from typing import Optional, List, Tuple

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.user import User
from genie_flow.permanent_storage import RetrievableModel
from genie_flow.permanent_storage.abstract_file_store import AbstractFileStorageManager

_DATABASE_NAME = "permanent_store.db"
_RETRYABLE_ERRORS = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}

_UPSERT_SQL = """
    INSERT INTO sessions (session_id, email_address, created_at, updated_at)
    VALUES (?, ?, datetime('now'), datetime('now'))
    ON CONFLICT(session_id) DO UPDATE SET updated_at = datetime('now')
"""


class FileStorageManager(AbstractFileStorageManager):
    _thread_local = local()

    def __init__(
        self,
        critical_watermark: int | float,
        max_writes: int,
        blob_path: str | Path | None,
        compress: bool,
        blob_directory_depth: int,
        database_path: str | Path | None,
        database_retries: int,
    ):
        """
        Permanently store GenieModel objects in tar files and keep an index of persisted
        records in an SQLite database.

        :param database_path: Path to the database file. Accepts a string or Path object.
            Can be None if no database is required.
        :param blob_path: Path to the blob storage directory. Accepts a string or Path
            object. Can be None if no blob storage is required.
        :param compress: Boolean flag to enable or disable compression for blob storage.
        :param database_retries: Int indicating the max retries for accessing the database
        :param blob_directory_depth: Integer specifying the depth of the directory
            structure for organizing blob storage. Defaults to 2.
        :param critical_watermark: the number of seconds of time-to-live, below which
            an object becomes critical to persist permanently
        """
        super().__init__(
            critical_watermark,
            max_writes,
            blob_path,
            compress,
            blob_directory_depth,
        )

        self.database_path = Path(database_path)
        self.database_retries = database_retries

        self._init_database()

    def _get_connection(self):
        if not hasattr(self._thread_local, 'conn'):
            self._thread_local.conn = self._create_connection()
        return self._thread_local.conn

    def _create_connection(self):
        self.database_path.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.database_path / _DATABASE_NAME,
            timeout=30.0,
            check_same_thread=False,
        )
        conn.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
            PRAGMA busy_timeout = 30000;
            PRAGMA temp_store = MEMORY;
        """)
        return conn

    def _init_database(self):
        """Initialize the database with WAL mode and proper settings"""
        self._get_connection().executescript("""
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

    def _execute_upsert(self, model: GenieModel):
        session_id = model.session_id
        user_info: Optional[User] = model.secondary_storage.get("user_info", None)
        email_address = user_info.email if user_info else "dummy@dummy.com"

        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(_UPSERT_SQL, (session_id, email_address))
        conn.commit()

    def _handle_upsert_error(
            self,
            e: sqlite3.OperationalError,
            attempt: int,
    ):
        if (
                e.sqlite_errorcode in _RETRYABLE_ERRORS
                and attempt < self.database_retries - 1
        ):
            logger.warning(
                "Database contention (error {code}), retry {attempt}/{max}",
                code=e.sqlite_errorname or e.sqlite_errorcode,
                attempt=attempt + 1,
                max=self.database_retries,
            )
            time.sleep(0.1 * (2 ** attempt))
        else:
            logger.error(
                "Failed to upsert session after {attempts} attempts: {error}",
                attempts=attempt + 1,
                error=e.sqlite_errorname or str(e)
            )
            raise e

    def _upsert_session_index(self, model: GenieModel):
        for attempt in range(self.database_retries):
            try:
                self._execute_upsert(model)
            except sqlite3.OperationalError as e:
                self._handle_upsert_error(e, attempt)
            else:
                return

    def store_multi(
            self,
            models: List[GenieModel | RetrievableModel],
    ) -> Tuple[List[str], List[str]]:
        """
        Persist a list of GenieModel or RetrievableModel objects. Returns a tuple of a
        list of succeeded session_ids and a list of failed session ids.

        First, writes all files for the supplied models. All succeeded writes will then
        be recorded into the database. If writing any to the database fails, attempts to
        remove any files written.

        :param models: a list of GenieModel or RetrievableModel objects
        :return: a tuple with succeeded, failed session ids
        """
        succeeded, failed = self._write_multi(models)
        if not succeeded:
            return [], [model.session_id for model in models]

        conn = self._get_connection()
        for attempt in range(self.database_retries):
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.executemany(_UPSERT_SQL, succeeded)
                conn.commit()
                return [s[0] for s in succeeded], failed
            except sqlite3.OperationalError as e:
                conn.rollback()
                try:
                    self._handle_upsert_error(e, attempt)
                except Exception as e:
                    logger.error(
                        "Failed to upsert {nr_sessions} sessions with error {exc}, "
                        "removing files",
                        nr_sessions=len(succeeded),
                        exc=f"{e.__class__.__name__}: {e}",
                    )
                    for session_id, _ in succeeded:
                        try:
                            self._delete_tar(session_id)
                        except Exception as e:
                            logger.warning(
                                "Failed to remove file for session {session_id}, "
                                "with error {exc}; ignoring",
                                session_id=session_id,
                                exc=f"{e.__class__.__name__}: {e}"
                            )
                    break

        return [], [model.session_id for model in models]

    def checkpoint(self):
        self._get_connection().execute("PRAGMA wal_checkpoint(PASSIVE)")

    def retrieve(self, session_id: str) -> GenieModel:
        return self._read_tar(session_id)

    def get_sessions_for_user(self, user: User) -> List[str]:
        if not user or not user.email:
            return list()

        cursor = self._get_connection().execute(
            "SELECT session_id FROM sessions WHERE email_address = ?",
            (user.email, ),
        )
        return [row[0] for row in cursor.fetchall()]
