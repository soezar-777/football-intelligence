#!/usr/bin/env python3
"""Fetch Spain's Segunda Division from API-Football (api-sports.io).

football-data.org's free tier does not include Segunda Division, so this
module fetches from https://v3.football.api-sports.io (free plan:
100 requests/day) and normalizes fixtures into the same shape as
football-data.org v4 match objects, so the rest of the pipeline (predict ->
verify -> performance) works unchanged.

Auth: API key in the `x-apisports-key` header. The key lives in
~/.config/football-intelligence/api_football_key (mode 600), never in the repo.

Match/team IDs are offset by APISPORTS_ID_OFFSET to avoid any collision with
football-data.org or OpenLigaDB IDs in the shared prediction history.

One request per sync covers the whole window (from/to params), so the free
plan's daily quota is more than enough for twice-daily runs.
"""

import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

APISPORTS_ID_OFFSET = 3_000_000
API_HOST = "v3.football.api-sports.io"
SEGUNDA_LEAGUE_ID = 141  # Spain - Segunda Division

KEY_PATH = Path.home() / ".config" / "football-intelligence" / "api_football_key"


def load_api_key() -> str | None:
    try:
        key = KEY_PATH.read_text(encoding="utf-8").strip()
        return key or None
    except OSError:
        return None


def _get(path: str, params: dict, api_key: str, retries: int = 4) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"https://{API_HOST}{path}?{query}"
    backoff = 10
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"x-apisports-key": api_key})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001 - retry on any fetch error
            print(f"[apisports] {path} failed (attempt {attempt}/{retries}): "
                  f"{exc}; retry in {backoff}s", flush=True)
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"[apisports] gave up on {path}")


def _status(short: str) -> str:
    """API-Football status short -> our status."""
    if short in ("FT", "AET", "PEN"):
        return "FINISHED"
    return "TIMED"


def normalize_fixture(f: dict) -> dict:
    fx = f.get("fixture") or {}
    teams = f.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = f.get("goals") or {}
    status = _status((fx.get("status") or {}).get("short") or "")
    finished = status == "FINISHED"
    return {
        "id": APISPORTS_ID_OFFSET + int(fx["id"]),
        "utcDate": fx.get("date"),
        "status": status,
        "homeTeam": {
            "id": APISPORTS_ID_OFFSET + int(home.get("id", 0)),
            "name": home.get("name") or "?",
            "shortName": "",
            "tla": "",
        },
        "awayTeam": {
            "id": APISPORTS_ID_OFFSET + int(away.get("id", 0)),
            "name": away.get("name") or "?",
            "shortName": "",
            "tla": "",
        },
        "score": {"fullTime": {
            "home": goals.get("home") if finished else None,
            "away": goals.get("away") if finished else None,
        }},
        "competition": {"code": "SDV", "name": "Segunda Division"},
    }


def current_season_year(today: datetime | None = None) -> int:
    today = today or datetime.now(timezone.utc)
    return today.year if today.month >= 7 else today.year - 1


def fetch_sdv_matches(api_key: str, days_back: int = 90,
                      days_ahead: int = 14) -> dict:
    today = datetime.now(timezone.utc).date()
    params = {
        "league": SEGUNDA_LEAGUE_ID,
        "season": current_season_year(),
        "from": (today - timedelta(days=days_back)).isoformat(),
        "to": (today + timedelta(days=days_ahead)).isoformat(),
        "timezone": "UTC",
    }
    payload = _get("/fixtures", params, api_key)
    if payload.get("errors"):
        raise RuntimeError(f"[apisports] API errors: {payload['errors']}")
    fixtures = payload.get("response") or []
    matches = [normalize_fixture(f) for f in fixtures]
    matches.sort(key=lambda m: m.get("utcDate") or "")
    finished = sum(1 for m in matches if m["status"] == "FINISHED")
    print(f"[apisports] SDV: {len(matches)} matches ({finished} finished) "
          f"[1 request]", flush=True)
    return {
        "competition": {"code": "SDV", "name": "Segunda Division"},
        "matches": matches,
    }


if __name__ == "__main__":
    key = load_api_key()
    if not key:
        print("no API key found at", KEY_PATH)
        raise SystemExit(1)
    payload = fetch_sdv_matches(key)
    print(json.dumps({"matches": len(payload["matches"])}, indent=2))
