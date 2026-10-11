"""Tests for backend/fetch_apisports.py (Segunda Division via API-Football)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import fetch_apisports as ap


def _fixture(short="FT", gh=2, ga=1):
    return {
        "fixture": {"id": 1234567, "date": "2026-10-11T18:00:00+00:00",
                    "status": {"short": short}},
        "teams": {"home": {"id": 723, "name": "Almeria"},
                  "away": {"id": 724, "name": "Osasuna"}},
        "goals": {"home": gh, "away": ga},
    }


def test_normalize_finished():
    m = ap.normalize_fixture(_fixture("FT"))
    assert m["id"] == ap.APISPORTS_ID_OFFSET + 1234567
    assert m["status"] == "FINISHED"
    assert m["homeTeam"]["name"] == "Almeria"
    assert m["score"]["fullTime"] == {"home": 2, "away": 1}
    assert m["competition"]["code"] == "SDV"


def test_normalize_upcoming_has_no_score():
    m = ap.normalize_fixture(_fixture("NS", None, None))
    assert m["status"] == "TIMED"
    assert m["score"]["fullTime"] == {"home": None, "away": None}


def test_status_mapping():
    assert ap._status("FT") == "FINISHED"
    assert ap._status("AET") == "FINISHED"
    assert ap._status("PEN") == "FINISHED"
    assert ap._status("NS") == "TIMED"
    assert ap._status("1H") == "TIMED"


def test_id_offset_avoids_other_sources():
    m = ap.normalize_fixture(_fixture())
    # football-data.org IDs < 1M, OpenLigaDB offset at 2M
    assert m["id"] > 2_000_000 + 1_000_000


def test_no_key_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "KEY_PATH", tmp_path / "nope")
    assert ap.load_api_key() is None
