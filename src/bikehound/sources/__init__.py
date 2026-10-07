from dataclasses import dataclass, field
from datetime import date
from functools import partial


class Blocked(Exception):
    """CAPTCHA, block or expired session. The platform is skipped for this run."""


@dataclass
class Listing:
    id: str
    platform: str
    url: str
    title: str
    description: str = ""
    price: str = ""
    location: str = ""
    photo_urls: list[str] = field(default_factory=list)
    posted_at: date | None = None  # bump date, day precision


def far_words(cfg) -> list[str]:
    """Words for the far (text) search: the model group, else the brand group."""
    group = cfg.keywords.get("model") or cfg.keywords.get("brand")
    return group.words if group else []


from . import (
    facebook,
    lrp,
    vinted,
)  # after Listing, Blocked and far_words, which the sources import


def listing_url(platform: str, listing_id: str, country: str) -> str:
    """The listing's link from its ID alone; each redirects to the full listing page."""
    if platform in lrp.HOSTS:
        return f"https://{lrp.HOSTS[platform][0]}/{listing_id}"
    if platform == "vinted":
        return f"https://www.vinted.{country.lower()}/items/{listing_id}"
    return f"{facebook.BASE}/item/{listing_id}/"


# platform name -> search(cfg, since, max_pages=None) -> list[Listing]
SOURCES: dict = {p: partial(lrp.search, p) for p in lrp.HOSTS} | {
    "vinted": vinted.search,
    "facebook": facebook.search,
}
