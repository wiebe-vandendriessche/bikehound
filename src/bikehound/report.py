"""The match gallery: one self-contained HTML page, rewritten after every run."""

import os
from html import escape
from pathlib import Path

from .sources import listing_url

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>BikeHound matches</title>
<style>
:root {{ color-scheme: light dark; --bg: #f6f6f4; --card: #fff; --muted: #666; --hit: #c2410c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #161616; --card: #222; --muted: #aaa; }} }}
body {{ margin: 0; padding: 16px; font: 15px/1.4 system-ui, sans-serif; background: var(--bg); }}
header {{ display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: center; margin-bottom: 16px; }}
h1 {{ font-size: 20px; margin: 0; }}
.grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }}
.card {{ background: var(--card); border-radius: 8px; overflow: hidden; color: inherit;
  text-decoration: none; display: flex; flex-direction: column; }}
.card img {{ width: 100%; aspect-ratio: 4/3; object-fit: cover; background: #8884; }}
.card div {{ padding: 8px 10px; }}
.card b {{ display: block; }}
.meta {{ color: var(--muted); font-size: 13px; }}
.notified .score {{ color: var(--hit); font-weight: 600; }}
[hidden] {{ display: none; }}
</style></head><body>
<header><h1>BikeHound matches</h1>
<label>Min score <input id="min" type="range" min="0" max="{top}" step="0.05" value="{threshold}">
<output id="val">{threshold}</output></label>
<label><input id="only" type="checkbox"> notified only</label>
<span class="meta" id="count"></span></header>
<main class="grid">
{cards}
</main>
<script>
const min = document.getElementById("min"), only = document.getElementById("only");
function filter() {{
  let n = 0;
  document.getElementById("val").textContent = (+min.value).toFixed(2);
  for (const c of document.querySelectorAll(".card")) {{
    const hit = c.classList.contains("notified");
    c.hidden = only.checked ? !hit : !hit && +c.dataset.score < +min.value;
    n += !c.hidden;
  }}
  document.getElementById("count").textContent = n + " shown";
}}
min.oninput = only.onchange = filter;
filter();
</script></body></html>
"""

CARD = """<a class="card{cls}" data-score="{score:.2f}" href="{url}" target="_blank" \
rel="noopener noreferrer">{img}<div><b>{title}</b>
<span class="meta">{price} {location}<br>{platform}, seen {seen}{posted}</span><br>
<span class="score">{score:.2f}</span> <span class="meta">{reasons}</span></div></a>"""


def _web(url: str) -> str:
    """Listing data is untrusted: only http(s) links, so no javascript: URLs end up in the page."""
    return escape(url) if url.startswith(("https://", "http://")) else ""


def card(r, country: str) -> str:
    photo = _web(r["photo"])
    # scored before details were saved: only the ID and score are known
    title = r["title"] or f"{r['platform']} {r['listing_id']} (no details saved)"
    return CARD.format(
        cls=" notified" if r["notified"] else "",
        score=r["score"],
        url=_web(r["url"] or listing_url(r["platform"], r["listing_id"], country)),
        img=f'<img src="{photo}" loading="lazy" alt="">' if photo else "",
        title=escape(title),
        price=escape(r["price"]),
        location=escape(r["location"]),
        platform=escape(r["platform"]),
        seen=r["first_seen"][:10],
        posted=f", dated {escape(r['posted_at'])}" if r["posted_at"] else "",
        reasons=escape(r["reasons"]),
    )


def write(rows: list, threshold: float, country: str, path: Path) -> None:
    top = max([threshold, *(r["score"] for r in rows)]) + 0.05
    html = PAGE.format(top=f"{top:.2f}", threshold=f"{threshold:.2f}",
                       cards="\n".join(card(r, country) for r in rows))  # fmt: skip
    tmp = path.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, path)  # never a half-written page in the browser
