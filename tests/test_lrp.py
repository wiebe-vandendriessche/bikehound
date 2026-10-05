import json
from datetime import date
from pathlib import Path

import pytest
from test_match import cfg

from bikehound.config import Group
from bikehound.sources import Blocked
from bikehound.sources.lrp import LIMIT, parse, parse_date, search

RAW = json.loads((Path(__file__).parent / "fixtures" / "lrp_search.json").read_text())
REF = date(2026, 10, 5)


def test_parse_maps_fields():
    a, b, c, d = parse(RAW, "2dehands", REF)
    assert a.id == "m1000000004"
    assert (
        a.url
        == "https://www.2dehands.be/v/fietsen-en-brommers/elektrische-fietsen/m1000000004-cortina-e-u4"
    )
    assert a.description.endswith("Ophalen in Gent...")  # the longer of the two
    assert (a.price, a.location, a.posted_at) == ("EUR 1250", "Gent", REF)
    assert a.photo_urls == ["https://images.example.test/a.jpg?rule=83"]
    assert b.photo_urls == ["https://images.example.test/b.jpg?rule=82"]  # imageUrls fallback
    assert (b.price, b.posted_at) == ("SEE_DESCRIPTION", date(2026, 10, 4))
    assert (c.posted_at, c.photo_urls) == (date(2026, 9, 18), [])
    assert (d.price, d.location, d.posted_at) == ("FREE", "", None)


def test_parse_date():
    assert parse_date("Eergisteren", REF) == date(2026, 10, 3)
    assert parse_date("2 okt 26", REF) == date(2026, 10, 2)
    assert parse_date("12 mrt. 25", REF) == date(2025, 3, 12)
    assert parse_date("garbage", REF) is None


def page(ids, day):
    items = [{"itemId": f"m{i}", "title": "fiets", "date": day} for i in ids]
    return {"listings": items}


class FakeAPI:
    """Serves `pages` per search kind, recording each request."""

    def __init__(self, near, far=()):
        self.near, self.far, self.calls = near, list(far), []

    def __call__(self, params):
        p = dict(params)
        self.calls.append(p)
        pages = self.near if "postcode" in p else self.far
        n = p["offset"] // LIMIT
        return pages[n] if n < len(pages) else {"listings": []}


def full(start, day):
    return page(range(start, start + LIMIT), day)


def test_stops_when_page_ends_before_since():
    api = FakeAPI(near=[full(0, "Vandaag"), full(100, "1 okt 26"), full(200, "1 okt 26")])
    found = search("2dehands", cfg(country="BE", keywords={}), date(2026, 10, 3), fetch=api)
    assert len(api.calls) == 2 and len(found) == 200


def test_max_pages_and_dedupe_across_near_and_far():
    api = FakeAPI(near=[full(0, "Vandaag")] * 3, far=[page([5, 999], "Vandaag")])
    c = cfg(country="BE", keywords={"model": Group(["e-u4"], 0.4)})
    found = search("2dehands", c, date(2026, 1, 1), max_pages=1, fetch=api)
    assert len(api.calls) == 2  # one near page, one far page
    assert len(found) == LIMIT + 1  # m5 seen in both
    assert api.calls[1]["query"] == "e-u4"


def test_near_only_on_home_site():
    api = FakeAPI(near=[], far=[page([1], "Vandaag")])
    c = cfg(country="BE", keywords={"brand": Group(["cortina"], 0.3)})
    assert len(search("marktplaats", c, date(2026, 1, 1), fetch=api)) == 1
    assert all("postcode" not in call for call in api.calls)


def test_empty_near_or_api_errors_block():
    with pytest.raises(Blocked):
        search("2dehands", cfg(country="BE"), REF, fetch=FakeAPI(near=[]))
    with pytest.raises(Blocked):
        search("2dehands", cfg(country="BE"), REF, fetch=lambda p: {"hasErrors": True})
