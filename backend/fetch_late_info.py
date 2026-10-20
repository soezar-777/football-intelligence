#!/usr/bin/env python3
"""Late pre-match information for one fixture (redesign section E).

Collects what is actually knowable shortly before kickoff and returns it
as structured JSON — facts only, nothing estimated:

  * confirmed starting XIs + formations (ESPN summary `rosters`, major
    competitions; lineups usually appear ~60-75 min before kickoff)
  * venue + weather as reported by ESPN gameInfo (when present)
  * Premier League ruled-out players (data/injuries_PL.json, Path 1 feed)

Usage:
  python3 fetch_late_info.py <CODE> "<home name>" "<away name>" [YYYY-MM-DD]

Every call is appended to data/late_info_log.jsonl (fixture, timestamp,
what was found) so flagged matches can be graded later and a numeric
adjustment can be backtested before it is ever applied — the same gate
that rejected rest-days and Dixon-Coles.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from fetch_seed import _norm, _map_team, _registry  # noqa: E402

ESPN_SLUGS = {
    "CL": "uefa.champions", "PL": "eng.1", "ELC": "eng.2", "PD": "esp.1",
    "SA": "ita.1", "BL1": "ger.1", "FL1": "fra.1", "DED": "ned.1",
    "PPL": "por.1", "BSA": "bra.1",
}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _find_event(slug: str, day: str, home_id: int, away_id: int,
                reg: dict) -> str | None:
    """ESPN event id for the fixture on YYYYMMDD, matched by team ids."""
    data = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
                f"{slug}/scoreboard?dates={day.replace('-', '')}")
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        ids = set()
        for c in comp.get("competitors", []):
            nm = ((c.get("team") or {}).get("displayName")
                  or (c.get("team") or {}).get("name") or "")
            hit = _map_team(nm, reg, {})
            if hit:
                ids.add(hit[0])
        if home_id in ids and away_id in ids:
            return ev.get("id")
    return None


def _lineups(summary: dict) -> dict:
    out = {}
    for side in summary.get("rosters", []):
        players = []
        for p in side.get("roster", []):
            if p.get("starter"):
                players.append(((p.get("athlete") or {})
                                .get("displayName")) or "")
        out[side.get("homeAway")] = {
            "formation": side.get("formation"),
            "xi": [x for x in players if x],
        }
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    code, home_name, away_name = argv[0], argv[1], argv[2]
    day = argv[3] if len(argv) > 3 else datetime.now(timezone.utc) \
        .date().isoformat()
    reg = _registry(code)
    home = _map_team(home_name, reg, {})
    away = _map_team(away_name, reg, {})
    info: dict = {
        "competition": code, "home": home_name, "away": away_name,
        "date": day, "checked_at": datetime.now(timezone.utc).isoformat(),
        "lineups": None, "venue": None, "weather": None,
        "ruled_out": {}, "notes": [],
    }
    if not home or not away:
        info["notes"].append("team(s) not in registry — no ESPN lookup")
    elif code in ESPN_SLUGS:
        try:
            ev_id = _find_event(ESPN_SLUGS[code], day, home[0], away[0], reg)
            if ev_id:
                s = _get(f"https://site.api.espn.com/apis/site/v2/sports/"
                         f"soccer/{ESPN_SLUGS[code]}/summary?event={ev_id}")
                lus = _lineups(s)
                if lus.get("home", {}).get("xi") or \
                        lus.get("away", {}).get("xi"):
                    info["lineups"] = lus
                else:
                    info["notes"].append("lineups not announced yet")
                gi = s.get("gameInfo") or {}
                venue = gi.get("venue") or {}
                info["venue"] = venue.get("fullName") or None
                w = gi.get("weather") or {}
                info["weather"] = w.get("displayValue") or None
            else:
                info["notes"].append("fixture not found on ESPN today")
        except Exception as e:  # noqa: BLE001
            info["notes"].append(f"ESPN lookup failed: {e}")
    else:
        info["notes"].append("no ESPN coverage for this competition")
    if code == "PL":
        inj_path = config.DATA_DIR / "injuries_PL.json"
        if inj_path.exists():
            inj = json.loads(inj_path.read_text(encoding="utf-8"))
            for label, team in (("home", home), ("away", away)):
                if team:
                    info["ruled_out"][label] = inj.get(team[1], [])
    log = config.DATA_DIR / "late_info_log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(info, ensure_ascii=False) + "\n")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
