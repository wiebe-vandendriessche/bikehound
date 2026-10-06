import pytest

from bikehound.config import PLATFORMS, ConfigError, load
from bikehound.sources import SOURCES

YAML = """
bike: {{stolen_on: 2026-09-20}}
location: {{postcode: "9000", country: {country}, radius_km: 50}}
threshold: 0.5
ntfy: {{url: "https://ntfy.sh/x"}}
"""


def test_country_is_belgium_or_netherlands(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(YAML.format(country="nl"))
    assert load(p).country == "NL"
    p.write_text(YAML.format(country="FR"))
    with pytest.raises(ConfigError, match="BE or NL"):
        load(p)


def test_every_platform_has_a_source():
    assert PLATFORMS == set(SOURCES)  # cli indexes SOURCES with any configured platform
