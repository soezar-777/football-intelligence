#!/usr/bin/env python3
"""Fetch LAST season's (2025/26) finished matches as a strength-training seed.

Why: early in a season every team has only a handful of current-season
matches (the Champions League has 2 per team), so raw strengths are mostly
noise. Last season's results, fed through the same recency weighting in
poisson.build_team_stats, decay to ~0.14x at 170 days and act as a gentle,
honest prior instead of an invented one.

Sources (both free, no key):
  * football-data.co.uk CSVs for the domestic leagues.
  * ESPN's public scoreboard archive for the Champions League.

Safety rule: a seed match is kept ONLY when BOTH team names map
confidently onto the current competition registry (real team ids from
data/matches_<CODE>.json). Anything ambiguous or unknown is dropped and
reported, never guessed.

Output: data/seed_<CODE>.json in the same match shape predict.py consumes.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

SEASON_CSV = "2526"  # football-data.co.uk season code for 2025/26

CSV_COMPS = {  # our code -> football-data.co.uk division code
    "PL": "E0", "ELC": "E1", "BL1": "D1", "BL2": "D2", "PD": "SP1",
    "SDV": "SP2", "SA": "I1", "FL1": "F1", "DED": "N1", "PPL": "P1",
}

ESPN_COMPS = {"CL": "uefa.champions"}

DROP_TOKENS = {
    "fc", "afc", "cf", "sc", "ac", "as", "ss", "us", "cd", "sd", "rc", "rcd",
    "club", "de", "del", "la", "el", "los", "las", "le", "les", "the", "e",
    "futbol", "calcio", "1901", "1903", "1904", "1907", "1910", "1899",
    "1846", "1900", "04", "05", "07", "09", "29", "65", "96", "1", "sv",
    "bsc", "vfl", "vfb", "fsv", "tsg", "ud", "bsc",
    # Generic club suffixes that differ between providers
    # (e.g. KickoffAPI "Sabah FA" vs football-data.org "Sabah FK").
    "fk", "fa",
}

# normalised source name -> exact canonical name in the current registry.
# Filled from the unmatched reports; every entry verified against output.
ALIASES: dict[str, dict[str, str]] = {
    "PL": {
        "man city": "Manchester City FC",
        "man united": "Manchester United FC",
        "nott m forest": "Nottingham Forest FC",
        "wolves": "Wolverhampton Wanderers FC",
    },
    "ELC": {
        "qpr": "Queens Park Rangers FC",
        "west brom": "West Bromwich Albion FC",
    },
    "BL1": {
        "bayern munich": "FC Bayern München",
        "ein frankfurt": "Eintracht Frankfurt",
        "hamburg": "Hamburger SV",
        "m gladbach": "Borussia Mönchengladbach",
    },
    "BL2": {
        "hertha berlin": "Hertha BSC",
        "karlsruhe": "Karlsruher SC",
    },
    "SA": {"inter": "FC Internazionale Milano"},
    "FL1": {
        "paris sg": "Paris Saint-Germain FC",
        "rennes": "Stade Rennais FC 1901",
        "brest": "Stade Brestois 29",
    },
    "DED": {"nijmegen": "NEC"},
    "PPL": {
        "sp lisbon": "Sporting Clube de Portugal",
        "guimaraes": "Vitória SC",
    },
    "PD": {
        "espanol": "RCD Espanyol de Barcelona",
        "ath bilbao": "Athletic Club",
        "ath madrid": "Club Atlético de Madrid",
    },
    "SDV": {"sp gijon": "Sporting Gijón"},
    "CL": {
        "bayern munich": "FC Bayern München",
        "bodo glimt": "FK Bodø/Glimt",
        "sporting cp": "Sporting Clube de Portugal",
    },
}

# Sister-division CSV used to seed promoted/relegated teams: a team that
# changed division still played last season — just in the other file.
# Both-teams-must-map still applies, so this yields the mutual matches
# among the promoted/relegated group (a small but real prior).
BRIDGE_CSV = {
    "PL": "E1", "ELC": "E0", "BL1": "D2", "BL2": "D1",
    "PD": "SP2", "SDV": "SP1",
}


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in DROP_TOKENS]
    return " ".join(toks)


def _registry(code: str) -> dict[str, tuple[int, str]]:
    """normalised name -> (team id, canonical name) from current data."""
    path = config.DATA_DIR / f"matches_{code}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    reg: dict[str, tuple[int, str]] = {}
    for m in payload.get("matches", []):
        for side in ("homeTeam", "awayTeam"):
            t = m.get(side) or {}
            if t.get("id") is not None and t.get("name"):
                reg[_norm(t["name"])] = (int(t["id"]), t["name"])
    return reg


def _map_team(raw: str, reg: dict[str, tuple[int, str]],
              aliases: dict[str, str]) -> tuple[int, str] | None:
    n = _norm(raw)
    if n in reg:
        return reg[n]
    if n in aliases:
        target = aliases[n]
        for k, v in reg.items():
            if v[1] == target:
                return v
        return None
    toks = set(n.split())
    if not toks:
        return None
    hits = [v for k, v in reg.items()
            if toks <= set(k.split()) or set(k.split()) <= toks]
    if len(hits) == 1:
        return hits[0]
    return None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_csv_comp(code: str, div: str, reg, aliases) -> tuple[list, list]:
    url = f"https://www.football-data.co.uk/mmz4281/{SEASON_CSV}/{div}.csv"
    text = _get(url).decode("utf-8-sig", errors="replace")
    out, unmatched = [], []
    seq = 0
    for row in csv.DictReader(io.StringIO(text)):
        try:
            hg = int(float(row["FTHG"])); ag = int(float(row["FTAG"]))
        except (KeyError, TypeError, ValueError):
            continue
        home = _map_team(row.get("HomeTeam", ""), reg, aliases)
        away = _map_team(row.get("AwayTeam", ""), reg, aliases)
        if not home or not away:
            if not home:
                unmatched.append(row.get("HomeTeam", ""))
            if not away:
                unmatched.append(row.get("AwayTeam", ""))
            continue
        dstr = (row.get("Date") or "").strip()
        dt = None
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                from datetime import datetime
                dt = datetime.strptime(dstr, fmt).date()
                break
            except ValueError:
                continue
        if dt is None:
            continue
        seq += 1
        out.append({
            "id": -(1_000_000 + seq),
            "utcDate": f"{dt.isoformat()}T12:00:00Z",
            "status": "FINISHED",
            "homeTeam": {"id": home[0], "name": home[1]},
            "awayTeam": {"id": away[0], "name": away[1]},
            "score": {"fullTime": {"home": hg, "away": ag}},
        })
    return out, unmatched


def fetch_espn_comp(code: str, slug: str, reg, aliases) -> tuple[list, list]:
    # ESPN rejects month-range queries (HTTP 400); single-date scoreboard
    # calls work. UCL plays Tue/Wed/Thu, plus the Saturday final.
    import time
    out, unmatched, seen = [], [], set()
    seq = 0
    days = []
    d = date(2025, 9, 1)
    while d <= date(2026, 5, 31):
        if d.weekday() in (1, 2, 3) or d == date(2026, 5, 30):
            days.append(d)
        d += timedelta(days=1)
    for day in days:
        url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
               f"{slug}/scoreboard?dates={day:%Y%m%d}")
        try:
            data = json.loads(_get(url))
        except Exception as e:  # noqa: BLE001
            print(f"[seed] {code}: ESPN {day} failed: {e}", flush=True)
            continue
        time.sleep(0.12)
        for ev in data.get("events", []):
            if ev.get("id") in seen:
                continue
            seen.add(ev.get("id"))
            comp = (ev.get("competitions") or [{}])[0]
            st = ((ev.get("status") or {}).get("type") or {}).get("state")
            if st != "post":
                continue
            teams = {}
            for c in comp.get("competitors", []):
                nm = ((c.get("team") or {}).get("displayName")
                      or (c.get("team") or {}).get("name") or "")
                try:
                    sc = int(float(c.get("score")))
                except (TypeError, ValueError):
                    sc = None
                teams[c.get("homeAway")] = (nm, sc)
            if "home" not in teams or "away" not in teams:
                continue
            (hn, hs), (an, as_) = teams["home"], teams["away"]
            if hs is None or as_ is None:
                continue
            home = _map_team(hn, reg, aliases)
            away = _map_team(an, reg, aliases)
            if not home or not away:
                if not home:
                    unmatched.append(hn)
                if not away:
                    unmatched.append(an)
                continue
            seq += 1
            out.append({
                "id": -(2_000_000 + seq),
                "utcDate": (ev.get("date") or "")[:19] + "Z",
                "status": "FINISHED",
                "homeTeam": {"id": home[0], "name": home[1]},
                "awayTeam": {"id": away[0], "name": away[1]},
                "score": {"fullTime": {"home": hs, "away": as_}},
            })
    return out, unmatched


def main() -> int:
    only = sys.argv[1:] or None
    for code, div in CSV_COMPS.items():
        if only and code not in only:
            continue
        reg = _registry(code)
        matches, unmatched = fetch_csv_comp(code, div, reg,
                                            ALIASES.get(code, {}))
        bridge = BRIDGE_CSV.get(code)
        if bridge:
            extra, _ = fetch_csv_comp(code, bridge, reg,
                                      ALIASES.get(code, {}))
            known = {(m["utcDate"][:10], m["homeTeam"]["id"],
                      m["awayTeam"]["id"]) for m in matches}
            extra = [m for m in extra
                     if (m["utcDate"][:10], m["homeTeam"]["id"],
                         m["awayTeam"]["id"]) not in known]
            if extra:
                for i, m in enumerate(extra):
                    m["id"] = -(3_000_000 + i)
                print(f"[seed] {code}: +{len(extra)} bridge matches "
                      f"from {bridge}", flush=True)
                matches = matches + extra
        _write(code, matches, unmatched)
    for code, slug in ESPN_COMPS.items():
        if only and code not in only:
            continue
        reg = _registry(code)
        matches, unmatched = fetch_espn_comp(code, slug, reg,
                                             ALIASES.get(code, {}))
        _write(code, matches, unmatched)
    return 0


def _write(code: str, matches: list, unmatched: list) -> None:
    path = config.DATA_DIR / f"seed_{code}.json"
    path.write_text(json.dumps({"matches": matches}, ensure_ascii=False),
                    encoding="utf-8")
    teams = {m["homeTeam"]["id"] for m in matches} | \
            {m["awayTeam"]["id"] for m in matches}
    print(f"[seed] {code}: wrote {len(matches)} matches covering "
          f"{len(teams)} teams -> {path.name}", flush=True)
    if unmatched:
        from collections import Counter
        top = Counter(unmatched).most_common(12)
        print(f"[seed] {code}: UNMATCHED (dropped): {top}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
