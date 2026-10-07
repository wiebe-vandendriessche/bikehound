from datetime import UTC, datetime

from bikehound.match import Score
from bikehound.sources import Listing
from bikehound.store import Store


def test_last_ok_per_platform(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    t1, t2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
    store.mark_ok("2dehands", t1)
    store.mark_ok("2dehands", t2)
    assert store.last_ok("2dehands") == t2
    assert store.last_ok("vinted") is None


def test_record_keeps_details_for_the_gallery_and_prunes(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    l = Listing("1", "vinted", "https://x.test/1", "a bike", price="100", photo_urls=["https://p"])
    store.record(l, Score(0.7, photo=0.7), True)
    [r] = store.listings()
    assert (r["url"], r["title"], r["photo"], r["notified"]) == (
        "https://x.test/1",
        "a bike",
        "https://p",
        1,
    )
    for t in ("seen", "listings"):
        store.db.execute(f"UPDATE {t} SET first_seen='2000-01-01'")
    store.record_run(datetime.now(UTC), True, "ok")
    assert store.listings() == []
