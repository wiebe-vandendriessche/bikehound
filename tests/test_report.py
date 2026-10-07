from bikehound import report


def row(**kw):
    return {"platform": "vinted", "listing_id": "1", "first_seen": "2026-10-07T10:00:00",
            "score": 0.62, "notified": 1, "url": "https://x.test/1", "title": "fiets",
            "price": "", "location": "", "photo": "", "posted_at": "", "reasons": "photo 0.62"} | kw  # fmt: skip


def test_escapes_listing_text_and_rejects_non_web_links(tmp_path):
    out = tmp_path / "matches.html"
    report.write([row(title="<script>x</script>"), row(url="javascript:alert(1)")], 0.5, "BE", out)
    html = out.read_text()
    assert "<script>x" not in html and "&lt;script&gt;x" in html
    assert "javascript:" not in html
    assert 'data-score="0.62" href="https://x.test/1"' in html


def test_rows_without_details_link_by_id(tmp_path):
    out = tmp_path / "matches.html"
    report.write([row(platform="vinted", listing_id="42", url="", title="")], 0.5, "BE", out)
    assert 'href="https://www.vinted.be/items/42"' in out.read_text()
