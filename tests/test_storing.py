import time
import uuid
from ctypes import c_bool
from multiprocessing import Process, Value

import pytest
import ulid
from pydantic import Field
from snappy import snappy

from genie_flow.genie import GenieModel
from genie_flow.model.dialogue import DialogueElement
from genie_flow.model.user import User
from genie_flow.model.versioned import VersionedModel
from genie_flow.utils import get_fully_qualified_name_from_class


def test_serialize():
    m = GenieModel(session_id=uuid.uuid4().hex)
    s = m.serialize()

    model_dump_json = m.model_dump_json()

    assert s == b"0:0:"+model_dump_json.encode("utf-8")

def test_serialize_compressed():
    m = GenieModel(session_id=uuid.uuid4().hex)
    s = m.serialize(compression=True)

    json_dump = m.model_dump_json()
    json_compressed = snappy.compress(json_dump)

    assert s == b"0:1:"+json_compressed


def test_deserialize():
    s = b'0:1:1\xc0{"session_id":"efb2e397b4554ea2998dd3182e6a6190"}'
    m = GenieModel.deserialize(s)

    assert isinstance(m, GenieModel)
    assert m.session_id == "efb2e397b4554ea2998dd3182e6a6190"


def test_deserialize_deserialize(genie_model):
    s = genie_model.serialize(compression=True)
    mm = GenieModel.deserialize(s)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_serialize_deserialize_schema_version(genie_model):
    s = genie_model.serialize(compression=True)

    # alter the version number of the serialized payload
    s = b"1" + s[1:]

    with pytest.raises(ValueError):
        GenieModel.deserialize(s)


def test_create_key_session_id(session_lock_manager_unconnected):
    session_id = "test-session"
    expected_key = "genie-flow-test:lock::test-session"
    key = session_lock_manager_unconnected._create_key("lock", None, session_id)
    assert key == expected_key


def test_create_key_model_class(session_lock_manager_unconnected):
    session_id = "test-session"
    model_class = GenieModel
    expected_key = "genie-flow-test:lock:GenieModel:test-session"
    key = session_lock_manager_unconnected._create_key("lock", model_class, session_id)
    assert key == expected_key


def test_create_key_model_instance(session_lock_manager_unconnected):
    session_id = "test-session"
    model_instance = GenieModel(session_id=session_id)
    expected_key = "genie-flow-test:lock:GenieModel:test-session"
    key = session_lock_manager_unconnected._create_key("lock", model_instance, session_id)
    assert key == expected_key


def test_store_model(session_lock_manager_connected, genie_model):
    session_lock_manager_connected.store_model(genie_model)

    key = "genie-flow-test:object:GenieModel:"+genie_model.session_id

    assert session_lock_manager_connected.redis_object_store.exists(key)


def test_store_retrieve_model(session_lock_manager_connected, genie_model):
    session_lock_manager_connected.store_model(genie_model)
    mm = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_store_retrieve_model_compressed(session_lock_manager_connected, genie_model):
    session_lock_manager_connected.compression = True

    session_lock_manager_connected.store_model(genie_model)
    mm = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)

    assert isinstance(mm, GenieModel)
    assert mm.session_id == genie_model.session_id
    for i, de in enumerate(mm.dialogue):
        assert de.actor == genie_model.dialogue[i].actor
        assert de.actor_text == genie_model.dialogue[i].actor_text


def test_persist_secondary_store(session_lock_manager_connected, genie_model, user):
    genie_model.secondary_storage["test"] = user

    session_lock_manager_connected.store_model(genie_model)
    mm = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)
    assert mm.secondary_storage["test"].email == "aap@noot.com"

    secondary_store_key = session_lock_manager_connected._create_key(
        "secondary",
        genie_model.__class__,
        genie_model.session_id,
    )
    persisted_fields = session_lock_manager_connected.redis_object_store.hgetall(secondary_store_key)
    user_fqn = get_fully_qualified_name_from_class(user)
    assert persisted_fields[b"test"].startswith(user_fqn.encode("utf-8"))


def test_not_persisting_secondary_store(session_lock_manager_connected, genie_model, user):
    genie_model.secondary_storage["test"] = user

    session_lock_manager_connected.store_model(genie_model)

    with session_lock_manager_connected.get_locked_model(
            genie_model.session_id,
            genie_model.__class__
    ) as model:
        model.actor = "test-actor"
        model.secondary_storage["test"].lastname = "TESTING123"

    mm = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)

    assert mm.actor == "test-actor"
    assert mm.secondary_storage["test"].lastname == genie_model.secondary_storage["test"].lastname


def test_delete_from_secondary_store(session_lock_manager_connected, genie_model, user):
    genie_model.secondary_storage["test"] = user

    session_lock_manager_connected.store_model(genie_model)

    mm = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)
    del mm.secondary_storage["test"]

    session_lock_manager_connected.store_model(mm)

    mm = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)
    assert "test" not in mm.secondary_storage


def test_locked_model(session_lock_manager_connected, genie_model):

    def parallel_lock_getter(wait_indicator: Value):
        wait_indicator.value = True
        with session_lock_manager_connected.get_locked_model(
            genie_model.session_id,
            genie_model.__class__
        ) as mm_p:
            wait_indicator.value = False

            assert isinstance(mm_p, GenieModel)
            assert mm_p.session_id == genie_model.session_id

    session_lock_manager_connected.store_model(genie_model)

    waiting_for_lock = Value(c_bool, False)
    with session_lock_manager_connected.get_locked_model(
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


def test_auto_save(session_lock_manager_connected, genie_model):
    session_lock_manager_connected.store_model(genie_model)
    with session_lock_manager_connected.get_locked_model(
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

    m = session_lock_manager_connected.get_model(genie_model.session_id, genie_model.__class__)
    assert len(m.dialogue) == len(genie_model.dialogue) + 1
    assert m.dialogue[-1].actor == "assistant"
    assert m.actor == "test-actor"


def test_exclude_computed_fields(example_computed_field):
    s = example_computed_field.serialize(compression=False)
    assert b"relevant_letters_digits" not in s


def test_include_computed_fields(example_computed_field):
    s = example_computed_field.serialize(include={"relevant_letters_digits"})
    assert b"relevant_letters_digits" in s
