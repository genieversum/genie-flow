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
