import httpx

from bikehound import notify
from bikehound.match import Score
from bikehound.sources import Listing


def hits(n):
    return [
        (Listing(str(i), "p", f"https://x.test/{i:03}" + "a" * 80, "t"), Score(i / n))
        for i in range(n)
    ]


def test_digest_splits_and_keeps_every_hit(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "_send", lambda url, body, title, **kw: sent.append((title, body)))
    h = hits(120)
    assert len(notify.digest("u", h)) == 120
    assert len(sent) > 1 and all(len(b.encode()) <= notify.MAX_BODY for _, b in sent)
    assert sent[0][1].startswith("0.99") and sent[0][0].endswith(f"(part 1/{len(sent)})")
    assert sum(b.count("\n") for _, b in sent) == 120


def test_digest_stops_at_failure(monkeypatch):
    calls = []

    def send(url, body, title, **kw):
        calls.append(title)
        if len(calls) == 2:
            raise httpx.HTTPError("429")

    monkeypatch.setattr(notify, "_send", send)
    sent = notify.digest("u", hits(120))
    assert 0 < len(sent) < 120 and len(calls) == 2


def test_every_message_carries_the_icon(monkeypatch):
    sent = []

    class Ok:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.append(kw["headers"]) or Ok())
    notify.failure("u", "vinted", "HTTP 403")
    assert sent[0]["Icon"] == notify.ICON and notify.ICON.endswith(".png")
