from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

PLATFORMS = {"2dehands", "marktplaats", "vinted", "facebook"}
DEFAULT_WEIGHTS = {"brand": 0.3, "model": 0.4}
OTHER_WEIGHT = 0.1


class ConfigError(Exception):
    pass


@dataclass
class Group:
    words: list[str]
    weight: float


@dataclass
class Config:
    stolen_on: date
    active_until: date
    frame_number: str | None
    reference_dir: Path
    postcode: str
    country: str
    radius_km: int
    platforms: list[str]
    keywords: dict[str, Group]
    threshold: float
    ntfy_url: str
    data_dir: Path = field(default=Path("data"))


def _need(d: dict, key: str, where: str):
    if not isinstance(d, dict) or d.get(key) in (None, ""):
        raise ConfigError(f"missing '{key}' in {where}")
    return d[key]


def _date(v, where: str) -> date:
    if not isinstance(v, date):
        raise ConfigError(f"{where} must be a date like 2026-09-20, got {v!r}")
    return v


def load(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} is empty or not a mapping")
    base = path.resolve().parent

    bike, loc = raw.get("bike"), raw.get("location")
    stolen = _date(_need(bike, "stolen_on", "bike"), "bike.stolen_on")
    until = bike.get("active_until")
    until = _date(until, "bike.active_until") if until else stolen + timedelta(days=365)

    platforms = raw.get("platforms") or ["2dehands", "marktplaats"]
    if bad := set(platforms) - PLATFORMS:
        raise ConfigError(f"unknown platforms {sorted(bad)}, choose from {sorted(PLATFORMS)}")

    keywords = {}
    for name, g in (raw.get("keywords") or {}).items():
        words = (g or {}).get("words")
        if not words or not isinstance(words, list):
            raise ConfigError(f"keywords.{name}.words must be a non-empty list")
        weight = g.get("weight", DEFAULT_WEIGHTS.get(name, OTHER_WEIGHT))
        keywords[name] = Group([str(w) for w in words], float(weight))

    threshold = raw.get("threshold")
    if not isinstance(threshold, (int, float)):
        raise ConfigError("missing numeric 'threshold'")

    ntfy_url = _need(raw.get("ntfy"), "url", "ntfy")
    if "{topic}" in ntfy_url:
        raise ConfigError("ntfy.url still contains {topic}, run `bikehound init` or set a topic")

    return Config(
        stolen_on=stolen,
        active_until=until,
        frame_number=bike.get("frame_number"),
        reference_dir=base / bike.get("reference_dir", "reference"),
        postcode=str(_need(loc, "postcode", "location")),
        country=str(_need(loc, "country", "location")),
        radius_km=int(_need(loc, "radius_km", "location")),
        platforms=platforms,
        keywords=keywords,
        threshold=float(threshold),
        ntfy_url=ntfy_url,
        data_dir=base / "data",
    )
