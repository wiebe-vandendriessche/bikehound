import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from test_match import cfg

from bikehound.config import Group
from bikehound.sources import Blocked
from bikehound.sources.facebook import BANDS, parse, search

HTML = (Path(__file__).parent / "fixtures" / "facebook_page.html").read_text()


def test_parse_maps_fields():
    a, b, c = sorted(parse(HTML), key=lambda l: l.id)
    assert (a.id, a.platform, a.title) == ("9000000001", "facebook", "Cortina E-U4 groen")
    assert a.url == "https://www.facebook.com/marketplace/item/9000000001/"
    assert (a.price, a.location) == ("250 €", "Gent")
    assert a.photo_urls == ["https://images.example.test/f1.jpg"]
    assert a.posted_at == datetime.fromtimestamp(1791289246, UTC).astimezone().date()
    assert (b.photo_urls, b.location) == ([], "Leuven")
    assert (c.price, c.location, c.photo_urls) == ("", "", [])


def page(*listings):
    """A page embedding (id, day) listings the way Facebook does."""
    edges = [
        {"node": {"listing": {"__typename": "GroupCommerceProductItem", "id": i,
                              "creation_time": int(datetime(2026, 10, d, 12, tzinfo=UTC).timestamp()),
                              "marketplace_listing_title": "fiets"}}}
        for i, d in listings
    ]  # fmt: skip
    return f'<script type="application/json">{json.dumps({"edges": edges})}</script>'


class FakeSite:
    def __init__(self, bands, far=""):
        self.bands, self.far, self.calls = bands, far, []

    def __call__(self, url):
        u = urlparse(url)
        self.calls.append((u.path, parse_qs(u.query)))
        if u.path.endswith("/search"):
            return self.far
        return self.bands.get(parse_qs(u.query)["minPrice"][0], "")


def test_near_loads_every_band_unions_and_drops_old():
    site = FakeSite({"0": page(("a", 6), ("b", 5)), "100": page(("b", 5), ("c", 1))})
    found = search(cfg(keywords={}), date(2026, 10, 4), fetch=site)
    assert sorted(l.id for l in found) == ["a", "b"]  # b once, c before since
    assert [c[1]["minPrice"][0] for c in site.calls] == [str(lo) for lo, _ in BANDS]
    assert site.calls[0][0] == "/marketplace/brussels/bicycles"
    assert "maxPrice" not in site.calls[-1][1]  # the top band is open-ended


def test_far_uses_model_words_in_the_country_area():
    site = FakeSite({"0": page(("a", 6))}, far=page(("z", 6)))
    c = cfg(country="NL", keywords={"model": Group(["e-u4"], 0.4)})
    found = search(c, date(2026, 10, 1), max_pages=1, fetch=site)
    assert sorted(l.id for l in found) == ["a", "z"]
    assert site.calls[-1] == ("/marketplace/amsterdam/search", site.calls[-1][1])
    assert site.calls[-1][1]["query"] == ["e-u4"]


def test_all_bands_empty_blocks():
    with pytest.raises(Blocked):
        search(cfg(keywords={}), date(2026, 10, 1), fetch=FakeSite({}))
