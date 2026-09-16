import tempfile
import uuid
from pathlib import Path

import pytest

from genie_flow.permanent_storage.abstract_file_store import FileStorageConfig
from genie_flow.permanent_storage.embedded_store import EmbeddedStorageManager
from genie_flow.permanent_storage.postgres_store import PostgresFileStoreManager


@pytest.fixture(scope="session")
def tmpdir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(scope="session")
def file_storage_config(tmpdir):
    tmpdir_path = Path(tmpdir)
    yield FileStorageConfig(
        file_storage_url=f"file://{tmpdir_path}/blob",
        compress=False,
        shard_depth=2,
        file_storage_options={},
    )


@pytest.fixture(scope="session")
def file_store_manager(tmpdir, file_storage_config):
        yield EmbeddedStorageManager(
            critical_watermark=30,
            max_writes=32,
            file_storage_config=file_storage_config,
            database_path=f"{tmpdir}/db",
            database_retries=3,
        )


def test_store(file_store_manager, genie_model):
    file_store_manager.store_multi([genie_model])

    db_path = file_store_manager.database_path / "permanent_store.db"
    assert db_path.exists()
    blob_path = "/".join(
        [
            file_store_manager.file_storage_base_path,
            genie_model.session_id[-2:],
            genie_model.session_id[-4:-2],
            f"{genie_model.session_id}.tar",
        ]
    )
    assert file_store_manager.fs.exists(blob_path)
    cursor = file_store_manager._get_connection().execute(
        """
            SELECT * FROM sessions
            WHERE session_id = ?
        """,
        (genie_model.session_id,)
    )
    assert len(cursor.fetchall())== 1


def test_store_multiple(file_store_manager, genie_model):
    genie_model2 = genie_model.__class__.model_validate(
        genie_model.model_dump(exclude="secondary_store")
    )
    genie_model2.session_id = uuid.uuid4().hex
    genie_model2.secondary_storage = genie_model.secondary_storage

    file_store_manager.store_multi([genie_model, genie_model2])
    cursor = file_store_manager._get_connection().execute(
        """
            SELECT * FROM sessions
            WHERE session_id = ? OR session_id = ?
        """,
        (genie_model.session_id, genie_model2.session_id)
    )
    assert len(cursor.fetchall()) == 2


def test_get_sessions_for_user(file_store_manager, genie_model):
    file_store_manager.store_multi([genie_model])
    user = genie_model.secondary_storage["user_info"]
    user_sessions = file_store_manager.get_sessions_for_user(user)

    assert genie_model.session_id in user_sessions


def test_retrieve(file_store_manager, genie_model):
    file_store_manager.store_multi([genie_model])
    restored = file_store_manager.retrieve(genie_model.session_id)
    restored_dict = restored.model_dump()

    for key, value in genie_model.model_dump().items():
        print(value)
        assert restored_dict[key] == value


def test_room(file_store_manager):
    assert file_store_manager.is_critical(1)
    assert not file_store_manager.is_critical(500)
    assert file_store_manager.remaining_room(1000) == 0
    assert file_store_manager.remaining_room(1) == 31


class MockCursor:
    def __init__(self):
        self.executed_queries = []
        self.executemany_calls = []
        self.fetchall_result = []
        self.fetchone_result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, query, params=None):
        self.executed_queries.append((query, params))

    def executemany(self, query, params_list):
        self.executemany_calls.append((query, params_list))
        self.rowcount = len(params_list) if params_list else 0

    def fetchall(self):
        return self.fetchall_result

    def fetchone(self):
        if self.fetchone_result is not None:
            return self.fetchone_result
        return self.fetchall_result[0] if self.fetchall_result else None

    def fetchmany(self, size=1):
        return self.fetchall_result[:size]

    def close(self):
        pass


class MockConnection:
    def __init__(self):
        self.cursor_calls = []
        self.commit_called = False
        self.rollback_called = False
        self._current_cursor = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def cursor(self):
        mock_cursor = MockCursor()
        self.cursor_calls.append(mock_cursor)
        self._current_cursor = mock_cursor
        return mock_cursor

    def commit(self):
        self.commit_called = True

    def rollback(self):
        self.rollback_called = True

    def close(self):
        pass


class MockConnectionPool:
    def __init__(self):
        self.connections = []
        self.connection_called = False
        self.getconn_called = False
        self.putconn_called = False
        self._current_connection = None

    def connection(self):
        """Context manager for getting a connection (psycopg3 style)"""
        self.connection_called = True
        mock_conn = MockConnection()
        self.connections.append(mock_conn)
        self._current_connection = mock_conn
        return mock_conn

    def getconn(self):
        """Direct connection getter (psycopg2 style)"""
        self.getconn_called = True
        mock_conn = MockConnection()
        self.connections.append(mock_conn)
        self._current_connection = mock_conn
        return mock_conn

    def putconn(self, conn):
        self.putconn_called = True

    def closeall(self):
        pass

    def close(self):
        pass

@pytest.fixture
def mock_postgres_connection_pool():
    return MockConnectionPool()


@pytest.fixture
def postgres_store_manager(tmpdir, file_storage_config, mock_postgres_connection_pool):
    yield PostgresFileStoreManager(
        critical_watermark=30,
        max_writes=32,
        file_storage_config=file_storage_config,
        db_pool=mock_postgres_connection_pool,
    )


def test_postgres_store(postgres_store_manager, genie_model):
    postgres_store_manager.store_multi([genie_model])

    blob_path = "/".join(
        [
            postgres_store_manager.file_storage_base_path,
            genie_model.session_id[-2:],
            genie_model.session_id[-4:-2],
            f"{genie_model.session_id}.tar",
        ]
    )
    assert postgres_store_manager.fs.exists(blob_path)

    assert postgres_store_manager.db_pool.connection_called
    assert 2 == len(
        postgres_store_manager
        .db_pool
        .connections
    )
    assert 1 == len(
        postgres_store_manager
        .db_pool
        .connections[-1]
        .cursor_calls
    )
    assert 1 == len(
        postgres_store_manager
        .db_pool
        .connections[-1]
        .cursor_calls[-1]
        .executemany_calls
    )
    assert "INSERT" in (
        postgres_store_manager
        .db_pool
        .connections[-1]
        .cursor_calls[-1]
        .executemany_calls[-1][0]
    )
    assert [(genie_model.session_id, genie_model.secondary_storage["user_info"].email)] == (
        postgres_store_manager
        .db_pool
        .connections[-1]
        .cursor_calls[-1]
        .executemany_calls[-1][1]
    )