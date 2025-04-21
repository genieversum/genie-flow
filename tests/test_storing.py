import time
import uuid
from ctypes import c_bool
from multiprocessing import Process, Value

import pytest
from snappy import snappy

from genie_flow.genie import GenieModel
from genie_flow.model.dialogue import DialogueElement


def test_serialize(session_manager_unconnected):
    m = GenieModel(session_id=uuid.uuid4().hex)
    s = session_manager_unconnected._serialize(m)

    assert s == b"0:0:{\"session_id\":\""+m.session_id.encode("utf-8")+b"\"}"

def test_serialize_compressed(session_manager_unconnected):
    session_manager_unconnected.compression = True

    m = GenieModel(session_id=uuid.uuid4().hex)
    s = session_manager_unconnected._serialize(m)

    json_dump = "{\"session_id\":\""+m.session_id+"\"}"
    json_compressed = snappy.compress(json_dump)

    assert s == b"0:1:"+json_compressed


def test_deserialize(session_manager_unconnected):
    s = b'0:1:1\xc0{"session_id":"efb2e397b4554ea2998dd3182e6a6190"}'
    m = session_manager_unconnected._deserialize(s, GenieModel)

    assert isinstance(m, GenieModel)
    assert m.session_id == "efb2e397b4554ea2998dd3182e6a6190"


def test_deserialize_deserialize(session_manager_unconnected, genie_model):
    session_manager_unconnected.compression = True

    s = session_manager_unconnected._serialize(genie_model)
    mm = session_manager_unconnected._deserialize(s, GenieModel)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_serialize_deserialize_schema_version(session_manager_unconnected, genie_model):
    s = session_manager_unconnected._serialize(genie_model)

    # alter the version number of the serialized payload
    s = b"1" + s[1:]

    with pytest.raises(ValueError):
        session_manager_unconnected._deserialize(s, GenieModel)


def test_create_key_session_id(session_manager_unconnected):
    session_id = "test-session"
    expected_key = "genie-flow-test:lock::test-session"
    key = session_manager_unconnected._create_key("lock", None, session_id)
    assert key == expected_key


def test_create_key_model_class(session_manager_unconnected):
    session_id = "test-session"
    model_class = GenieModel
    expected_key = "genie-flow-test:lock:GenieModel:test-session"
    key = session_manager_unconnected._create_key("lock", model_class, session_id)
    assert key == expected_key


def test_create_key_model_instance(session_manager_unconnected):
    session_id = "test-session"
    model_instance = GenieModel(session_id=session_id)
    expected_key = "genie-flow-test:lock:GenieModel:test-session"
    key = session_manager_unconnected._create_key("lock", model_instance, session_id)
    assert key == expected_key


def test_store_model(session_manager_connected, genie_model):
    session_manager_connected.store_model(genie_model)

    key = "genie-flow-test:object:GenieModel:"+genie_model.session_id

    assert session_manager_connected.redis_object_store.exists(key)
    print(session_manager_connected.redis_object_store.get(key))


def test_store_retrieve_model(session_manager_connected, genie_model):
    session_manager_connected.store_model(genie_model)
    mm = session_manager_connected.get_model(genie_model.session_id, genie_model.__class__)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_store_retrieve_model_compressed(session_manager_connected, genie_model):
    session_manager_connected.compression = True

    session_manager_connected.store_model(genie_model)
    mm = session_manager_connected.get_model(genie_model.session_id, genie_model.__class__)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_locked_model(session_manager_connected, genie_model):

    def parallel_lock_getter(wait_indicator: Value):
        wait_indicator.value = True
        with session_manager_connected.get_locked_model(
            genie_model.session_id,
            genie_model.__class__
        ) as mm_p:
            wait_indicator.value = False

            assert isinstance(mm_p, GenieModel)
            assert mm_p.session_id == genie_model.session_id

    session_manager_connected.store_model(genie_model)

    waiting_for_lock = Value(c_bool, False)
    with session_manager_connected.get_locked_model(
            genie_model.session_id,
            genie_model.__class__
    ) as mm:
        assert isinstance(mm, GenieModel)
        assert mm.session_id == genie_model.session_id

        p = Process(target=parallel_lock_getter, args=(waiting_for_lock,))
        p.start()

        time.sleep(0.1)
        # the parallel process should be waiting for the lock
        assert waiting_for_lock.value == True

    time.sleep(0.1)
    # the parallel process should have the lock now
    assert waiting_for_lock.value == False

    p.join()


def test_auto_save(session_manager_connected, genie_model):
    session_manager_connected.store_model(genie_model)
    with session_manager_connected.get_locked_model(
            genie_model.session_id,
            genie_model.__class__
    ) as mm:
        mm.dialogue.append(
            DialogueElement(
                actor="assistant",
                actor_text="test"
            )
        )
        mm.actor = "test-actor"

    m = session_manager_connected.get_model(genie_model.session_id, genie_model.__class__)
    assert len(m.dialogue) == len(genie_model.dialogue) + 1
    assert m.dialogue[-1].actor == "assistant"
    assert m.actor == "test-actor"

def test_progress_start(session_manager_connected):
    session_id = uuid.uuid4().hex
    session_manager_connected.progress_start(session_id, "test-task", 8)

    key = session_manager_connected._create_key("progress", None, session_id)
    progress_store = session_manager_connected.redis_progress_store
    assert progress_store.exists(key)
    assert progress_store.hget(key, "total_nr_subtasks") == b"8"
    assert progress_store.hget(key, "nr_subtasks_executed") == b"0"

    assert session_manager_connected.progress_exists(session_id)
    assert session_manager_connected.progress_status(session_id) == (8, 0)


def test_progress_done(session_manager_connected):
    session_id = uuid.uuid4().hex
    session_manager_connected.progress_start(session_id, "test-task", 8)

    assert session_manager_connected.progress_exists(session_id)

    session_manager_connected.progress_finished(session_id)
    assert not session_manager_connected.progress_exists(session_id)


def test_progress_update(session_manager_connected):
    session_id = uuid.uuid4().hex
    session_manager_connected.progress_start(session_id, "test-task", 8)

    session_manager_connected.progress_update_done(session_id)
    assert session_manager_connected.progress_status(session_id) == (8, 1)

    session_manager_connected.progress_update_todo(session_id, 8)
    assert session_manager_connected.progress_status(session_id) == (16, 1)
