#!/usr/bin/env python3
"""Fetch 2. Bundesliga data from OpenLigaDB (free, no API key required).

football-data.org's free tier does not include BL2, so this module fetches
from https://api.openligadb.de and normalizes matches into the same shape as
football-data.org v4 match objects, so the rest of the pipeline (predict ->
verify -> performance) works unchanged.

Match IDs are offset by BL2_ID_OFFSET to avoid any collision with
football-data.org fixture IDs in the shared prediction history.
"""

import json
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BL2_ID_OFFSET = 2_000_000
BERLIN = ZoneInfo("Europe/Berlin")

BASE = "https://api.openligadb.de"


def _get(url: str, retries: int = 4) -> object:
    backoff = 10
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001 - retry on any fetch error
            print(f"[openliga] {url} failed (attempt {attempt}/{retries}): "
                  f"{exc}; retry in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"[openliga] gave up on {url}")


def _to_utc_iso(berlin_naive: str) -> str:
    """'2026-08-07T20:30:00' (Europe/Berlin wall time) -> UTC ISO string."""
    dt = datetime.fromisoformat(berlin_naive).replace(tzinfo=BERLIN)
    return dt.astimezone(timezone.utc).isoformat()


def _final_score(m: dict) -> tuple:
    """(home, away) from the Endergebnis result, or (None, None)."""
    for r in m.get("matchResults") or []:
        if r.get("resultTypeID") == 2:  # Endergebnis / final
            return r.get("pointsTeam1"), r.get("pointsTeam2")
    return None, None


def _norm_team(side: dict) -> dict:
    return {
        "id": side.get("teamId"),
        "name": side.get("teamName") or "?",
        "shortName": side.get("shortName") or "",
        "tla": "",
    }


def normalize_match(m: dict) -> dict:
    finished = bool(m.get("matchIsFinished"))
    hg, ag = _final_score(m) if finished else (None, None)
    return {
        "id": BL2_ID_OFFSET + int(m["matchID"]),
        "utcDate": _to_utc_iso(m["matchDateTime"]),
        "status": "FINISHED" if finished else "TIMED",
        "homeTeam": _norm_team(m.get("team1") or {}),
        "awayTeam": _norm_team(m.get("team2") or {}),
        "score": {"fullTime": {"home": hg, "away": ag}},
        "competition": {"code": "BL2", "name": "2. Bundesliga"},
    }


def current_season_year(today: datetime | None = None) -> int:
    """OpenLigaDB season key: the year the season starts (July cutoff)."""
    today = today or datetime.now(timezone.utc)
    return today.year if today.month >= 7 else today.year - 1


def fetch_bl2_matches(days_ahead: int = 14) -> dict:
    year = current_season_year()
    url = f"{BASE}/getmatchdata/bl2/{year}"
    raw = _get(url)
    matches = [normalize_match(m) for m in raw]
    # Keep full finished history for team-strength training, but only
    # near-term upcoming fixtures for predictions (mirrors the
    # football-data.org days-ahead window and keeps the published file small).
    horizon = datetime.now(timezone.utc).timestamp() + days_ahead * 86400
    kept = []
    for m in matches:
        if m["status"] == "FINISHED":
            kept.append(m)
            continue
        try:
            ko = datetime.fromisoformat(m["utcDate"]).timestamp()
        except (ValueError, TypeError):
            continue
        if ko <= horizon:
            kept.append(m)
    kept.sort(key=lambda m: m.get("utcDate") or "")
    finished = sum(1 for m in kept if m["status"] == "FINISHED")
    upcoming = len(kept) - finished
    print(f"[openliga] BL2 season {year}: {len(kept)} matches "
          f"({finished} finished, {upcoming} upcoming in {days_ahead}d) "
          f"[windowed]", flush=True)
    return {
        "competition": {"code": "BL2", "name": "2. Bundesliga"},
        "matches": kept,
    }


if __name__ == "__main__":
    payload = fetch_bl2_matches()
    print(json.dumps({"matches": len(payload["matches"])}, indent=2))
