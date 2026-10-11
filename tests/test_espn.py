"""Tests for backend/fetch_espn.py (Segunda Division via ESPN + CSV)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import fetch_espn as espn


def test_canonical_name_csv_to_espn():
    assert espn.canonical_name("Castellon") == "Castellón"
    assert espn.canonical_name("Sp Gijon") == "Sporting Gijón"
    assert espn.canonical_name("Oviedo") == "Real Oviedo"
    assert espn.canonical_name("Sabadell") == "CD Sabadell"
    assert espn.canonical_name("RC Celta Fortuna") == "Celta Vigo II"


def test_canonical_name_passthrough_espn_names():
    assert espn.canonical_name("Almería") == "Almería"
    assert espn.canonical_name("FC Andorra") == "FC Andorra"


def test_norm_strips_accents_and_prefixes():
    assert espn._norm("Castellón") == "castellon"
    assert espn._norm("FC Andorra") == "andorra"
    assert espn._norm("Real Sociedad II") == "sociedad"
    assert espn._norm("Sporting Gijón") == "gijon"


def test_madrid_to_utc():
    # 19:30 CEST (UTC+2) -> 17:30 UTC
    assert espn._madrid_to_utc("14/08/2026", "19:30").startswith(
        "2026-08-14T17:30:00+00:00")


def test_id_offsets_avoid_other_sources():
    assert espn.ESPN_ID_OFFSET > 3_000_000  # above apisports offset
    assert espn.CSV_ID_BASE > espn.ESPN_ID_OFFSET
