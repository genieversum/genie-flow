from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from loguru import logger

from genie_flow.genie import GenieModel
from genie_flow.model.user import User
from genie_flow.permanent_storage import RetrievableModel

try:
    import psycopg
    from psycopg_pool import ConnectionPool
except ImportError:
    psycopg = None
    ConnectionPool = None

from genie_flow.permanent_storage.abstract_file_store import AbstractFileStorageManager


_UPSERT_SQL = """
    INSERT INTO sessions (session_id, email_address, created_at, updated_at)
    VALUES (%s, %s, NOW(), NOW())
    ON CONFLICT (session_id)
        DO UPDATE SET updated_at = NOW()
"""


@dataclass
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    max_pool_size: int
    timeout: int | float

    @property
    def conninfo(self):
        return (
            f"host={self.host} port={self.port} "
            f"dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


class PostgresFileStoreManager(AbstractFileStorageManager):

    def __init__(
        self,
        critical_watermark: int | float,
        max_writes: int,
        blob_url: str | Path | None,
        compress: bool,
        blob_directory_depth: int,
        db_pool: ConnectionPool,
    ):
        if psycopg is None:
            raise ImportError(
                "PostgreSQL support requires psycopg. "
                "Install with: pip install genie-flow[postgres]"
            )

        super().__init__(
            critical_watermark,
            max_writes,
            blob_url,
            compress,
            blob_directory_depth,
        )
        self.db_pool = db_pool

        self._init_database()

    @classmethod
    def from_config(
        cls,
        critical_watermark: int | float,
        max_writes: int,
        blob_path: str | Path | None,
        compress: bool,
        blob_directory_depth: int,
        database_config: PostgresConfig,
    ):
        if psycopg is None:
            raise ImportError(
                "PostgreSQL support requires psycopg. "
                "Install with: pip install genie-flow[postgres]"
            )

        db_pool = ConnectionPool(
            database_config.conninfo,
            min_size=2,
            max_size=database_config.max_pool_size,
            timeout=database_config.timeout,
        )

        return cls(
            critical_watermark,
            max_writes,
            blob_path,
            compress,
            blob_directory_depth,
            db_pool
        )

    def _init_database(self):
        with self.db_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        email_address TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_email 
                    ON sessions(email_address)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sessions_updated_at 
                    ON sessions(updated_at)
                """)
            conn.commit()

    def store_multi(
            self,
            models: List[GenieModel | RetrievableModel],
    ) -> Tuple[List[str], List[str]]:
        succeeded, failed = self._write_multi(models)
        if not succeeded:
            return [], [model.session_id for model in models]

        with self.db_pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.executemany(_UPSERT_SQL, succeeded)
                except Exception as e:
                    conn.rollback()
                    logger.error(
                        "Failed to upsert {nr_sessions} sessions: {exc}, removing files",
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
                    return [], [model.session_id for model in models]

            conn.commit()
            logger.info("Successfully stored {count} sessions", count=len(succeeded))
            return [s[0] for s in succeeded], failed

    def checkpoint(self):
        pass

    def get_sessions_for_user(self, user: User) -> list[str]:
        if not user or not user.email:
            return []

        with self.db_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT session_id FROM sessions WHERE email_address = %s",
                    (user.email,)
                )
                return [row[0] for row in cur.fetchall()]
