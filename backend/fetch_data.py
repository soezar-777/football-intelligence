#!/usr/bin/env python3
"""Fetch fixtures, results and standings from football-data.org v4.

Polite free-tier client:
  * >= 6.5 s between requests (free tier = 10 req/min)
  * exponential backoff on HTTP 429 / 5xx
  * per-competition failures are logged and skipped, never fatal

Writes pretty JSON into data/:
  competitions.json, matches_<CODE>.json, standings_<CODE>.json

Only summary counts are printed -- never the API key or raw payloads.
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta

import requests

import config
import fetch_allsvenskan
import fetch_espn
import fetch_openliga

SESSION = requests.Session()
_last_call = 0.0

# Competitions fetched from OpenLigaDB (free, keyless) instead of
# football-data.org, which does not include them on the free tier.
OPENLIGA_CODES = {"BL2"}
# Segunda Division: ESPN public API (fixtures) + football-data.co.uk CSV
# (results). API-Football's free tier is season-capped (2022-2024), so it
# cannot serve the current season; fetch_apisports stays in the repo for
# potential future use.
# Allsvenskan: same pattern via fetch_allsvenskan (ESPN swe.1 + SWE.csv).
ESPN_CODES = {"SDV", "ALV"}


def _polite_wait() -> None:
    """Sleep so we never exceed the free-tier rate limit."""
    global _last_call
    wait = config.MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)


def api_get(path: str, params: dict | None = None) -> dict:
    """GET <API_BASE><path> with retries. Returns parsed JSON."""
    global _last_call
    url = config.API_BASE + path
    headers = {"X-Auth-Token": config.load_api_key()}
    backoff = config.RETRY_BACKOFF_SECONDS
    for attempt in range(1, config.MAX_RETRIES + 1):
        _polite_wait()
        try:
            resp = SESSION.get(url, headers=headers, params=params or {}, timeout=30)
        except requests.RequestException as exc:
            print(f"[fetch] network error on {path}: {exc}; retry in {backoff}s",
                  flush=True)
            time.sleep(backoff)
            backoff *= 2
            continue
        _last_call = time.monotonic()
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            print(f"[fetch] HTTP {resp.status_code} on {path} "
                  f"(attempt {attempt}/{config.MAX_RETRIES}); sleeping {backoff}s",
                  flush=True)
            time.sleep(backoff)
            backoff *= 2
            continue
        # 4xx other than 429: not retryable
        raise RuntimeError(f"[fetch] HTTP {resp.status_code} on {path}: "
                           f"{resp.text[:200]}")
    raise RuntimeError(f"[fetch] gave up on {path} after {config.MAX_RETRIES} attempts")


def save_json(name: str, obj: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DATA_DIR / name
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def fetch_competitions(wanted: list[str]) -> dict:
    payload = api_get("/competitions")
    comps = [c for c in payload.get("competitions", [])
             if c.get("code") in wanted]
    return {"fetched_at": date.today().isoformat(), "competitions": comps}


def fetch_matches(code: str, date_from: str, date_to: str) -> dict:
    payload = api_get(f"/competitions/{code}/matches",
                      {"dateFrom": date_from, "dateTo": date_to})
    return payload


def fetch_standings(code: str) -> dict:
    return api_get(f"/competitions/{code}/standings")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch football-data.org v4 data")
    ap.add_argument("--competitions", default=",".join(config.COMPETITIONS),
                    help="comma-separated competition codes")
    ap.add_argument("--days-back", type=int, default=90,
                    help="history window for finished matches")
    ap.add_argument("--days-ahead", type=int, default=14,
                    help="window for upcoming fixtures")
    args = ap.parse_args(argv)

    codes = [c.strip().upper() for c in args.competitions.split(",") if c.strip()]
    today = date.today()
    date_from = (today - timedelta(days=args.days_back)).isoformat()
    date_to = (today + timedelta(days=args.days_ahead)).isoformat()

    print(f"[fetch] competitions={','.join(codes)} window={date_from}..{date_to}",
          flush=True)

    try:
        comps = fetch_competitions(codes)
    except RuntimeError as exc:
        print(f"[fetch] ERROR: {exc}", flush=True)
        return 1
    # football-data.org doesn't list OpenLigaDB/API-Football-sourced competitions
    if "BL2" in codes and not any(c.get("code") == "BL2"
                                  for c in comps["competitions"]):
        comps["competitions"].append({"code": "BL2", "name": "2. Bundesliga",
                                      "source": "openligadb"})
    if "SDV" in codes and not any(c.get("code") == "SDV"
                                  for c in comps["competitions"]):
        comps["competitions"].append({"code": "SDV", "name": "Segunda Division",
                                      "source": "api-football"})
    if "ALV" in codes and not any(c.get("code") == "ALV"
                                  for c in comps["competitions"]):
        comps["competitions"].append({"code": "ALV", "name": "Allsvenskan",
                                      "source": "espn"})
    save_json("competitions.json", comps)
    print(f"[fetch] competitions.json: {len(comps['competitions'])} competitions",
          flush=True)

    ok, failed = 0, []
    for code in codes:
        try:
            if code in OPENLIGA_CODES:
                if code == "BL2":
                    matches = fetch_openliga.fetch_bl2_matches()
                else:
                    raise RuntimeError(f"[fetch] no OpenLigaDB handler for {code}")
                n = len(matches.get("matches", []))
                finished = sum(1 for m in matches.get("matches", [])
                               if m.get("status") == "FINISHED")
                save_json(f"matches_{code}.json", matches)
                print(f"[fetch] {code}: {n} matches ({finished} finished) "
                      f"[openliga]", flush=True)
                ok += 1
                continue
            if code in ESPN_CODES:
                if code == "SDV":
                    matches = fetch_espn.fetch_sdv_matches()
                elif code == "ALV":
                    matches = fetch_allsvenskan.fetch_alv_matches()
                else:
                    raise RuntimeError(f"[fetch] no ESPN handler for {code}")
                n = len(matches.get("matches", []))
                finished = sum(1 for m in matches.get("matches", [])
                               if m.get("status") == "FINISHED")
                save_json(f"matches_{code}.json", matches)
                print(f"[fetch] {code}: {n} matches ({finished} finished) "
                      f"[espn+csv]", flush=True)
                ok += 1
                continue
            matches = fetch_matches(code, date_from, date_to)
            n = len(matches.get("matches", []))
            finished = sum(1 for m in matches.get("matches", [])
                           if m.get("status") == "FINISHED")
            save_json(f"matches_{code}.json", matches)
            try:
                standings = fetch_standings(code)
                save_json(f"standings_{code}.json", standings)
            except RuntimeError as exc:
                print(f"[fetch] {code}: standings skipped ({exc})", flush=True)
            print(f"[fetch] {code}: {n} matches ({finished} finished)", flush=True)
            ok += 1
        except RuntimeError as exc:
            print(f"[fetch] {code}: FAILED ({exc})", flush=True)
            failed.append(code)

    print(f"[fetch] done: {ok} ok, {len(failed)} failed "
          f"{failed if failed else ''}", flush=True)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
