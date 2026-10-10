"""End-to-end grading test for backend/verify.py with synthetic data."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config
import verify


def _write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_verify_grades_synthetic_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "COMPETITIONS", ["PL"])

    _write(tmp_path / "predictions.json", {
        "model_version": "poisson-v1",
        "predictions": [{
            "fixture_id": 9001,
            "competition": "PL",
            "home_team": {"id": 1, "name": "Home FC"},
            "away_team": {"id": 2, "name": "Away FC"},
            "kickoff": "2026-10-05T14:00:00Z",
            "markets": {"1x2": {"home": 0.6, "draw": 0.25, "away": 0.15}},
            "picks": {
                "1x2": {"selection": "home", "prob": 0.6},
                "ou25": {"selection": "over", "prob": 0.58},
                "btts": {"selection": "yes", "prob": 0.56},
                "ah": {"line": "-1.5", "side": "home_cover", "prob": 0.57},
                "correct_score": {"selection": "2-1", "prob": 0.13},
            },
        }],
    })
    _write(tmp_path / "matches_PL.json", {
        "matches": [{
            "id": 9001,
            "status": "FINISHED",
            "score": {"fullTime": {"home": 2, "away": 1}},
        }],
    })

    out = verify.verify_all()
    assert out["graded_count"] == 1
    g = out["matches"][0]["grades"]
    # actual 2-1: home win, over 2.5? no (3 > 2.5 -> over yes), btts yes,
    # AH -1.5: margin 1 - 1.5 < 0 -> not covered, correct score 2-1 exact
    assert g["1x2"]["hit"] is True
    assert g["ou25"]["hit"] is True
    assert g["btts"]["hit"] is True
    assert g["ah"]["hit"] is False
    assert g["correct_score"]["hit"] is True
    assert out["summary"]["1x2"]["hit_rate"] == 1.0
    assert out["summary"]["ah"]["hit_rate"] == 0.0


def test_verify_push_is_void(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "COMPETITIONS", ["PL"])
    _write(tmp_path / "predictions.json", {
        "model_version": "poisson-v1",
        "predictions": [{
            "fixture_id": 9002,
            "competition": "PL",
            "home_team": {"id": 1, "name": "Home FC"},
            "away_team": {"id": 2, "name": "Away FC"},
            "kickoff": "2026-10-05T14:00:00Z",
            "markets": {"1x2": {"home": 0.5, "draw": 0.3, "away": 0.2}},
            "picks": {
                "1x2": None,
                "ou25": None,
                "btts": None,
                "ah": {"line": "-1.0", "side": "home_cover", "prob": 0.6},
                "correct_score": None,
            },
        }],
    })
    _write(tmp_path / "matches_PL.json", {
        "matches": [{
            "id": 9002,
            "status": "FINISHED",
            "score": {"fullTime": {"home": 2, "away": 1}},  # margin 1 + (-1) = 0
        }],
    })
    out = verify.verify_all()
    g = out["matches"][0]["grades"]
    assert g["ah"]["hit"] is None  # push -> void, excluded from hit-rate
    assert out["summary"]["ah"]["graded"] == 0
