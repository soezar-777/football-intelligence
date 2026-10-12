#!/usr/bin/env python3
"""Fetch Sweden's Allsvenskan from free sources.

football-data.org's free tier has no Swedish league, and API-Football's
free tier is season-capped (2022-2024), so this module combines two free
sources (same pattern as fetch_espn.py for Segunda):

* Results (team-strength training): football-data.co.uk new/SWE.csv --
  free CSV, all-seasons archive, includes full-time scores.
* Upcoming fixtures: ESPN's public scoreboard API (swe.1) -- free, no key,
  queried per date for the next `days_ahead` days.

Both are normalized into the same shape as football-data.org v4 match
objects, so the rest of the pipeline (predict -> verify -> performance)
works unchanged.

Match IDs are offset by ESPN_ID_OFFSET to avoid collision with other
sources in the shared prediction history. CSV results and ESPN fixtures
are deduplicated by (home, away, date).
"""

import csv
import io
import json
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ESPN_ID_OFFSET = 5_000_000
CSV_ID_BASE = 5_900_000
STOCKHOLM = ZoneInfo("Europe/Stockholm")

CSV_URL = "https://www.football-data.co.uk/new/SWE.csv"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/swe.1/scoreboard"

# football-data.co.uk name -> canonical (ESPN-style) name
TEAM_CANONICAL = {
    "AIK": "AIK",
    "Brommapojkarna": "IF Brommapojkarna",
    "Degerfors": "Degerfors IF",
    "Djurgarden": "Djurgårdens IF",
    "Elfsborg": "IF Elfsborg",
    "GAIS": "GAIS",
    "Goteborg": "IFK Göteborg",
    "Hacken": "BK Häcken",
    "Halmstad": "Halmstads BK",
    "Hammarby": "Hammarby IF",
    "Kalmar": "Kalmar FF",
    "Malmo FF": "Malmö FF",
    "Mjallby": "Mjällby AIF",
    "Norrkoping": "IFK Norrköping",
    "Orgryte": "Örgryte IS",
    "Oster": "Östers IF",
    "Osters": "Östers IF",
    "Sirius": "IK Sirius",
    "Varnamo": "IFK Värnamo",
    "Vasteras SK": "Västerås SK",
}


def _norm(name: str) -> str:
    n = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode()
    n = n.lower().strip()
    for p in ("if ", "ifk ", "ik ", "bk "):
        if n.startswith(p):
            n = n[len(p):]
            break
    return n.strip()


def canonical_name(name: str) -> str:
    if name in TEAM_CANONICAL:
        return TEAM_CANONICAL[name]
    want = _norm(name)
    for csv_name, canon in TEAM_CANONICAL.items():
        if _norm(csv_name) == want or _norm(canon) == want:
            return canon
    print(f"[allsvenskan] unmapped team name: {name!r}", flush=True)
    return name


def _get(url: str, retries: int = 4):
    backoff = 8
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001 - retry on any fetch error
            print(f"[allsvenskan] {url[:80]} failed (attempt {attempt}/{retries}): "
                  f"{exc}; retry in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"[allsvenskan] gave up on {url[:80]}")


def _stockholm_to_utc(date_ddmmyyyy: str, time_hhmm: str) -> str:
    dt = datetime.strptime(f"{date_ddmmyyyy} {time_hhmm}", "%d/%m/%Y %H:%M")
    dt = dt.replace(tzinfo=STOCKHOLM)
    return dt.astimezone(timezone.utc).isoformat()


def fetch_alv_results() -> list:
    raw = _get(CSV_URL).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    names = sorted({canonical_name(r["Home"].strip()) for r in rows}
                   | {canonical_name(r["Away"].strip()) for r in rows})
    tid = {n: CSV_ID_BASE + 100 + i for i, n in enumerate(names)}
    matches = []
    for i, r in enumerate(rows):
        if not r.get("HG"):
            continue
        try:
            hg, ag = int(r["HG"]), int(r["AG"])
        except (ValueError, TypeError):
            continue
        home = canonical_name(r["Home"].strip())
        away = canonical_name(r["Away"].strip())
        matches.append({
            "id": CSV_ID_BASE + i,
            "utcDate": _stockholm_to_utc(r["Date"].strip(),
                                        r["Time"].strip() or "00:00"),
            "status": "FINISHED",
            "homeTeam": {"id": tid[home],
                         "name": home, "shortName": "", "tla": ""},
            "awayTeam": {"id": tid[away],
                         "name": away, "shortName": "", "tla": ""},
            "score": {"fullTime": {"home": hg, "away": ag}},
            "competition": {"code": "ALV", "name": "Allsvenskan"},
        })
    print(f"[allsvenskan] ALV results (csv): {len(matches)} finished",
          flush=True)
    return matches, tid


def _espn_teams(competitors: list) -> tuple:
    home = away = None
    hs = aws = None
    for c in competitors:
        t = c.get("team") or {}
        nm = canonical_name(t.get("displayName") or "?")
        if c.get("homeAway") == "home":
            home, hs = nm, c.get("score")
        else:
            away, aws = nm, c.get("score")
    return home, away, hs, aws


def fetch_alv_fixtures(days_ahead: int = 14, tid: dict | None = None) -> list:
    tid = tid or {}
    matches = []
    today = datetime.now(timezone.utc).date()
    for delta in range(days_ahead + 1):
        day = today + timedelta(days=delta)
        url = f"{ESPN_URL}?dates={day.strftime('%Y%m%d')}"
        try:
            payload = json.loads(_get(url))
        except RuntimeError:
            continue
        for e in payload.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            st = (comp.get("status") or {}).get("type") or {}
            finished = st.get("name") == "STATUS_FULL_TIME"
            home, away, hs, aws = _espn_teams(comp.get("competitors") or [])
            if not home or not away:
                continue
            try:
                eid = int(str(e.get("id", "0"))[-9:])
            except ValueError:
                eid = abs(int(str(e.get("id", "")).encode().hex()[:8], 16)) % 10**8
            try:
                hg = int(hs) if finished and hs is not None else None
                ag = int(aws) if finished and aws is not None else None
            except (ValueError, TypeError):
                hg = ag = None
            hid = tid.get(home, ESPN_ID_OFFSET + 100 + len(tid))
            aid = tid.get(away, ESPN_ID_OFFSET + 101 + len(tid))
            matches.append({
                "id": ESPN_ID_OFFSET + eid,
                "utcDate": e.get("date"),
                "status": "FINISHED" if finished else "TIMED",
                "homeTeam": {"id": hid,
                             "name": home, "shortName": "", "tla": ""},
                "awayTeam": {"id": aid,
                             "name": away, "shortName": "", "tla": ""},
                "score": {"fullTime": {"home": hg, "away": ag}},
                "competition": {"code": "ALV", "name": "Allsvenskan"},
            })
        time.sleep(0.4)  # be polite to the unofficial API
    print(f"[allsvenskan] ALV fixtures: {len(matches)} events in {days_ahead}d",
          flush=True)
    return matches


def fetch_alv_matches(days_ahead: int = 14) -> dict:
    results, tid = fetch_alv_results()
    fixtures = fetch_alv_fixtures(days_ahead, tid)
    seen = set()
    matches = []
    for m in results + fixtures:
        key = (_norm(m["homeTeam"]["name"]), _norm(m["awayTeam"]["name"]),
               (m.get("utcDate") or "")[:10])
        if key in seen:
            continue
        seen.add(key)
        matches.append(m)
    matches.sort(key=lambda m: m.get("utcDate") or "")
    finished = sum(1 for m in matches if m["status"] == "FINISHED")
    print(f"[allsvenskan] ALV total: {len(matches)} matches "
          f"({finished} finished)", flush=True)
    return {
        "competition": {"code": "ALV", "name": "Allsvenskan"},
        "matches": matches,
    }


if __name__ == "__main__":
    payload = fetch_alv_matches()
    print(json.dumps({"matches": len(payload["matches"])}, indent=2))
