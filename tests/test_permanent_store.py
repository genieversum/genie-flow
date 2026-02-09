import shutil
import tempfile
from pathlib import Path

import pytest

from genie_flow.permanent_storage.file_store import FileStorageManager


@pytest.fixture(scope="session")
def file_store_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        yield FileStorageManager(
            database_path=tmpdir_path / "db",
            blob_path=tmpdir_path / "blob",
            compress=False,
        )


def test_store(file_store_manager, genie_model):
    file_store_manager.store_multi([genie_model])

    db_path = file_store_manager.database_path / "permanent_store.db"
    assert db_path.exists()
    blob_path = (
        file_store_manager.blob_path
        / genie_model.session_id[-2:]
        / genie_model.session_id[-4:-2]
        / f"{genie_model.session_id}.tar"
    )
    assert blob_path.exists()
    cursor = file_store_manager._get_connection().execute(
        """
            SELECT * FROM sessions
            WHERE session_id = ?
        """,
        (genie_model.session_id,)
    )
    assert len(cursor.fetchall())== 1


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
