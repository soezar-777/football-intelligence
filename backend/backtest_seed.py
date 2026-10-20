#!/usr/bin/env python3
"""Point-in-time backtest gate for the multi-season seed (2026-10-20).

For every graded fixture in prediction_history.json, rebuild the model
twice as of its kickoff date:
  A) current-season matches only          (post-B settings, MIN_MATCHES=8)
  B) A + last-season seed matches         (fetch_seed.py output)
and compare Brier scores. The seed ships only if B is not worse overall.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from poisson import build_team_stats, predict_match  # noqa: E402


def load_matches(code: str) -> list[dict]:
    p = config.DATA_DIR / f"matches_{code}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("matches", [])


def load_seed(code: str) -> list[dict]:
    p = config.DATA_DIR / f"seed_{code}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("matches", [])


def brier_1x2(probs: dict, actual: str) -> float:
    return sum((probs.get(k, 0.0) - (1.0 if k == actual else 0.0)) ** 2
               for k in ("home", "draw", "away"))


def main() -> int:
    hist = json.loads((config.DATA_DIR / "prediction_history.json")
                      .read_text(encoding="utf-8"))
    results: dict[str, tuple[int, int]] = {}
    matches_by_comp: dict[str, list[dict]] = {}
    seed_by_comp: dict[str, list[dict]] = {}
    for code in config.COMPETITIONS:
        ms = load_matches(code)
        matches_by_comp[code] = ms
        seed_by_comp[code] = load_seed(code)
        for m in ms:
            if m.get("status") == "FINISHED":
                sc = (m.get("score") or {}).get("fullTime") or {}
                if sc.get("home") is not None:
                    results[str(m.get("id"))] = (sc["home"], sc["away"])

    agg = {"A": [0.0, 0.0, 0], "B": [0.0, 0.0, 0]}  # 1x2, ou, n
    per_comp: dict[str, dict] = defaultdict(
        lambda: {"A": [0.0, 0], "B": [0.0, 0]})
    skipped = 0
    for fid, p in hist.items():
        if fid not in results:
            continue
        code = p.get("competition")
        ko = (p.get("kickoff") or "")[:10]
        if not code or not ko:
            skipped += 1
            continue
        hg, ag = results[fid]
        actual = "home" if hg > ag else "draw" if hg == ag else "away"
        over = 1.0 if hg + ag > 2.5 else 0.0
        hid = (p.get("home_team") or {}).get("id")
        aid = (p.get("away_team") or {}).get("id")
        if hid is None or aid is None:
            skipped += 1
            continue
        base = [m for m in matches_by_comp.get(code, [])
                if m.get("status") == "FINISHED"
                and (m.get("utcDate") or "")[:10] < ko]
        variants = {
            "A": base,
            "B": base + [m for m in seed_by_comp.get(code, [])
                         if (m.get("utcDate") or "")[:10] < ko],
        }
        try:
            kd = date.fromisoformat(ko)
        except ValueError:
            skipped += 1
            continue
        for tag, train in variants.items():
            stats, avgs = build_team_stats(train, kd)
            try:
                r = predict_match(hid, aid, stats, avgs)
            except Exception:  # noqa: BLE001
                continue
            b1 = brier_1x2(r["markets"]["1x2"], actual)
            bo = (r["markets"]["ou"]["2.5"]["over"] - over) ** 2
            agg[tag][0] += b1; agg[tag][1] += bo; agg[tag][2] += 1
            per_comp[code][tag][0] += b1; per_comp[code][tag][1] += 1
    for tag in ("A", "B"):
        s1, so, n = agg[tag]
        print(f"{tag}: n={n}  1X2 Brier {s1/max(n,1):.4f}  "
              f"OU Brier {so/max(n,1):.4f}")
    print(f"skipped: {skipped}")
    print("per-comp 1X2 Brier (A -> B):")
    for code in sorted(per_comp):
        a, b = per_comp[code]["A"], per_comp[code]["B"]
        if a[1]:
            print(f"  {code}: {a[0]/a[1]:.4f} -> {b[0]/b[1]:.4f}  (n={a[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
