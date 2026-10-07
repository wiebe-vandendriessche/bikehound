import time

import httpx

from .match import Score
from .sources import Listing
from .sources.lrp import HOSTS

# the app shows this as the notification icon (PNG or JPEG only)
ICON = "https://raw.githubusercontent.com/wiebe-vandendriessche/bikehound/main/img/icon-192.png"


def _send(
    url: str, body: str, title: str, click: str = "", attach: str = "", tags: str = ""
) -> None:
    # headers must be ASCII, so listing text goes in the body only
    h = {"Title": title, "Tags": tags, "Icon": ICON}
    if click:
        h["Click"] = click
    if attach:
        h["Attach"] = attach
    # ntfy.sh allows a burst of 60, then one message per 5 s; wait instead of dropping
    # (a first run can find 100+ matches). Still limited after a minute (daily quota): raise,
    # and the caller defers the listing to the next run.
    for _ in range(12):
        r = httpx.post(url, content=body.encode(), headers=h, timeout=20)
        if r.status_code != 429:
            break
        time.sleep(5)
    r.raise_for_status()


def match(url: str, l: Listing, s: Score) -> None:
    body = f"{l.title}\n{l.price} {l.location}\n{s.reasons()} (total {s.total:.2f})"
    if l.posted_at:
        # 2dehands and Marktplaats only give the bump date, which can be later than the post date
        body += f"\n{'bumped' if l.platform in HOSTS else 'posted'} {l.posted_at}"
    _send(
        url,
        body,
        f"Possible match on {l.platform}",
        l.url,
        l.photo_urls[0] if l.photo_urls else "",
        "dog",
    )


def failure(url: str, platform: str, why: str) -> None:
    _send(
        url,
        f"{platform} was skipped this run: {why}",
        f"BikeHound: {platform} failed",
        tags="warning",
    )


def crashed(url: str, why: str) -> None:
    _send(
        url,
        f"The run stopped on an unexpected error: {why}. See the log.",
        "BikeHound: run crashed",
        tags="warning",
    )


def stopped(url: str, until) -> None:
    _send(
        url,
        f"The search ended on {until}. Raise bike.active_until to continue.",
        "BikeHound: search stopped",
        tags="stop_sign",
    )
