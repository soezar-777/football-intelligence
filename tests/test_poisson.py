"""Tests for the Poisson prediction model (backend/poisson.py)."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import poisson
from poisson import (
    build_team_stats,
    expected_goals,
    market_1x2,
    market_asian_handicap,
    market_btts,
    market_over_under,
    poisson_distribution,
    predict_match,
    score_matrix,
)


def _close(a, b=1.0, tol=1e-9):
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


def _stats(home_attack=1.6, home_defense=0.8, away_attack=0.7, away_defense=1.3):
    """Strong home side vs weak away side (ids 1 and 2)."""
    return {
        1: {"attack_home": home_attack, "defense_home": home_defense,
            "attack_away": 1.0, "defense_away": 1.0, "matches": 20.0},
        2: {"attack_home": 1.0, "defense_home": 1.0,
            "attack_away": away_attack, "defense_away": away_defense,
            "matches": 20.0},
    }


_AVGS = {"home": 1.45, "away": 1.15}


# ------------------------------------------------------------- basics ----
def test_poisson_distribution_sums_to_one():
    for lam in (0.0, 0.5, 1.45, 2.8, 5.0):
        assert _close(sum(poisson_distribution(lam)))


def test_score_matrix_sums_to_one():
    m = score_matrix(1.8, 1.1)
    assert _close(sum(sum(row) for row in m))
    assert len(m) == 9 and all(len(row) == 9 for row in m)


def test_1x2_sums_to_one():
    probs = market_1x2(score_matrix(2.0, 1.0))
    assert _close(sum(probs.values()))
    assert set(probs) == {"home", "draw", "away"}
    assert all(0.0 <= p <= 1.0 for p in probs.values())


def test_over_under_sums_to_one():
    m = score_matrix(1.6, 1.2)
    for line in (1.5, 2.5, 3.5):
        ou = market_over_under(m, line)
        assert _close(ou["over"] + ou["under"])


def test_btts_sums_to_one():
    b = market_btts(score_matrix(1.6, 1.2))
    assert _close(b["yes"] + b["no"])


def test_asian_handicap_cover_not_cover_sums_to_one():
    ah = market_asian_handicap(score_matrix(1.9, 1.0))
    for line, probs in ah.items():
        assert _close(probs["cover"] + probs["push"] + probs["not_cover"]), line
    # non-integer line has no push: cover + not_cover == 1
    p = ah["-1.5"]
    assert p["push"] == 0.0
    assert _close(p["cover"] + p["not_cover"])


def test_xg_non_negative():
    hxg, axg = expected_goals(1, 2, _stats(), _AVGS)
    assert hxg >= 0.0 and axg >= 0.0
    # unknown teams fall back to league averages, never negative/crash
    hxg2, axg2 = expected_goals(999, 1000, {}, _AVGS)
    assert hxg2 >= 0.0 and axg2 >= 0.0
    assert _close(hxg2, _AVGS["home"]) and _close(axg2, _AVGS["away"])


# -------------------------------------------------------------- model ----
def test_strong_home_team_ordering():
    """A clearly stronger home team: P(home) > P(draw) > P(away)."""
    pred = predict_match(1, 2, _stats(), _AVGS)
    p = pred["markets"]["1x2"]
    assert p["home"] > p["draw"] > p["away"], p


def test_expected_goals_formula():
    hxg, axg = expected_goals(1, 2, _stats(), _AVGS)
    assert _close(hxg, 1.6 * 1.3 * 1.45)
    assert _close(axg, 0.7 * 0.8 * 1.15)


def test_empty_history_falls_back_without_crashing():
    stats, avgs = build_team_stats([])
    assert stats == {}
    assert avgs["home"] > 0 and avgs["away"] > 0
    pred = predict_match(11, 22, stats, avgs)  # unknown teams
    assert _close(pred["xg"]["home"], avgs["home"])
    assert _close(pred["xg"]["away"], avgs["away"])
    assert _close(sum(pred["markets"]["1x2"].values()))


def _fm(home_id, away_id, hg, ag, day="2026-09-01"):
    return {
        "status": "FINISHED",
        "utcDate": f"{day}T14:00:00Z",
        "homeTeam": {"id": home_id},
        "awayTeam": {"id": away_id},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


def test_single_finished_match_builds_sane_stats():
    matches = [
        # team 10: prolific at home
        _fm(10, 20, 3, 0), _fm(10, 20, 2, 1), _fm(10, 20, 4, 1),
        # other low-scoring games set a modest league average
        _fm(30, 40, 1, 0), _fm(50, 60, 0, 0),
        _fm(30, 50, 1, 1), _fm(40, 60, 0, 1),
    ]
    stats, avgs = build_team_stats(matches)
    # thin data -> blended toward 1.0, but directionally sensible
    assert stats[10]["attack_home"] > 1.0
    assert stats[20]["defense_away"] > 1.0  # conceded 3 per game vs avg
    hxg, axg = expected_goals(10, 20, stats, avgs)
    assert hxg > axg


def test_predict_match_market_shapes():
    pred = predict_match(1, 2, _stats(), _AVGS)
    mk = pred["markets"]
    assert set(mk["ou"]) == {"1.5", "2.5", "3.5"}
    assert len(mk["correct_scores"]) == 5
    assert mk["correct_scores"][0]["prob"] >= mk["correct_scores"][-1]["prob"]
    assert set(mk["ah"]) == {"-1.5", "-1.0", "-0.5", "0.5", "1.0", "1.5"}
    # every probability set sums to 1
    assert _close(sum(mk["1x2"].values()))
    for line in mk["ou"].values():
        assert _close(line["over"] + line["under"])
    assert _close(mk["btts"]["yes"] + mk["btts"]["no"])


def test_rounded_probabilities_sum_exactly_to_one():
    """Rounded market probabilities in predict_match sum to exactly 1.0."""
    from poisson import _rounded
    for probs in ({"a": 0.333333, "b": 0.333333, "c": 0.333334},
                  {"home": 0.51234, "draw": 0.26111, "away": 0.22655}):
        r = _rounded(probs)
        assert sum(r.values()) == 1.0, r
    # end-to-end through predict_match
    pred = predict_match(1, 2, _stats(), _AVGS)
    mk = pred["markets"]
    assert sum(mk["1x2"].values()) == 1.0
    assert sum(mk["btts"].values()) == 1.0
    for line in list(mk["ou"].values()) + list(mk["ah"].values()):
        assert sum(line.values()) == 1.0, line
