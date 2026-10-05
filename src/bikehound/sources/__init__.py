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


from . import lrp  # after Listing and Blocked, which the sources import

# platform name -> search(cfg, since, max_pages=None) -> list[Listing]
SOURCES: dict = {p: partial(lrp.search, p) for p in lrp.HOSTS}
