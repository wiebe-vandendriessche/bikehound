import httpx

from bikehound import notify


def test_rate_limit_waits_then_sends(monkeypatch):
    codes = [429, 429, 200]

    class R:
        def __init__(self):
            self.status_code = codes.pop(0)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPError(str(self.status_code))

    monkeypatch.setattr(httpx, "post", lambda url, **kw: R())
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    notify.failure("u", "vinted", "x")  # does not raise
    assert codes == []


def test_every_message_carries_the_icon(monkeypatch):
    sent = []

    class Ok:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.append(kw["headers"]) or Ok())
    notify.failure("u", "vinted", "HTTP 403")
    assert sent[0]["Icon"] == notify.ICON and notify.ICON.endswith(".png")
