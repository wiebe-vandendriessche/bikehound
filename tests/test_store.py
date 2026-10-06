from datetime import UTC, datetime

from bikehound.store import Store


def test_last_ok_per_platform(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    t1, t2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
    store.mark_ok("2dehands", t1)
    store.mark_ok("2dehands", t2)
    assert store.last_ok("2dehands") == t2
    assert store.last_ok("vinted") is None
