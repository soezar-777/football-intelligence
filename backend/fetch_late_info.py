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


def _kickoff_lineups(day: str, home_id: int, away_id: int,
                     reg: dict) -> tuple[dict | None, str]:
    """Lineups via KickoffAPI (user's free Hobby key, verified 2026-10-20:
    /fixtures/lineups works on the free plan). Covers every competition,
    including ones ESPN has no slug for. The day's fixture list is cached
    for 10 minutes so a full match night costs ~1 + n calls of the
    100/day budget. Returns (lineups|None, note)."""
    try:
        sys.path.insert(0, "/home/hatch/workspace/custom-connectors/"
                           "custom.kickoffapi/bin")
        import kickoff  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return None, f"KickoffAPI unavailable: {e}"
    cache = config.DATA_DIR / f"kickoff_fixtures_{day}.json"
    body = None
    try:
        import time
        if cache.exists() and time.time() - cache.stat().st_mtime < 600:
            body = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        body = None
    if body is None:
        out = kickoff.get(f"/fixtures?date={day}")
        if out.get("status") != 200:
            return None, f"KickoffAPI fixtures HTTP {out.get('status')}"
        body = out.get("body") or {}
        try:
            cache.write_text(json.dumps(body), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    fixture = None
    for fx in body.get("response", []):
        hn = ((fx.get("homeTeam") or {}).get("name")) or ""
        an = ((fx.get("awayTeam") or {}).get("name")) or ""
        h = _map_team(hn, reg, {})
        a = _map_team(an, reg, {})
        if h and a and h[0] == home_id and a[0] == away_id:
            fixture = fx
            break
    if not fixture:
        return None, "fixture not found on KickoffAPI"
    out = kickoff.get(f"/fixtures/lineups?fixture={fixture['id']}")
    if out.get("status") != 200:
        return None, f"KickoffAPI lineups HTTP {out.get('status')}"
    resp = (out.get("body") or {}).get("response") or []
    lus: dict = {}
    for entry in resp:
        xi = [((p.get("player") or {}).get("name")) or ""
              for p in entry.get("startXI", [])]
        xi = [x for x in xi if x]
        if not xi:
            continue
        side = ("home" if entry.get("teamId") == fixture.get("homeTeamId")
                else "away")
        lus[side] = {"formation": entry.get("formation"), "xi": xi}
    if lus.get("home") or lus.get("away"):
        return lus, "KickoffAPI"
    return None, "lineups not announced yet (KickoffAPI)"


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
        info["notes"].append("team(s) not in registry — no lookup")
    else:
        # Primary: KickoffAPI (all competitions). Fallback: ESPN (venue,
        # weather, and lineups for the leagues it covers).
        lus, note = _kickoff_lineups(day, home[0], away[0], reg)
        if lus:
            info["lineups"] = lus
            info["notes"].append(f"lineups via {note}")
        else:
            info["notes"].append(note)
        if code in ESPN_SLUGS:
            try:
                ev_id = _find_event(ESPN_SLUGS[code], day, home[0],
                                    away[0], reg)
                if ev_id:
                    s = _get(f"https://site.api.espn.com/apis/site/v2/"
                             f"sports/soccer/{ESPN_SLUGS[code]}/summary"
                             f"?event={ev_id}")
                    if info["lineups"] is None:
                        elus = _lineups(s)
                        if elus.get("home", {}).get("xi") or \
                                elus.get("away", {}).get("xi"):
                            info["lineups"] = elus
                            info["notes"].append("lineups via ESPN")
                    gi = s.get("gameInfo") or {}
                    venue = gi.get("venue") or {}
                    info["venue"] = venue.get("fullName") or None
                    w = gi.get("weather") or {}
                    info["weather"] = w.get("displayValue") or None
                else:
                    info["notes"].append("fixture not found on ESPN today")
            except Exception as e:  # noqa: BLE001
                info["notes"].append(f"ESPN lookup failed: {e}")
        if info["lineups"] is None and not any(
                "not announced" in n for n in info["notes"]):
            info["notes"].append("lineups not announced yet")
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
