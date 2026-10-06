from datetime import date
from pathlib import Path

import pytest

from bikehound.config import Config, Group
from bikehound.match import found, photo_score, score
from bikehound.sources import Listing


def cfg(**kw) -> Config:
    base = {
        "stolen_on": date(2026, 9, 20),
        "active_until": date(2027, 9, 20),
        "frame_number": "WXYZ 12345",
        "reference_dir": Path("reference"),
        "postcode": "9000",
        "country": "BE",
        "lat": None,
        "lon": None,
        "radius_km": 50,
        "platforms": ["2dehands"],
        "threshold": 0.5,
        "ntfy_url": "http://x",
        "keywords": {
            "brand": Group(["cortina"], 0.3),
            "model": Group(["e-u4"], 0.4),
            "color": Group(["groen"], 0.1),
        },
    }
    return Config(**{**base, **kw})


def test_brand_plus_model_reaches_threshold_color_alone_does_not():
    c = cfg()
    assert score(Listing("1", "p", "u", "Cortina E-U4 te koop"), c).notify(c.threshold)
    assert not score(Listing("2", "p", "u", "Groene fiets"), c).notify(c.threshold)


def test_accent_and_case_insensitive():
    c = cfg(keywords={"brand": Group(["vélo"], 1.0)})
    assert score(Listing("1", "p", "u", "VELO"), c).groups == ["brand"]


def test_frame_number_always_notifies():
    c = cfg()
    s = score(Listing("1", "p", "u", "fiets", "nummer wxyz-12345 graveer"), c)
    assert s.frame_hit and s.notify(99)


def test_photo_score_takes_best_pair():
    import torch

    refs = torch.eye(3)[:2]  # two reference photos
    listing = torch.tensor([[0.0, 0.0, 1.0], [0.6, 0.8, 0.0]])
    assert abs(photo_score(listing, refs) - 0.5 * (0.8 - 0.55) / 0.16) < 1e-6  # best pair, rescaled
    assert photo_score(torch.tensor([[0.0, 0.0, 1.0]]), refs) == 0.0  # below baseline
    assert photo_score(torch.empty(0, 3), refs) == 0.0


def test_photo_adds_to_keywords():
    c = cfg()
    s = score(Listing("1", "p", "u", "Cortina fiets"), c, photo=0.5)
    assert abs(s.total - 0.8) < 1e-9 and s.groups == ["brand"]


@pytest.mark.parametrize(
    "word, text, hit",
    [
        ("28", "28 inch wielen", True),
        ("28", "280 euro", False),
        ("28", "1280", False),
        ("28", "28.00 eur", False),
        ("28", "28.5 inch", False),
        ("28", "28,5 inch", False),
        ("e u4", "cortina e u4", True),
        ("e-u4", "cortina e-u4", True),
        ("e-u4", "e-u45", False),
        ("groen", "felgroen", True),
        ("groen", "groene fiets", True),
        ("Vert", "vtt vert", True),  # the word is normalised, the text already is
    ],
)
def test_numbers_never_match_inside_longer_numbers(word, text, hit):
    assert found(word, text) is hit
