import tempfile
import uuid
from pathlib import Path

import pytest

from genie_flow.permanent_storage.embedded_store import EmbeddedStorageManager


@pytest.fixture(scope="session")
def file_store_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        yield EmbeddedStorageManager(
            critical_watermark=30,
            max_writes=32,
            blob_url=f"file://{tmpdir_path}/blob",
            compress=False,
            blob_directory_depth=2,
            database_path=tmpdir_path / "db",
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
