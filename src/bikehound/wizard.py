"""`bikehound init` in a terminal: a few questions, written into the commented config template."""

import re
import shlex
import shutil
from datetime import date
from json import dumps  # a JSON list or string is valid YAML flow syntax
from pathlib import Path
from string import Template

from .config import COUNTRIES
from .match import PHOTO_EXT
from .sources.lrp import today

# Dutch, French, English; an answer in any of them finds its row. Words match anywhere in the
# text, so inflections are covered ("zwart" in "zwarte") except where the stem changes ("rode").
COLOURS = [
    ("zwart", "noir", "black"),
    ("witte", "blanc", "white"),
    ("grijs", "grijze", "gris", "grey", "gray"),
    ("zilver", "argent", "silver"),
    ("rood", "rode", "rouge"),
    ("blauw", "bleu", "blue"),
    ("groen", "vert", "green"),
    ("geel", "gele", "jaune", "yellow"),
    ("oranje", "orange"),
    ("roze", "rose", "pink"),
    ("paars", "violet", "purple"),
    ("bruin", "brun", "brown"),
    ("beige",),
]
# answers left out of the rows because they are inside other words: "covered", "switch"
ALIASES = {"red": "rood", "wit": "witte"}
PLATFORMS = ["2dehands", "marktplaats"]  # on by default; vinted and facebook are asked for
OPT_IN = [
    ("vinted", "Also search Vinted? Its terms forbid automated access, see the README. [y/N]"),
    ("facebook", "Also search Facebook Marketplace? Same caveat, logged out only. [y/N]"),
]
FRAME_EXAMPLE = '# frame_number: "WXYZ12345"    # optional, a hit always notifies'

# what a config written without questions contains (stdin is not a terminal)
EXAMPLE = {
    "stolen_on": date(2026, 9, 20),
    "country": "BE",
    "postcode": "9000",
    "radius_km": 50,
    "frame_number": None,
    "keywords": {
        "brand": (["cortina"], None),
        "model": (["e-u4", "eu4", "e u4"], None),
        "color": (["felgroen", "groen", "green", "vert"], 0.3),
    },
    "platforms": PLATFORMS,
    "photos": [],
}


def variants(name: str) -> list[str]:
    """The spellings sellers use for a model name: E-U4 -> e-u4, e u4, eu4."""
    n = " ".join(name.lower().split())
    return list(dict.fromkeys([n, re.sub(r"[-/]", " ", n), re.sub(r"[-/]", "", n)]))


def colour_words(answer: str) -> list[str]:
    w = ALIASES.get(answer.strip().lower(), answer.strip().lower())
    return next((list(row) for row in COLOURS if w in row), [w])


def ask(prompt: str, parse=str.strip, default: str = ""):
    """Asks until parse accepts the answer; parse raises ValueError with the reason."""
    while True:
        answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or default
        try:
            return parse(answer)
        except ValueError as e:
            print(f"  {e}")


def _stolen_on(s: str) -> date:
    try:
        d = date.fromisoformat(s)
    except ValueError:
        raise ValueError("write the date like 2026-09-20") from None
    if d > today():
        raise ValueError("that date is in the future")
    return d


def _country(s: str) -> str:
    if s.upper() not in COUNTRIES:
        raise ValueError("BikeHound covers BE and NL")
    return s.upper()


def _postcode(s: str) -> str:
    if not re.fullmatch(r"\d{4}( ?[A-Za-z]{2})?", s):
        raise ValueError("a postcode is 4 digits, in NL optionally followed by 2 letters")
    return s.replace(" ", "").upper()


def _radius(s: str) -> int:
    if not s.isdigit() or int(s) == 0:
        raise ValueError("a whole number of km, like 50")
    return int(s)


def _yes(s: str) -> bool:
    return s.lower().startswith("y")


def _photos(s: str) -> list[Path]:
    """A folder or files, as typed or dragged into the terminal (which quotes them)."""
    found = []
    for part in shlex.split(s):
        p = Path(part).expanduser()
        if not p.exists():
            raise ValueError(f"{p} does not exist")
        found += sorted(p.iterdir()) if p.is_dir() else [p]
    photos = [p for p in found if p.is_file() and p.suffix.lower() in PHOTO_EXT]
    if s and not photos:
        raise ValueError("no jpg, png or webp photos there")
    return photos


def interactive() -> dict:
    print("A few questions about your bike. Enter accepts the value in [brackets].")
    v = {"stolen_on": ask("Date the bike was stolen (YYYY-MM-DD)", _stolen_on)}
    v["country"] = ask("Country, BE or NL", _country, "BE")
    v["postcode"] = ask("Postcode", _postcode)
    v["radius_km"] = ask("Search radius in km", _radius, "50")
    v["frame_number"] = ask("Frame number (Enter to skip)") or None
    keywords = {}
    if brand := ask("Brand (Enter to skip)"):
        keywords["brand"] = ([w.strip().lower() for w in brand.split(",") if w.strip()], None)
    if model := ask("Model, comma-separated if it has several names (Enter to skip)"):
        words = list(dict.fromkeys(w for m in model.split(",") if m.strip() for w in variants(m)))
        print(f"  searching for: {', '.join(words)}")
        keywords["model"] = (words, None)
    if colour := ask("Main colour (Enter to skip)"):
        words = colour_words(colour)
        print(f"  searching for: {', '.join(words)}")
        unusual = ask("Is that colour unusual for this kind of bike? [y/N]", _yes)
        keywords["color"] = (words, 0.3 if unusual else None)
    v["keywords"] = keywords
    v["platforms"] = PLATFORMS + [p for p, question in OPT_IN if ask(question, _yes)]
    v["photos"] = ask("Folder or photos of your bike, drag them here (Enter to skip)", _photos)
    return v


def render(template: str, v: dict) -> str:
    frame = v["frame_number"]
    keywords = [
        f"  {name}: {{ words: {dumps(words, ensure_ascii=False)}"
        + (f", weight: {weight}" if weight else "")
        + " }"
        for name, (words, weight) in v["keywords"].items()
    ]
    return Template(template).substitute(
        stolen_on=v["stolen_on"].isoformat(),
        frame_line=f"frame_number: {dumps(frame)}" if frame else FRAME_EXAMPLE,
        postcode=v["postcode"],
        country=v["country"],
        radius_km=v["radius_km"],
        platforms=dumps(v["platforms"]),
        keywords="\n".join(keywords) or '  # brand: { words: ["cortina"] }',
    )


def copy_photos(photos: list[Path], dest: Path) -> int:
    """Copies into dest, never over a file of the same name. Returns how many were copied."""
    copied = 0
    for p in photos:
        if not (dest / p.name).exists():
            shutil.copy2(p, dest / p.name)
            copied += 1
    return copied
