#!/usr/bin/env python3
"""Fetch Premier League injury data from premierinjuries.com.

Display-only feature (Path 1, approved by the user 2026-10-20): the app shows
"Ruled out: X, Y" under PL fixtures. This NEVER feeds the prediction model --
predict.py only annotates predictions_PL.json with the lists.

Source page: https://www.premierinjuries.com/injury-table.php
Markup (verified 2026-10-20):
  team heading: <tr class="heading" data-team-id="N"> ...
                  <div class="injury-team">Arsenal</div>
  player row:   <tr class="player-row team_N"> with mob-title cells
                  Player / Reason / Further Detail / Potential Return /
                  Condition / Status
Only players whose Status is exactly "Ruled Out" are published. Players with
a percentage chance (25/50/75%) are doubtful, NOT ruled out, and must never
be labelled as such.

Writes data/injuries_PL.json:
  {"generated_at": iso, "source": "premierinjuries.com",
   "teams": {"Arsenal": ["William Saliba", ...], ...}}

Exit codes: 0 = ok, 2 = scrape failed (run_daily tolerates 2; predict.py
then simply attaches no flags).
"""

import html as html_lib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://www.premierinjuries.com/injury-table.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "injuries_PL.json"

_HEADING_RE = re.compile(
    r'<tr class="heading" data-team-id="(\d+)">(.*?)</tr>', re.S)
_TEAM_NAME_RE = re.compile(r'<div class="injury-team">([^<]+)</div>')
_ROW_RE = re.compile(r'<tr class="player-row team_(\d+)">(.*?)</tr>', re.S)


def _cell(block: str, title: str) -> str:
    m = re.search(
        r'<div class="mob-title">' + re.escape(title) + r'</div>(.*?)</td>',
        block, re.S)
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", "", m.group(1))
    return html_lib.unescape(text).strip()


def parse_injury_table(page: str) -> dict[str, list[str]]:
    """Return {team_name: [ruled-out player names]} from the table HTML."""
    team_names: dict[str, str] = {}
    for tid, block in _HEADING_RE.findall(page):
        m = _TEAM_NAME_RE.search(block)
        if m:
            team_names[tid] = html_lib.unescape(m.group(1)).strip()
    teams: dict[str, list[str]] = {}
    for tid, block in _ROW_RE.findall(page):
        if _cell(block, "Status") != "Ruled Out":
            continue
        player = _cell(block, "Player")
        team = team_names.get(tid)
        if player and team:
            teams.setdefault(team, []).append(player)
    for team in teams:
        teams[team] = sorted(set(teams[team]))
    return teams


def fetch_and_save() -> bool:
    """Fetch the injury table and write injuries_PL.json. True on success."""
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = resp.read().decode("utf-8", errors="replace")
        teams = parse_injury_table(page)
        if not teams:
            print("[injuries] parsed 0 teams -- page layout changed?",
                  flush=True)
            return False
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "premierinjuries.com",
            "teams": teams,
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        n = sum(len(v) for v in teams.values())
        print(f"[injuries] wrote {OUT_PATH.name}: {n} ruled-out players "
              f"across {len(teams)} teams", flush=True)
        return True
    except Exception as exc:  # network/parse failure must never kill the run
        print(f"[injuries] fetch failed: {exc}", flush=True)
        return False


def main() -> int:
    return 0 if fetch_and_save() else 2


if __name__ == "__main__":
    sys.exit(main())
