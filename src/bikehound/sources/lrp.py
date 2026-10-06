"""2dehands.be and Marktplaats.nl: one shared JSON search API (/lrp/api/search)."""

import random
import time
from datetime import date, datetime, timedelta

import httpx

from . import Blocked, Listing, far_words

HOSTS = {"2dehands": ("www.2dehands.be", "BE"), "marktplaats": ("www.marktplaats.nl", "NL")}
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)
BIKES_L1 = 445
# every bike subcategory of 445; leaves out parts, accessories, mopeds and steps
BIKES_L2 = (446, 447, 448, 449, 451, 453, 454, 455, 456, 459, 460, 461, 464, 466, 467, 1621, 1916, 1917, 2026)  # fmt: skip
LIMIT = 100
NEAR_PAGES = 50  # the API returns nothing past offset + limit = 5000
FAR_PAGES = 10
MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
RELATIVE = {"vandaag": 0, "gisteren": 1, "eergisteren": 2}


def today() -> date:
    return datetime.now().astimezone().date()


def parse_date(s: str, ref: date) -> date | None:
    """The listing's bump date: 'Vandaag', 'Gisteren', 'Eergisteren' or '2 okt 26'."""
    s = (s or "").strip().lower()
    if s in RELATIVE:
        return ref - timedelta(days=RELATIVE[s])
    try:
        d, mon, yy = s.split()
        return date(2000 + int(yy), MONTHS.index(mon.rstrip(".")) + 1, int(d))
    except ValueError:
        return None


def parse(raw: dict, platform: str, ref: date | None = None) -> list[Listing]:
    host = HOSTS[platform][0]
    ref = ref or today()
    out = []
    for item in raw.get("listings", []):
        price = item.get("priceInfo", {})
        cents = price.get("priceCents")
        photos = [p["largeUrl"] for p in item.get("pictures", []) if p.get("largeUrl")]
        photos = photos or [
            "https:" + u if u.startswith("//") else u for u in item.get("imageUrls", [])
        ]
        out.append(
            Listing(
                id=item["itemId"],
                platform=platform,
                url=f"https://{host}{item.get('vipUrl', '')}",
                title=item.get("title", ""),
                description=max(
                    item.get("description", ""),
                    item.get("categorySpecificDescription", ""),
                    key=len,
                ),
                price=f"EUR {cents // 100}" if cents else price.get("priceType", ""),
                location=item.get("location", {}).get("cityName", ""),
                photo_urls=photos,
                posted_at=parse_date(item.get("date", ""), ref),
            )
        )
    return out


def _pages(fetch, params: list, platform: str, since: date, cap: int) -> list[Listing]:
    """Newest first, until a page ends before `since`, runs out, or hits the cap."""
    out = []
    for page in range(cap):
        raw = fetch(params + [("offset", page * LIMIT), ("limit", LIMIT)])
        if raw.get("hasErrors"):
            raise Blocked("search API reported errors")
        batch = parse(raw, platform)
        out += batch
        if len(batch) < LIMIT:
            break
        last = batch[-1].posted_at
        if last and last < since:
            break
    return out


def searches(platform: str, cfg) -> list[tuple[str, list, int]]:
    base = [("l1CategoryId", BIKES_L1), ("sortBy", "SORT_INDEX"), ("sortOrder", "DECREASING")]
    out = []
    # the sites ignore a postcode from the other country, so near runs on the home site only
    if cfg.country.upper() == HOSTS[platform][1]:
        near = base + [("l2CategoryIds", c) for c in BIKES_L2]
        near += [("postcode", cfg.postcode), ("distanceMeters", cfg.radius_km * 1000)]
        out.append(("near", near, NEAR_PAGES))
    out += [("far", base + [("query", w)], FAR_PAGES) for w in far_words(cfg)]
    return out


def _http_fetch(client: httpx.Client):
    def fetch(params: list) -> dict:
        time.sleep(random.uniform(2, 5))
        try:
            r = client.get("/lrp/api/search", params=params)
        except httpx.HTTPError as e:
            raise Blocked(f"network error: {e}") from e
        if r.status_code != 200:
            raise Blocked(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise Blocked("response is not JSON, probably a bot check") from e

    return fetch


def search(
    platform: str, cfg, since: date, max_pages: int | None = None, fetch=None
) -> list[Listing]:
    if fetch is None:
        host = HOSTS[platform][0]
        with httpx.Client(base_url=f"https://{host}", headers={"User-Agent": UA}, timeout=20) as c:
            return search(platform, cfg, since, max_pages, _http_fetch(c))
    found: dict[str, Listing] = {}
    for kind, params, cap in searches(platform, cfg):
        listings = _pages(fetch, params, platform, since, min(cap, max_pages or cap))
        if kind == "near" and not listings:
            # a bike category within a radius is never empty, so this is breakage, not a quiet day
            raise Blocked("near search returned nothing")
        for listing in listings:
            found.setdefault(listing.id, listing)
    return list(found.values())
