from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from test_match import cfg

from bikehound.config import Group
from bikehound.sources import Blocked
from bikehound.sources.lrp import today
from bikehound.sources.vinted import IDS_PER_DAY, NEAR_PAGES, PER_PAGE, parse, search

HTML = (Path(__file__).parent / "fixtures" / "vinted_catalog.html").read_text()
SINCE = date(2026, 10, 5)


def test_parse_maps_fields():
    a, b, c = parse(HTML, "www.vinted.be")  # the favourite-only id has no link, so no listing
    assert (a.id, a.platform) == ("1000000001", "vinted")
    assert a.url == "https://www.vinted.be/items/1000000001-cortina-e-u4-groen"
    assert a.title == "Cortina E-U4 groen, Marque: Cortina, État: Bon état"  # no prices
    assert c.title == "Mountainbike"
    assert (a.price, a.photo_urls) == ("450,00 €", ["https://images.example.test/v1.webp?s=1"])
    assert (b.price, b.photo_urls) == ("80,00 €", [])
    assert c.price == ""  # empty price text never picks up a later number


def card(i):
    return (
        f'<a href="/items/{i}-fiets" data-testid="product-item-id-{i}--overlay-link" title="fiets">'
    )


def full(start):
    return "".join(card(i) for i in range(start, start + PER_PAGE))


class FakeSite:
    """Serves `near` pages for the bike-category search, `far` pages for text searches."""

    def __init__(self, near, far=()):
        self.near, self.far, self.calls = near, list(far), []

    def __call__(self, url):
        q = parse_qs(urlparse(url).query)
        self.calls.append(q)
        pages = self.far if "search_text" in q else self.near
        n = int(q["page"][0]) - 1
        return pages[n] if n < len(pages) else ""


def test_near_reads_until_short_page_or_cap():
    site = FakeSite(near=[full(0), full(100), card(999)])
    assert len(search(cfg(keywords={}), SINCE, fetch=site)) == 2 * PER_PAGE + 1
    assert site.calls[0]["catalog[]"] == ["4345", "4346"]
    site = FakeSite(near=[full(i * 100) for i in range(20)])
    search(cfg(keywords={}), SINCE, fetch=site)
    assert len(site.calls) == NEAR_PAGES


def test_far_uses_model_words_in_cycling_and_dedupes():
    site = FakeSite(near=[card(1) + card(2)], far=[card(2) + card(3)])
    c = cfg(country="NL", keywords={"model": Group(["e-u4"], 0.4)})
    found = search(c, SINCE, max_pages=1, fetch=site)
    assert sorted(l.id for l in found) == ["1", "2", "3"]
    assert site.calls[1]["search_text"] == ["e-u4"] and site.calls[1]["catalog[]"] == ["4333"]
    assert found[0].url.startswith("https://www.vinted.nl/")


def test_empty_near_blocks():
    with pytest.raises(Blocked):
        search(cfg(), SINCE, fetch=FakeSite(near=[]))


def test_since_becomes_an_id_cutoff():
    # since = yesterday: keep the 2 newest days of ids, counted back from the newest one
    top, day = 100 * IDS_PER_DAY, IDS_PER_DAY
    bumped = card(top - 30 * day)  # an old listing bumped to the top keeps its old id
    page1 = bumped + "".join(card(top - i) for i in range(PER_PAGE - 1))
    page2 = card(top - day) + "".join(card(top - 3 * day - i) for i in range(PER_PAGE - 1))
    page3 = "".join(card(top - 4 * day - i) for i in range(PER_PAGE))
    site = FakeSite(near=[page1, page2, page3, page1], far=[card(top + 1) + bumped])
    c = cfg(keywords={"model": Group(["e-u4"], 0.4)})
    found = {int(l.id) for l in search(c, today() - timedelta(days=1), fetch=site)}
    assert min(found) >= top - 2 * day and len(found) == (PER_PAGE - 1) + 1 + 1
    assert len(site.calls) == 3 + 1  # near ends at the first page with nothing new
