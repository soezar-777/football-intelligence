#!/usr/bin/env python3
"""Aggregate model performance from verification.json.

Outputs data/performance.json:
  * hit-rate per market (overall)
  * hit-rate per market per competition
  * rolling last-30 graded predictions (by kickoff)
  * Brier score for the 1X2 market (lower is better; 0 = perfect)
"""

import json
import sys
from datetime import datetime, timezone

import config

MARKETS = ("1x2", "ou25", "btts", "ah", "correct_score")


def _hit_rates(matches: list[dict]) -> dict:
    out = {}
    for market in MARKETS:
        decided = [m for m in matches if m["grades"][market]["hit"] is not None]
        hits = sum(1 for m in decided if m["grades"][market]["hit"])
        out[market] = {
            "graded": len(decided),
            "hit": hits,
            "hit_rate": round(hits / len(decided), 4) if decided else None,
        }
    return out


def _brier_1x2(matches: list[dict]) -> float | None:
    """Mean squared error of 1X2 probability vectors vs actual outcome."""
    scores = []
    for m in matches:
        probs = m.get("probs_1x2") or {}
        actual = m.get("actual", "")
        try:
            hg, ag = (int(x) for x in actual.split("-"))
        except (ValueError, AttributeError):
            continue
        truth = {"home": 0.0, "draw": 0.0, "away": 0.0}
        truth["home" if hg > ag else "away" if hg < ag else "draw"] = 1.0
        try:
            err = sum((float(probs[k]) - truth[k]) ** 2 for k in truth)
        except (KeyError, TypeError, ValueError):
            continue
        scores.append(err)
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def aggregate() -> dict:
    path = config.DATA_DIR / "verification.json"
    if not path.exists():
        print("[performance] no verification.json yet", flush=True)
        matches: list[dict] = []
    else:
        matches = json.loads(path.read_text(encoding="utf-8")).get("matches", [])

    by_competition: dict[str, dict] = {}
    for code in sorted({m.get("competition") for m in matches if m.get("competition")}):
        by_competition[code] = _hit_rates(
            [m for m in matches if m.get("competition") == code])

    ordered = sorted(matches, key=lambda m: m.get("kickoff") or "")
    rolling = _hit_rates(ordered[-30:])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": config.MODEL_VERSION,
        "graded_total": len(matches),
        "overall": _hit_rates(matches),
        "by_competition": by_competition,
        "rolling_last_30": rolling,
        "brier_1x2": _brier_1x2(matches),
    }


def main() -> int:
    out = aggregate()
    path = config.DATA_DIR / "performance.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"[performance] wrote {path.name}: {out['graded_total']} graded, "
          f"brier_1x2={out['brier_1x2']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
