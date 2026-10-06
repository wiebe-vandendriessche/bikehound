import httpx

from .match import Score
from .sources import Listing

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
    httpx.post(url, content=body.encode(), headers=h, timeout=20).raise_for_status()


def match(url: str, l: Listing, s: Score) -> None:
    body = f"{l.title}\n{l.price} {l.location}\n{s.reasons()} (total {s.total:.2f})"
    _send(
        url,
        body,
        f"Possible match on {l.platform}",
        l.url,
        l.photo_urls[0] if l.photo_urls else "",
        "dog",
    )


MAX_BODY = 4000  # ntfy turns messages over 4096 bytes into attachments


def digest(url: str, hits: list[tuple[Listing, Score]]) -> list[tuple[Listing, Score]]:
    """First run: all hits as a few list messages instead of one push each (ntfy rate limit).
    Returns the hits that were sent; stops at the first failed message."""
    hits = sorted(hits, key=lambda h: h[1].total, reverse=True)
    parts: list[list] = [[]]
    size = 0
    for l, s in hits:
        line = f"{s.total:.2f}  {l.price}  {l.location}  {l.url}\n"
        if parts[-1] and size + len(line.encode()) > MAX_BODY:
            parts.append([])
            size = 0
        parts[-1].append((l, s, line))
        size += len(line.encode())
    sent = []
    for i, part in enumerate(parts, 1):
        if not part:
            continue
        title = f"BikeHound first run: {len(hits)} possible matches (part {i}/{len(parts)})"
        try:
            _send(url, "".join(line for *_, line in part), title, tags="dog")
        except httpx.HTTPError:
            break
        sent += [(l, s) for l, s, _ in part]
    return sent


def failure(url: str, platform: str, why: str) -> None:
    _send(
        url,
        f"{platform} was skipped this run: {why}",
        f"BikeHound: {platform} failed",
        tags="warning",
    )


def stopped(url: str, until) -> None:
    _send(
        url,
        f"The search ended on {until}. Raise bike.active_until to continue.",
        "BikeHound: search stopped",
        tags="stop_sign",
    )
