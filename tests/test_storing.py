import uuid

from genie_flow.genie import GenieModel
from genie_flow.session_lock import SessionLockManager


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