#!/usr/bin/env python3
"""Build Poisson predictions for every scheduled fixture.

Reads data/matches_<CODE>.json, trains team strengths on FINISHED matches,
predicts SCHEDULED/TIMED/POSTPONED fixtures and writes data/predictions.json.

Each prediction carries all market probabilities plus a top pick per market;
a pick is only published when its probability clears the MIN_EDGE threshold.
"""

import json
import sys
from datetime import datetime, timezone

import config
from poisson import build_team_stats, predict_match

UPCOMING_STATUSES = ("SCHEDULED", "TIMED", "POSTPONED")


def _team_info(side: dict) -> dict:
    return {
        "id": side.get("id"),
        "name": side.get("name") or side.get("shortName") or "?",
        "tla": side.get("tla") or "",
    }


def _choose_pick(probs: dict[str, float], threshold: float) -> dict | None:
    """Highest-probability outcome, or None if it misses the edge threshold."""
    if not probs:
        return None
    selection, prob = max(probs.items(), key=lambda kv: kv[1])
    if prob >= threshold:
        return {"selection": selection, "prob": prob}
    return None


def _pick_ah(ah_markets: dict) -> dict | None:
    """Most informative Asian Handicap call.

    Among all (line, side) combos clearing the edge threshold, take the one
    closest to 50/50 -- the "fairest" line, where the model's call says the
    most. Trivial near-certainties (e.g. home +1.5 cover at 90%) are skipped
    in favour of a genuinely decisive handicap line.
    """
    best = None  # (distance from 0.5, line, side, prob)
    for line, probs in ah_markets.items():
        for side in ("cover", "not_cover"):
            p = probs.get(side, 0.0)
            if p >= config.MIN_EDGE["ah"]:
                dist = abs(p - 0.5)
                if best is None or dist < best[0]:
                    best = (dist, line, side, p)
    if best is None:
        return None
    _, line, side, prob = best
    return {"line": line, "side": f"home_{side}", "prob": prob}


def _picks(markets: dict) -> dict:
    ou25 = markets["ou"]["2.5"]
    btts = markets["btts"]
    # Asian Handicap: the most informative (closest to 50/50) line/side
    # clearing the edge threshold.
    ah_pick = _pick_ah(markets["ah"])
    top_cs = markets["correct_scores"][0] if markets["correct_scores"] else None
    return {
        "1x2": _choose_pick(markets["1x2"], config.MIN_EDGE["1x2"]),
        "ou25": _choose_pick(ou25, config.MIN_EDGE["ou25"]),
        "btts": _choose_pick(btts, config.MIN_EDGE["btts"]),
        "ah": ah_pick,
        "correct_score": (
            {"selection": top_cs["score"], "prob": top_cs["prob"]}
            if top_cs and top_cs["prob"] >= config.MIN_EDGE["correct_score"]
            else None
        ),
    }


def predict_all(codes: list[str]) -> dict:
    predictions = []
    skipped = 0
    for code in codes:
        path = config.DATA_DIR / f"matches_{code}.json"
        if not path.exists():
            print(f"[predict] {code}: no matches file, skipping", flush=True)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        matches = payload.get("matches", [])
        finished = [m for m in matches if m.get("status") == "FINISHED"]
        upcoming = [m for m in matches if m.get("status") in UPCOMING_STATUSES]

        team_stats, league_avgs = build_team_stats(finished)
        print(f"[predict] {code}: {len(finished)} finished -> stats for "
              f"{len(team_stats)} teams; {len(upcoming)} upcoming fixtures",
              flush=True)

        for m in upcoming:
            try:
                home = _team_info(m["homeTeam"])
                away = _team_info(m["awayTeam"])
                if home["id"] is None or away["id"] is None:
                    skipped += 1
                    continue
                result = predict_match(home["id"], away["id"],
                                       team_stats, league_avgs)
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue
            predictions.append({
                "fixture_id": m.get("id"),
                "competition": code,
                "home_team": home,
                "away_team": away,
                "kickoff": m.get("utcDate"),
                "status": m.get("status"),
                "xg": result["xg"],
                "markets": result["markets"],
                "picks": _picks(result["markets"]),
            })

    predictions.sort(key=lambda p: p.get("kickoff") or "")
    return {
        "model_version": config.MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(predictions),
        "skipped": skipped,
        "predictions": predictions,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Predict scheduled fixtures")
    ap.add_argument("--competitions", default=",".join(config.COMPETITIONS))
    args = ap.parse_args(argv)
    codes = [c.strip().upper() for c in args.competitions.split(",") if c.strip()]

    out = predict_all(codes)
    path = config.DATA_DIR / "predictions.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"[predict] wrote {path.name}: {out['count']} predictions "
          f"({out['skipped']} skipped)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
