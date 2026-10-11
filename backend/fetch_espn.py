#!/usr/bin/env python3
"""Fetch Spain's Segunda Division (LALIGA 2) from free sources.

football-data.org has no Segunda Division at all, and API-Football's free
tier is season-capped (2022-2024), so this module combines two free sources:

* Results (team-strength training): football-data.co.uk SP2.csv -- free CSV,
  updated after each matchday, includes full-time scores.
* Upcoming fixtures: ESPN's public scoreboard API (esp.2) -- free, no key,
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

ESPN_ID_OFFSET = 4_000_000
CSV_ID_BASE = 4_900_000
MADRID = ZoneInfo("Europe/Madrid")

CSV_URL = "https://www.football-data.co.uk/mmz4281/2627/SP2.csv"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.2/scoreboard"

# football-data.co.uk name -> canonical (ESPN-style) name
TEAM_CANONICAL = {
    "Albacete": "Albacete",
    "Almeria": "Almería",
    "Andorra": "FC Andorra",
    "Burgos": "Burgos",
    "Cadiz": "Cádiz",
    "Castellon": "Castellón",
    "Celta B": "Celta Vigo II",
    "RC Celta Fortuna": "Celta Vigo II",
    "Ceuta": "Ceuta",
    "Cordoba": "Córdoba",
    "Eibar": "Eibar",
    "Eldense": "Eldense",
    "Girona": "Girona",
    "Granada": "Granada",
    "Las Palmas": "Las Palmas",
    "Leganes": "Leganés",
    "Mallorca": "Mallorca",
    "Oviedo": "Real Oviedo",
    "Sabadell": "CD Sabadell",
    "Sociedad B": "Real Sociedad II",
    "Sp Gijon": "Sporting Gijón",
    "Tenerife": "Tenerife",
    "Valladolid": "Real Valladolid",
}


def _norm(name: str) -> str:
    n = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode()
    n = n.lower().strip()
    for p in ("fc ", "cd ", "real ", "sporting ", "sp "):
        if n.startswith(p):
            n = n[len(p):]
            break
    n = n.replace(" ii", "").replace(" b", "")
    return n.strip()


def canonical_name(name: str) -> str:
    if name in TEAM_CANONICAL:
        return TEAM_CANONICAL[name]
    # fallback: match by normalized form
    want = _norm(name)
    for csv_name, canon in TEAM_CANONICAL.items():
        if _norm(csv_name) == want or _norm(canon) == want:
            return canon
    print(f"[espn] unmapped team name: {name!r}", flush=True)
    return name


def _get(url: str, retries: int = 4):
    backoff = 8
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001 - retry on any fetch error
            print(f"[espn] {url[:80]} failed (attempt {attempt}/{retries}): "
                  f"{exc}; retry in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"[espn] gave up on {url[:80]}")


def _madrid_to_utc(date_ddmmyyyy: str, time_hhmm: str) -> str:
    dt = datetime.strptime(f"{date_ddmmyyyy} {time_hhmm}", "%d/%m/%Y %H:%M")
    dt = dt.replace(tzinfo=MADRID)
    return dt.astimezone(timezone.utc).isoformat()


def fetch_sdv_results() -> list:
    raw = _get(CSV_URL).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    # deterministic team ids from sorted canonical names
    names = sorted({canonical_name(r["HomeTeam"].strip()) for r in rows}
                   | {canonical_name(r["AwayTeam"].strip()) for r in rows})
    tid = {n: CSV_ID_BASE + 100 + i for i, n in enumerate(names)}
    matches = []
    for i, r in enumerate(rows):
        if not r.get("FTHG"):
            continue
        try:
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
        except (ValueError, TypeError):
            continue
        home = canonical_name(r["HomeTeam"].strip())
        away = canonical_name(r["AwayTeam"].strip())
        matches.append({
            "id": CSV_ID_BASE + i,
            "utcDate": _madrid_to_utc(r["Date"].strip(), r["Time"].strip() or "00:00"),
            "status": "FINISHED",
            "homeTeam": {"id": tid[home],
                         "name": home, "shortName": "", "tla": ""},
            "awayTeam": {"id": tid[away],
                         "name": away, "shortName": "", "tla": ""},
            "score": {"fullTime": {"home": hg, "away": ag}},
            "competition": {"code": "SDV", "name": "Segunda Division"},
        })
    print(f"[espn] SDV results (csv): {len(matches)} finished", flush=True)
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


def fetch_sdv_fixtures(days_ahead: int = 14, tid: dict | None = None) -> list:
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
                "competition": {"code": "SDV", "name": "Segunda Division"},
            })
        time.sleep(0.4)  # be polite to the unofficial API
    print(f"[espn] SDV fixtures: {len(matches)} events in {days_ahead}d",
          flush=True)
    return matches


def fetch_sdv_matches(days_ahead: int = 14) -> dict:
    results, tid = fetch_sdv_results()
    fixtures = fetch_sdv_fixtures(days_ahead, tid)
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
    print(f"[espn] SDV total: {len(matches)} matches ({finished} finished)",
          flush=True)
    return {
        "competition": {"code": "SDV", "name": "Segunda Division"},
        "matches": matches,
    }


if __name__ == "__main__":
    payload = fetch_sdv_matches()
    print(json.dumps({"matches": len(payload["matches"])}, indent=2))
