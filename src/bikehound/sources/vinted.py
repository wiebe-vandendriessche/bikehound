"""Vinted: the catalog pages a logged-out visitor sees, read through a real Chromium.

The JSON API (/api/v2/catalog/items) refuses direct calls with 403, so this parses the
server-rendered catalog HTML instead. Facts measured on vinted.be: see ARCHITECTURE.md.
"""

from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlencode

from . import Blocked, Listing, far_words
from .browser import pages
from .lrp import today

# bikes and e-bikes, each including its subcategories. Kids' bikes (4347) are left out: about
# 1000 a day on vinted.be, which alone would fill the 10-page cap in under a day.
BIKES = (4345, 4346)
CYCLING = 4333  # far search: bikes plus parts and accessories, never shoes named "Gazelle"
PER_PAGE = 96
NEAR_PAGES = 10  # the site returns nothing past page 10; ~17 bikes a day, so ~8 weeks back
FAR_PAGES = 2
# Item ids are one global counter. Measured growth: 10.8M/day (19 h), 11.5M/day (8 weeks),
# 8.3M/day (12-month average). Too low a rate only reads further back, so stay below them all.
# ponytail: measured 2026-10-06; should Vinted fall below this rate, the cutoff lands after
# `since` and the oldest listings are missed: re-measure from two items' upload times
IDS_PER_DAY = 8_000_000
TESTID = "product-item-id-"


class _Cards(HTMLParser):
    """Collects the fields of each catalog card, keyed by item id."""

    def __init__(self):
        super().__init__()
        self.cards: dict[str, dict] = {}
        self._price: dict | None = None  # card whose price text comes next

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        tid = a.get("data-testid") or ""
        if not tid.startswith(TESTID):
            return
        iid, _, part = tid.removeprefix(TESTID).partition("--")
        card = self.cards.setdefault(iid, {})
        if part == "overlay-link":
            # the title attribute also carries brand, condition and price: good for keywords
            card["href"], card["title"] = a.get("href") or "", a.get("title") or ""
        elif part == "image--img" and a.get("src"):
            card["photo"] = a["src"]
        elif part == "price-text":
            self._price = card

    def handle_data(self, data):
        if self._price is not None and data.strip():
            self._price["price"] = data.strip()
            self._price = None

    def handle_endtag(self, tag):
        self._price = None


def parse(html: str, host: str) -> list[Listing]:
    p = _Cards()
    p.feed(html)
    return [
        Listing(
            id=iid,
            platform="vinted",
            url=f"https://{host}{c['href'].split('?')[0]}",
            title=c["title"],
            price=c.get("price", ""),
            photo_urls=[c["photo"]] if "photo" in c else [],
        )
        for iid, c in p.cards.items()
        if c.get("href") and iid.isdigit()
    ]


def search(cfg, since: date, max_pages: int | None = None, fetch=None) -> list[Listing]:
    # cards carry no date, so `since` becomes an id cutoff estimated from the newest id
    host = f"www.vinted.{cfg.country.lower()}"
    if fetch is None:
        with pages(cfg, "vinted") as get:
            return search(cfg, since, max_pages, get)
    # no radius on Vinted (shipping marketplace): near is the whole country's bike categories
    runs = [("near", [("catalog[]", c) for c in BIKES], NEAR_PAGES)]
    runs += [("far", [("catalog[]", CYCLING), ("search_text", w)], FAR_PAGES) for w in far_words(cfg)]  # fmt: skip
    found: dict[str, Listing] = {}
    cutoff = None
    for kind, params, cap in runs:
        for page in range(1, min(cap, max_pages or cap) + 1):
            q = urlencode(params + [("order", "newest_first"), ("page", page)])
            batch = parse(fetch(f"https://{host}/catalog?{q}"), host)
            if kind == "near" and page == 1:
                if not batch:
                    # newest bikes in a whole country are never empty: breakage, not a quiet day
                    raise Blocked("near search returned nothing")
                days = (today() - since).days + 1
                cutoff = max(int(l.id) for l in batch) - days * IDS_PER_DAY
            # "newest first" is by bump, and a bumped listing keeps its old id: drop each old
            # one, but only a page with nothing after the cutoff ends the search (as D11)
            new = [l for l in batch if int(l.id) >= cutoff]
            for listing in new:
                found.setdefault(listing.id, listing)
            if len(batch) < PER_PAGE or not new:
                break
    return list(found.values())
