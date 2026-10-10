"""Poisson-based match prediction model (FOOTBALL INTELLIGENCE core).

Pipeline
--------
1. finished matches (home/away split, recency-weighted)
       -> team attack / defense strengths vs league averages
2. strengths -> expected goals (xG) for a fixture
3. xG pair -> Poisson score-probability matrix (0..8 x 0..8, sums to 1)
4. matrix -> market probabilities:
       1X2, Over/Under (1.5/2.5/3.5), BTTS, top correct scores,
       Asian Handicap home-cover probabilities

Design notes
------------
* Home and away performances are modelled separately: a team's home attack
  strength only ever comes from goals it scored at home, etc.
* Recent matches matter more: exponential decay with a 180-day half-life.
* Teams with too little history fall back toward the league average
  (strength 1.0 = perfectly average), blended proportionally to how much
  data exists. Empty history therefore never crashes and simply predicts
  the league-average scoreline.
* Every probability set is defensively re-normalised so it sums to 1.0,
  guarding against float drift and the 0..8 goal truncation.
"""

import math
from datetime import date, datetime

MAX_GOALS = 8            # score matrix covers 0..8 goals per side
MIN_MATCHES = 5.0        # weighted matches before a raw strength is trusted
RECENCY_HALFLIFE_DAYS = 180.0


# ------------------------------------------------------------ Poisson ----
def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) for X ~ Poisson(lam). lam < 0 is treated as 0."""
    lam = max(lam, 0.0)
    if k < 0:
        return 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_distribution(lam: float, max_goals: int = MAX_GOALS) -> list[float]:
    """Truncated Poisson distribution over 0..max_goals, normalised to 1."""
    probs = [poisson_pmf(k, lam) for k in range(max_goals + 1)]
    return _normalize(probs)


def _normalize(probs: list[float]) -> list[float]:
    """Scale a list of non-negative numbers to sum to 1 (defensive)."""
    total = sum(probs)
    if total <= 0:
        n = len(probs)
        return [1.0 / n] * n
    return [p / total for p in probs]


def _rounded(probs: dict[str, float], ndigits: int = 4) -> dict[str, float]:
    """Round a probability dict, then nudge the largest entry by the
    residual so the rounded values still sum to exactly 1.0."""
    rounded = {k: round(v, ndigits) for k, v in probs.items()}
    residual = round(1.0 - sum(rounded.values()), ndigits)
    if residual:
        key = max(rounded, key=lambda k: rounded[k])
        rounded[key] = round(rounded[key] + residual, ndigits)
    return rounded


# ------------------------------------------------------ Team strengths ----
def _days_ago(utc_str: str, today: date) -> float:
    """Days between today and an ISO-8601 UTC timestamp (never negative)."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        delta = (today - dt.date()).days
    except (ValueError, TypeError, AttributeError):
        delta = 0
    return max(float(delta), 0.0)


def _recency_weight(days_ago: float) -> float:
    """Exponential decay: weight halves every RECENCY_HALFLIFE_DAYS."""
    return 0.5 ** (days_ago / RECENCY_HALFLIFE_DAYS)


def _blend(raw: float, n_weighted: float) -> float:
    """Blend a raw strength toward 1.0 when data is thin.

    n_weighted >= MIN_MATCHES  -> raw (full trust)
    n_weighted == 0            -> 1.0 (league average)
    """
    confidence = min(1.0, n_weighted / MIN_MATCHES)
    return confidence * raw + (1.0 - confidence) * 1.0


def _safe_div(num: float, den: float, fallback: float = 1.0) -> float:
    return num / den if den > 0 else fallback


def build_team_stats(matches: list[dict], today: date | None = None):
    """Build attack/defense strengths from finished matches.

    Each match dict needs: homeTeam{ id }, awayTeam{ id },
    score{ fullTime{ home, away } }, utcDate, status == "FINISHED".

    Returns (team_stats, league_avgs) where
      team_stats[team_id] = {"attack_home", "defense_home",
                             "attack_away", "defense_away", "matches"}
      league_avgs = {"home": avg home goals, "away": avg away goals}
    """
    today = today or date.today()

    # weighted accumulators per team
    acc: dict[int, dict] = {}

    def team(tid: int) -> dict:
        return acc.setdefault(tid, {
            "hw": 0.0, "hgf": 0.0, "hga": 0.0,   # home: weight, scored, conceded
            "aw": 0.0, "agf": 0.0, "aga": 0.0,   # away: weight, scored, conceded
        })

    sum_w = 0.0
    sum_home_goals = 0.0
    sum_away_goals = 0.0

    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        try:
            hid = int(m["homeTeam"]["id"])
            aid = int(m["awayTeam"]["id"])
            hg = m["score"]["fullTime"]["home"]
            ag = m["score"]["fullTime"]["away"]
            if hg is None or ag is None:
                continue
            hg, ag = int(hg), int(ag)
        except (KeyError, TypeError, ValueError):
            continue

        w = _recency_weight(_days_ago(m.get("utcDate", ""), today))
        if w <= 0:
            continue

        h, a = team(hid), team(aid)
        h["hw"] += w
        h["hgf"] += w * hg
        h["hga"] += w * ag
        a["aw"] += w
        a["agf"] += w * ag
        a["aga"] += w * hg
        sum_w += w
        sum_home_goals += w * hg
        sum_away_goals += w * ag

    league_avgs = {
        "home": _safe_div(sum_home_goals, sum_w, 1.45),
        "away": _safe_div(sum_away_goals, sum_w, 1.15),
    }

    team_stats: dict[int, dict] = {}
    for tid, s in acc.items():
        attack_home = _blend(
            _safe_div(s["hgf"], s["hw"]) / league_avgs["home"], s["hw"])
        defense_home = _blend(
            _safe_div(s["hga"], s["hw"]) / league_avgs["away"], s["hw"])
        attack_away = _blend(
            _safe_div(s["agf"], s["aw"]) / league_avgs["away"], s["aw"])
        defense_away = _blend(
            _safe_div(s["aga"], s["aw"]) / league_avgs["home"], s["aw"])
        team_stats[tid] = {
            "attack_home": attack_home,
            "defense_home": defense_home,
            "attack_away": attack_away,
            "defense_away": defense_away,
            "matches": round(s["hw"] + s["aw"], 2),
        }
    return team_stats, league_avgs


_NEUTRAL = {"attack_home": 1.0, "defense_home": 1.0,
            "attack_away": 1.0, "defense_away": 1.0, "matches": 0.0}


def expected_goals(home_id: int, away_id: int,
                   team_stats: dict, league_avgs: dict) -> tuple[float, float]:
    """Expected goals for a fixture.

    hxg = home_attack(home) x away_defense(away) x league_avg_home_goals
    axg = away_attack(away) x home_defense(home) x league_avg_away_goals
    Unknown teams use neutral (1.0) strengths.
    """
    hs = team_stats.get(home_id, _NEUTRAL)
    aws = team_stats.get(away_id, _NEUTRAL)
    hxg = hs["attack_home"] * aws["defense_away"] * league_avgs["home"]
    axg = aws["attack_away"] * hs["defense_home"] * league_avgs["away"]
    return max(hxg, 0.0), max(axg, 0.0)


# --------------------------------------------------------- Score matrix ----
def score_matrix(hxg: float, axg: float,
                 max_goals: int = MAX_GOALS) -> list[list[float]]:
    """Full score-probability matrix; matrix[i][j] = P(home i - away j).

    Assumes independent Poisson goal counts; normalised to sum to 1.0.
    """
    home = poisson_distribution(hxg, max_goals)
    away = poisson_distribution(axg, max_goals)
    total = sum(home) * sum(away)
    total = total if total > 0 else 1.0
    return [[(home[i] * away[j]) / total
             for j in range(max_goals + 1)]
            for i in range(max_goals + 1)]


def _matrix_total(matrix: list[list[float]]) -> float:
    return sum(sum(row) for row in matrix) or 1.0


# -------------------------------------------------------------- Markets ----
def market_1x2(matrix: list[list[float]]) -> dict[str, float]:
    """Home / Draw / Away probabilities; sums to 1.0."""
    n = len(matrix)
    home = sum(matrix[i][j] for i in range(n) for j in range(n) if i > j)
    draw = sum(matrix[i][i] for i in range(n))
    away = sum(matrix[i][j] for i in range(n) for j in range(n) if i < j)
    home, draw, away = _normalize([home, draw, away])
    return {"home": home, "draw": draw, "away": away}


def market_over_under(matrix: list[list[float]],
                      line: float) -> dict[str, float]:
    """Over/Under for a .5 line (no push possible); over + under = 1."""
    n = len(matrix)
    over = sum(matrix[i][j] for i in range(n) for j in range(n)
               if i + j > line)
    under = sum(matrix[i][j] for i in range(n) for j in range(n)
                if i + j < line)
    over, under = _normalize([over, under])
    return {"over": over, "under": under}


def market_btts(matrix: list[list[float]]) -> dict[str, float]:
    """Both Teams To Score yes/no; yes + no = 1."""
    n = len(matrix)
    yes = sum(matrix[i][j] for i in range(n) for j in range(n)
              if i >= 1 and j >= 1)
    no = 1.0 - yes
    yes, no = _normalize([yes, no])
    return {"yes": yes, "no": no}


def top_correct_scores(matrix: list[list[float]],
                       n: int = 5) -> list[dict]:
    """The n most likely exact scorelines, descending by probability."""
    scored = [({"score": f"{i}-{j}", "prob": matrix[i][j]})
              for i in range(len(matrix)) for j in range(len(matrix))]
    scored.sort(key=lambda s: s["prob"], reverse=True)
    return scored[:n]


def market_asian_handicap(matrix: list[list[float]],
                          lines: tuple[float, ...] = (-1.5, -1.0, -0.5,
                                                      0.5, 1.0, 1.5)
                          ) -> dict[str, dict[str, float]]:
    """Asian Handicap home-cover probabilities per line.

    For line L: cover  = P(home_goals - away_goals + L > 0)
                push   = P(... == 0)          (integer lines only)
                not_cover = remainder
    cover + push + not_cover = 1 for every line (push = 0 on .5 lines).
    """
    n = len(matrix)
    out: dict[str, dict[str, float]] = {}
    for line in lines:
        cover = push = 0.0
        for i in range(n):
            for j in range(n):
                margin = (i - j) + line
                if margin > 0:
                    cover += matrix[i][j]
                elif margin == 0:
                    push += matrix[i][j]
        not_cover = 1.0 - cover - push
        cover, push, not_cover = _normalize([cover, push, not_cover])
        out[str(line)] = {"cover": cover, "push": push,
                          "not_cover": not_cover}
    return out


# -------------------------------------------------------- Full predict ----
def predict_match(home_id: int, away_id: int,
                  team_stats: dict, league_avgs: dict) -> dict:
    """Predict one fixture; returns xG, matrix-derived markets (all sum to 1)."""
    hxg, axg = expected_goals(home_id, away_id, team_stats, league_avgs)
    matrix = score_matrix(hxg, axg)
    return {
        "xg": {"home": round(hxg, 3), "away": round(axg, 3)},
        "markets": {
            "1x2": _rounded(market_1x2(matrix)),
            "ou": {str(line): _rounded(market_over_under(matrix, line))
                   for line in (1.5, 2.5, 3.5)},
            "btts": _rounded(market_btts(matrix)),
            "correct_scores": [
                {"score": s["score"], "prob": round(s["prob"], 4)}
                for s in top_correct_scores(matrix, 5)
            ],
            "ah": {line: _rounded(probs)
                   for line, probs in
                   market_asian_handicap(matrix).items()},
        },
    }
