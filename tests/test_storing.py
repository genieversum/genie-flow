import random
import uuid

import pytest
from snappy import snappy

from genie_flow.genie import GenieModel
from genie_flow.model.dialogue import DialogueElement
from genie_flow.session_lock import SessionLockManager



@pytest.fixture
def genie_model():
    return GenieModel(
        session_id=uuid.uuid4().hex,
        dialogue=[
            DialogueElement(
                actor=random.choice(["system", "assistant", "user"]),
                actor_text=" ".join(
                    random.choices(
                        [
                            "aap", "noot", "mies", "wim", "zus", "jet",
                            "teun", "vuur", "gijs", "lam", "kees", "bok",
                            "weide", "does", "hok", "duif", "schapen"
                        ],
                        k=32
                    )
                )
            )
            for _ in range(50)
        ]
    )

def test_serialize():
    sm = SessionLockManager(
        None,
        None,
        None,
        120,
        120,
        120,
        False,
        "genie-flow-test",
    )
    m = GenieModel(
        session_id=uuid.uuid4().hex,
    )
    s = sm._serialize(m)

    assert s == b"0:0:{\"session_id\":\""+m.session_id.encode("utf-8")+b"\"}"

def test_serialize_compressed():
    sm = SessionLockManager(
        None,
        None,
        None,
        120,
        120,
        120,
        True,
        "genie-flow-test",
    )
    m = GenieModel(
        session_id=uuid.uuid4().hex,
    )
    s = sm._serialize(m)

    json_dump = "{\"session_id\":\""+m.session_id+"\"}"
    json_compressed = snappy.compress(json_dump)

    assert s == b"0:1:"+json_compressed


def test_deserialize():
    sm = SessionLockManager(
        None,
        None,
        None,
        120,
        120,
        120,
        True,
        "genie-flow-test",
    )

    s = b'0:1:1\xc0{"session_id":"efb2e397b4554ea2998dd3182e6a6190"}'
    m = sm._deserialize(s, GenieModel)

    assert isinstance(m, GenieModel)
    assert m.session_id == "efb2e397b4554ea2998dd3182e6a6190"


def test_deserialize_deserialize(genie_model):
    sm = SessionLockManager(
        None,
        None,
        None,
        120,
        120,
        120,
        True,
        "genie-flow-test",
    )
    s = sm._serialize(genie_model)
    mm = sm._deserialize(s, GenieModel)

    print(s)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_serialize_deserialize_schema_version(genie_model):
    sm = SessionLockManager(
        None,
        None,
        None,
        120,
        120,
        120,
        True,
        "genie-flow-test",
    )
    s = sm._serialize(genie_model)

    # alter the version number of the serialized payload
    s = b"1" + s[1:]

    with pytest.raises(ValueError):
        sm._deserialize(s, GenieModel)

import pytest
from unittest.mock import Mock, patch
from genie_flow.session_lock import SessionLockManager
from genie_flow.genie import GenieModel


@pytest.fixture
def mock_redis():
    return Mock()

@pytest.fixture
def session_manager(mock_redis):
    return SessionLockManager(
        redis_client=mock_redis,
        redis_lock_client=mock_redis,
        redis_store_client=mock_redis,
        lock_timeout=120,
        store_timeout=120,
        lock_retry_timeout=120,
        compress=False,
        prefix="genie-flow-test"
    )

def test_lock_acquisition_success(session_manager, mock_redis):
    session_id = "test-session"
    mock_redis.set.return_value = True

    result = session_manager.acquire_lock(session_id)

    assert result is True
    mock_redis.set.assert_called_once()
    assert mock_redis.set.call_args[0][0].startswith("genie-flow-test:lock:")

def test_lock_acquisition_failure(session_manager, mock_redis):
    session_id = "test-session"
    mock_redis.set.return_value = False

    result = session_manager.acquire_lock(session_id)

    assert result is False
    mock_redis.set.assert_called_once()

def test_lock_release(session_manager, mock_redis):
    session_id = "test-session"

    session_manager.release_lock(session_id)

    mock_redis.delete.assert_called_once()
    assert mock_redis.delete.call_args[0][0].startswith("genie-flow-test:lock:")

@pytest.mark.asyncio
async def test_store_session(session_manager, mock_redis, genie_model):
    session_id = genie_model.session_id

    await session_manager.store_session(genie_model)

    mock_redis.set.assert_called_once()
    # Verify the key starts with the correct prefix
    assert mock_redis.set.call_args[0][0].startswith("genie-flow-test:store:")

@pytest.mark.asyncio
async def test_load_session_existing(session_manager, mock_redis):
    session_id = "test-session"
    mock_redis.get.return_value = b"0:0:{\"session_id\":\"test-session\"}"

    result = await session_manager.load_session(session_id)

    assert isinstance(result, GenieModel)
    assert result.session_id == session_id
    mock_redis.get.assert_called_once()

@pytest.mark.asyncio
async def test_load_session_not_found(session_manager, mock_redis):
    session_id = "test-session"
    mock_redis.get.return_value = None

    result = await session_manager.load_session(session_id)

    assert result is None
    mock_redis.get.assert_called_once()

def test_lock_key_generation(session_manager):
    session_id = "test-session"
    expected_key = "genie-flow-test:lock:test-session"

    key = session_manager._lock_key(session_id)

    assert key == expected_key

def test_store_key_generation(session_manager):
    session_id = "test-session"
    expected_key = "genie-flow-test:store:test-session"

    key = session_manager._store_key(session_id)

    assert key == expected_key

@pytest.mark.asyncio
async def test_clear_session(session_manager, mock_redis):
    session_id = "test-session"

    await session_manager.clear_session(session_id)

    mock_redis.delete.assert_called_once()
    assert mock_redis.delete.call_args[0][0].startswith("genie-flow-test:store:")