import builtins
import sys
from argparse import Namespace
from datetime import date

from bikehound import cli, wizard
from bikehound.config import Group, load
from bikehound.match import word_warnings


def init(tmp_path, monkeypatch, answers=None):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: answers is not None)
    if answers is not None:
        it = iter(answers)
        monkeypatch.setattr(builtins, "input", lambda prompt: next(it))
    assert cli.init(Namespace(config=tmp_path / "config.yaml")) == 0
    return load(tmp_path / "config.yaml")


def test_interactive(tmp_path, monkeypatch):
    photos = tmp_path / "my photos"
    photos.mkdir()
    (photos / "side.jpg").write_bytes(b"x")
    (photos / "notes.txt").write_text("x")
    answers = [
        "20/09/2026",  # wrong form, asked again
        "2026-09-20",
        "nl",
        "1012 ab",
        "",  # default radius
        "WXYZ 123",
        "Cortina",
        "E-U4",
        "green",
        "y",  # unusual colour
        "n",  # vinted
        "y",  # facebook
        f"'{photos}'",  # dragged into the terminal
    ]
    cfg = init(tmp_path, monkeypatch, answers)
    assert cfg.stolen_on == date(2026, 9, 20)
    assert (cfg.country, cfg.postcode, cfg.radius_km) == ("NL", "1012AB", 50)
    assert cfg.frame_number == "WXYZ 123"
    assert cfg.keywords["model"].words == ["e-u4", "e u4", "eu4"]
    assert cfg.keywords["color"] == Group(["groen", "vert", "green"], 0.3)
    assert cfg.platforms == ["2dehands", "marktplaats", "facebook"]
    assert [p.name for p in (tmp_path / "reference").iterdir()] == ["side.jpg"]


def test_without_terminal_writes_the_example(tmp_path, monkeypatch):
    cfg = init(tmp_path, monkeypatch)
    assert cfg.postcode == "9000" and "{topic}" not in cfg.ntfy_url


def test_helpers():
    assert wizard.variants("Manhattan 40-27") == [
        "manhattan 40-27",
        "manhattan 40 27",
        "manhattan 4027",
    ]
    assert wizard.colour_words("Rouge") == ["rood", "rode", "rouge"]
    assert wizard.colour_words("red") == ["rood", "rode", "rouge"]
    w = word_warnings({"brand": Group(["mtb", "28", "cortina"], 0.3)})
    assert len(w) == 3  # short word, bare number, no model group
