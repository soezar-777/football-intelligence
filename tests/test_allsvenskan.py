"""Tests for backend/fetch_allsvenskan.py (Allsvenskan via ESPN + CSV)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import fetch_allsvenskan as alv


def test_canonical_name_csv_to_espn():
    assert alv.canonical_name("Malmo FF") == "Malmö FF"
    assert alv.canonical_name("Goteborg") == "IFK Göteborg"
    assert alv.canonical_name("Elfsborg") == "IF Elfsborg"
    assert alv.canonical_name("Kalmar") == "Kalmar FF"
    assert alv.canonical_name("Oster") == "Östers IF"


def test_canonical_name_passthrough_espn_names():
    assert alv.canonical_name("Malmö FF") == "Malmö FF"
    assert alv.canonical_name("IF Elfsborg") == "IF Elfsborg"
    assert alv.canonical_name("AIK") == "AIK"


def test_norm_strips_accents_and_prefixes():
    assert alv._norm("Malmö FF") == "malmo ff"
    assert alv._norm("IF Elfsborg") == "elfsborg"
    assert alv._norm("Djurgårdens IF") == "djurgardens if"


def test_stockholm_to_utc():
    # 19:00 CEST (UTC+2) -> 17:00 UTC
    assert alv._stockholm_to_utc("14/08/2026", "19:00").startswith(
        "2026-08-14T17:00:00+00:00")


def test_id_offsets_avoid_other_sources():
    assert alv.ESPN_ID_OFFSET > 4_900_000  # above SDV csv offset
    assert alv.CSV_ID_BASE > alv.ESPN_ID_OFFSET
