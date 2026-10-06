from argparse import Namespace

from bikehound import cli, notify
from bikehound.sources import Listing
from bikehound.store import Store

CONFIG = """
bike: {stolen_on: 2026-09-20, active_until: 2099-01-01}
location: {postcode: "9000", country: BE, radius_km: 50}
platforms: [2dehands, marktplaats]
keywords: {model: {words: [e-u4]}}
threshold: 0.5
ntfy: {url: "https://ntfy.test/t"}
"""


def test_broken_platform_does_not_stop_the_others(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(CONFIG)
    sent = []
    monkeypatch.setattr(notify, "_send", lambda url, body, title, **kw: sent.append(title))
    monkeypatch.setattr(cli, "load_model", lambda: None)
    monkeypatch.setattr(cli, "reference_embeddings", lambda model, cfg: None)
    monkeypatch.setattr(cli, "listing_photo_score", lambda *a: 0.0)

    def broken(cfg, since):
        raise KeyError("itemId")  # e.g. the site changed its JSON

    def working(cfg, since):
        return [Listing("1", "marktplaats", "https://x.test/1", "a bike")]

    monkeypatch.setattr(cli, "SOURCES", {"2dehands": broken, "marktplaats": working})
    args = Namespace(config=tmp_path / "config.yaml", force=False, platform=None)
    assert cli.run(args) == 1
    assert "BikeHound: 2dehands failed" in sent
    store = Store(tmp_path / "data" / "bikehound.sqlite")
    assert store.is_seen("marktplaats", "1")
    assert store.last_ok("2dehands") is None
