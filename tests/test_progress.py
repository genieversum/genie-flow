import ulid

from genie_flow.celery import ProgressLoggingTask


def test_progress_start(session_lock_manager_connected):
    session_id = str(ulid.new().uuid)
    invocation_id = "some-task-" + ulid.new().str
    session_lock_manager_connected.progress_start(session_id, invocation_id, 8)

    key = session_lock_manager_connected._create_key(
        "progress",
        None,
        session_id,
    )
    progress_store = session_lock_manager_connected.redis_progress_store
    assert progress_store.exists(key)
    assert progress_store.hget(key, f"{invocation_id}:todo") == b"8"
    assert progress_store.hget(key, f"{invocation_id}:done") == b"0"
    assert progress_store.hget(key, f"{invocation_id}:tombstone") == b"f"

    assert session_lock_manager_connected.progress_exists(session_id)
    assert session_lock_manager_connected.progress_exists(session_id, invocation_id)
    assert not session_lock_manager_connected.progress_exists(session_id, "some other")
    assert session_lock_manager_connected.progress_status(session_id) == (8, 0)


def test_progress_done(session_lock_manager_connected):
    session_id = str(ulid.new().uuid)
    invocation_id = "some-task-" + ulid.new().str
    session_lock_manager_connected.progress_start(session_id, invocation_id, 8)

    assert session_lock_manager_connected.progress_exists(session_id, invocation_id)

    for i in range(8):
        if i == 7:
            session_lock_manager_connected.progress_tombstone(session_id, invocation_id)
        session_lock_manager_connected.progress_update_done(session_id, invocation_id)
    assert not session_lock_manager_connected.progress_exists(session_id, invocation_id)


def test_progress_update(session_lock_manager_connected):
    session_id = str(ulid.new().uuid)
    invocation_id = "some-task-" + ulid.new().str
    session_lock_manager_connected.progress_start(session_id, invocation_id, 8)

    session_lock_manager_connected.progress_update_done(session_id, invocation_id)
    assert session_lock_manager_connected.progress_status(session_id) == (8, 1)

    session_lock_manager_connected.progress_update_todo(session_id, invocation_id, 8)
    assert session_lock_manager_connected.progress_status(session_id) == (16, 1)


def test_on_success(session_lock_manager_unconnected, monkeypatch):
    session_id = str(ulid.new().uuid)
    invocation_id = "some-task-" + ulid.new().str

    record = []

    monkeypatch.setattr(
        session_lock_manager_unconnected,
        "progress_update_done",
        lambda *args, **kwargs: record.append((*args, dict(**kwargs)))
    )

    task = ProgressLoggingTask()
    task.session_lock_manager = session_lock_manager_unconnected

    task.on_success(
        retval="some return value",
        task_id="some task id",
        args=("A", "B", session_id, "fqn", invocation_id),
        kwargs={},
    )

    assert record[0] == (session_id, invocation_id, {})


def test_on_failure(session_lock_manager_unconnected, monkeypatch):
    session_id = str(ulid.new().uuid)
    invocation_id = "some-task-" + ulid.new().str

    record = []

    monkeypatch.setattr(
        session_lock_manager_unconnected,
        "progress_update_done",
        lambda *args, **kwargs: record.append((*args, dict(**kwargs)))
    )

    task = ProgressLoggingTask()
    task.session_lock_manager = session_lock_manager_unconnected

    task.on_failure(
        exc=Exception("some exception"),
        task_id="some task id",
        args=("A", "B", session_id, "fqn", invocation_id),
        kwargs={},
        einfo=None,
    )

    assert record[0] == (session_id, invocation_id, {})
