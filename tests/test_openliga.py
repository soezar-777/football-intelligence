"""Tests for backend/fetch_openliga.py (2. Bundesliga via OpenLigaDB)."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import fetch_openliga as ol


def _sample(finished=True):
    return {
        "matchID": 12345,
        "matchDateTime": "2026-10-11T13:30:00",  # Europe/Berlin wall time
        "team1": {"teamId": 1, "teamName": "Hertha BSC", "shortName": "BSC"},
        "team2": {"teamId": 2, "teamName": "VfL Bochum", "shortName": "BOC"},
        "matchIsFinished": finished,
        "matchResults": [
            {"resultTypeID": 1, "pointsTeam1": 1, "pointsTeam2": 0},
            {"resultTypeID": 2, "pointsTeam1": 2, "pointsTeam2": 1},
        ] if finished else [],
    }


def test_normalize_finished_match():
    m = ol.normalize_match(_sample(finished=True))
    assert m["id"] == ol.BL2_ID_OFFSET + 12345
    assert m["status"] == "FINISHED"
    assert m["homeTeam"]["name"] == "Hertha BSC"
    assert m["awayTeam"]["name"] == "VfL Bochum"
    assert m["score"]["fullTime"] == {"home": 2, "away": 1}
    assert m["competition"]["code"] == "BL2"
    # 13:30 Berlin (CEST, +02:00) -> 11:30 UTC
    assert m["utcDate"].startswith("2026-10-11T11:30:00+00:00")


def test_normalize_upcoming_match():
    m = ol.normalize_match(_sample(finished=False))
    assert m["status"] == "TIMED"
    assert m["score"]["fullTime"] == {"home": None, "away": None}


def test_season_year_cutoff():
    july = datetime(2026, 7, 1, tzinfo=timezone.utc)
    june = datetime(2026, 6, 30, tzinfo=timezone.utc)
    assert ol.current_season_year(july) == 2026
    assert ol.current_season_year(june) == 2025


def test_id_offset_avoids_football_data_range():
    # football-data.org fixture IDs are well below 1M; offset keeps BL2 clear
    m = ol.normalize_match(_sample())
    assert m["id"] > 1_000_000
