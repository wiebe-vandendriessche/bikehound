"""Facebook Marketplace, logged out: the bikes pages any visitor can open, read through a real
Chromium. No account. Best effort, measured 2026-10-06 (see ARCHITECTURE.md):

- a page embeds only 24 listings and does not load more without a login, and the plain page is
  a stale sample; one page per price band gives far more, and fresher, listings;
- the area can only be chosen by a big-city slug; smaller cities fall back to US listings, and
  radius parameters are ignored.
"""

import json
import logging
import re
from datetime import UTC, date, datetime
from urllib.parse import quote

from . import Blocked, Listing, far_words
from .browser import pages

BASE = "https://www.facebook.com/marketplace"
# verified slugs; an unknown one silently returns San Francisco listings, so never user input
CITY = {"BE": "brussels", "NL": "amsterdam"}
SORT = "sortBy=creation_time_descend&exact=false"
# each band's 24 newest reached 2 to 7 days back around Brussels, so a daily run sees them all
BANDS = ((0, 50), (50, 100), (100, 200), (200, 400), (400, 800), (800, None))
ITEM = "GroupCommerceProductItem"
SCRIPT = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.DOTALL)

log = logging.getLogger(__name__)


def _listing(x: dict) -> Listing:
    geo = (x.get("location") or {}).get("reverse_geocode") or {}
    photo = ((x.get("primary_listing_photo") or {}).get("image") or {}).get("uri")
    return Listing(
        id=x["id"],
        platform="facebook",
        url=f"{BASE}/item/{x['id']}/",
        title=x.get("marketplace_listing_title") or "",
        price=(x.get("listing_price") or {}).get("formatted_amount") or "",
        location=geo.get("city") or "",
        photo_urls=[photo] if photo else [],
        posted_at=datetime.fromtimestamp(x["creation_time"], UTC).astimezone().date(),  # local day
    )


def parse(html: str) -> list[Listing]:
    """The listings embedded in the page's JSON scripts."""
    found: dict[str, Listing] = {}
    for blob in SCRIPT.findall(html):
        if ITEM not in blob:
            continue
        stack = [json.loads(blob)]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if x.get("__typename") == ITEM and "creation_time" in x:
                    found[x["id"]] = _listing(x)
                stack += x.values()
            elif isinstance(x, list):
                stack += x
    return list(found.values())


def search(cfg, since: date, max_pages: int | None = None, fetch=None) -> list[Listing]:
    if fetch is None:
        with pages(cfg, "facebook") as get:
            return search(cfg, since, max_pages, get)
    city = CITY[cfg.country]  # config allows BE and NL only
    found: dict[str, Listing] = {}
    # near: one bikes page per price band (max_pages limits the bands, for `check`)
    for lo, hi in BANDS[:max_pages]:
        band = f"&minPrice={lo}" + (f"&maxPrice={hi}" if hi else "")
        url = f"{BASE}/{city}/bicycles?{SORT}{band}"
        batch = parse(fetch(url))
        log.debug("facebook: %d listings, %s", len(batch), url)
        if batch and (oldest := min(l.posted_at for l in batch)) > since:
            log.warning("facebook: price band %s-%s reached back only to %s; older listings in "
                        "it were not seen", lo, hi or "", oldest)  # fmt: skip
        found |= {l.id: l for l in batch}
    if not found:
        # bikes around a capital are never empty: a login wall, a changed page, or a profile
        # someone logged in to (a logged-in session can be held at a checkpoint)
        raise Blocked(
            "no listings: Facebook may require a login now, or data/profiles/facebook/ is "
            "logged in (delete that folder; this source works logged out)"
        )
    # far: text searches are sparse enough for one page each (10 days deep in the spike)
    for w in far_words(cfg):
        url = f"{BASE}/{city}/search?query={quote(w)}&{SORT}"
        batch = parse(fetch(url))
        log.debug("facebook: %d listings, %s", len(batch), url)
        found |= {l.id: l for l in batch}
    return [l for l in found.values() if l.posted_at >= since]
