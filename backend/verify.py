#!/usr/bin/env python3
"""Grade predictions against actual finished results.

Loads data/predictions.json and data/matches_<CODE>.json, matches each
prediction to its fixture's final score, and grades every published pick
hit / miss / void (push). Writes data/verification.json with per-match
grades plus a summary.

Predictions for fixtures that are not FINISHED yet are simply not graded --
they will be picked up on a later run.
"""

import json
import sys
from datetime import datetime, timezone

import config


def _outcome(hg: int, ag: int) -> str:
    if hg > ag:
        return "home"
    if hg < ag:
        return "away"
    return "draw"


def _grade_1x2(pick: dict | None, hg: int, ag: int) -> dict:
    if not pick:
        return {"pick": None, "hit": None}
    return {"pick": pick["selection"], "hit": pick["selection"] == _outcome(hg, ag)}


def _grade_ou25(pick: dict | None, hg: int, ag: int) -> dict:
    if not pick:
        return {"pick": None, "hit": None}
    actual = "over" if hg + ag > 2.5 else "under"
    return {"pick": pick["selection"], "hit": pick["selection"] == actual}


def _grade_btts(pick: dict | None, hg: int, ag: int) -> dict:
    if not pick:
        return {"pick": None, "hit": None}
    actual = "yes" if hg >= 1 and ag >= 1 else "no"
    return {"pick": pick["selection"], "hit": pick["selection"] == actual}


def _grade_correct_score(pick: dict | None, hg: int, ag: int) -> dict:
    if not pick:
        return {"pick": None, "hit": None}
    return {"pick": pick["selection"], "hit": pick["selection"] == f"{hg}-{ag}"}


def _grade_ah(pick: dict | None, hg: int, ag: int) -> dict:
    """Asian Handicap: push (exact line) grades as void (hit=None)."""
    if not pick:
        return {"pick": None, "hit": None}
    try:
        line = float(pick["line"])
    except (TypeError, ValueError):
        return {"pick": None, "hit": None}
    margin = (hg - ag) + line
    label = f"{pick['line']}:{pick['side']}"
    if margin == 0:
        return {"pick": label, "hit": None}  # push = void
    cover = margin > 0
    hit = cover if pick["side"] == "home_cover" else not cover
    return {"pick": label, "hit": hit}


def verify_all() -> dict:
    pred_path = config.DATA_DIR / "predictions.json"
    if not pred_path.exists():
        print("[verify] no predictions.json yet; nothing to grade", flush=True)
        return {"generated_at": datetime.now(timezone.utc).isoformat(),
                "graded_count": 0, "matches": [], "summary": {}}

    predictions = json.loads(pred_path.read_text(encoding="utf-8"))["predictions"]

    # fixture_id -> (home goals, away goals) for every FINISHED match we know
    results: dict[int, tuple[int, int]] = {}
    for code in config.COMPETITIONS:
        path = config.DATA_DIR / f"matches_{code}.json"
        if not path.exists():
            continue
        for m in json.loads(path.read_text(encoding="utf-8")).get("matches", []):
            if m.get("status") != "FINISHED":
                continue
            try:
                ft = m["score"]["fullTime"]
                if ft["home"] is None or ft["away"] is None:
                    continue
                results[int(m["id"])] = (int(ft["home"]), int(ft["away"]))
            except (KeyError, TypeError, ValueError):
                continue

    graded = []
    for p in predictions:
        fid = p.get("fixture_id")
        if fid is None or int(fid) not in results:
            continue
        hg, ag = results[int(fid)]
        picks = p.get("picks", {})
        grades = {
            "1x2": _grade_1x2(picks.get("1x2"), hg, ag),
            "ou25": _grade_ou25(picks.get("ou25"), hg, ag),
            "btts": _grade_btts(picks.get("btts"), hg, ag),
            "ah": _grade_ah(picks.get("ah"), hg, ag),
            "correct_score": _grade_correct_score(picks.get("correct_score"),
                                                  hg, ag),
        }
        graded.append({
            "fixture_id": fid,
            "competition": p.get("competition"),
            "home_team": p.get("home_team", {}).get("name"),
            "away_team": p.get("away_team", {}).get("name"),
            "kickoff": p.get("kickoff"),
            "actual": f"{hg}-{ag}",
            "probs_1x2": p.get("markets", {}).get("1x2"),
            "grades": grades,
        })

    graded.sort(key=lambda g: g.get("kickoff") or "")

    summary: dict[str, dict] = {}
    for market in ("1x2", "ou25", "btts", "ah", "correct_score"):
        decided = [g for g in graded if g["grades"][market]["hit"] is not None]
        hits = sum(1 for g in decided if g["grades"][market]["hit"])
        summary[market] = {
            "graded": len(decided),
            "hit": hits,
            "hit_rate": round(hits / len(decided), 4) if decided else None,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": config.MODEL_VERSION,
        "graded_count": len(graded),
        "matches": graded,
        "summary": summary,
    }


def main() -> int:
    out = verify_all()
    path = config.DATA_DIR / "verification.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"[verify] wrote {path.name}: {out['graded_count']} matches graded",
          flush=True)
    for market, s in out["summary"].items():
        print(f"[verify]   {market}: {s['hit']}/{s['graded']} "
              f"hit_rate={s['hit_rate']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
