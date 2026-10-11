"""Central configuration for FOOTBALL INTELLIGENCE.

Security note: the football-data.org API key is NEVER stored in this repo.
It is loaded from the FOOTBALL_DATA_API_KEY environment variable first,
falling back (for local development only) to a 600-mode file outside the repo.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------- API ----
API_BASE = "https://api.football-data.org/v4"
API_KEY_ENV = "FOOTBALL_DATA_API_KEY"
# Local-dev fallback: a file readable only by the owner, OUTSIDE the repo.
LOCAL_KEY_FILE = Path("/home/hatch/.config/football-intelligence/api_key")

# ------------------------------------------------------- Competitions ----
# football-data.org v4 competition codes (all on the free tier).
COMPETITIONS = [
    "PL",   # Premier League (England)
    "BL1",  # Bundesliga (Germany)
    "SA",   # Serie A (Italy)
    "PD",   # Primera Division / La Liga (Spain)
    "FL1",  # Ligue 1 (France)
    "DED",  # Eredivisie (Netherlands)
    "PPL",  # Primeira Liga (Portugal)
    "CL",   # UEFA Champions League
    "ELC",  # Championship (England)
    "BSA",  # Campeonato Brasileiro Serie A (Brazil)
    "BL2",  # 2. Bundesliga (Germany) -- via OpenLigaDB (free, keyless)
]

# -------------------------------------------------------------- Paths ----
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"

# -------------------------------------------------------- Rate limits ----
# football-data.org free tier: 10 requests/minute.
# Keep a polite margin: at least 6.5 s between calls.
MIN_SECONDS_BETWEEN_CALLS = 6.5
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 60  # doubled on every 429 retry

# -------------------------------------------------------------- Model ----
MODEL_VERSION = "poisson-v1"

# A market pick is only published when its probability reaches this floor.
MIN_EDGE = {
    "1x2": 0.45,
    "ou25": 0.55,
    "btts": 0.55,
    "ah": 0.55,
    "correct_score": 0.12,
}

ASIAN_HANDICAP_LINES = (-1.5, -1.0, -0.5, 0.5, 1.0, 1.5)
OVER_UNDER_LINES = (1.5, 2.5, 3.5)


def load_api_key() -> str:
    """Return the API key from env, else the local 600-mode dev file.

    Raises RuntimeError if neither is available. Never logs the key.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key
    try:
        if LOCAL_KEY_FILE.exists():
            file_key = LOCAL_KEY_FILE.read_text(encoding="utf-8").strip()
            if file_key:
                return file_key
    except OSError:
        pass
    raise RuntimeError(
        f"API key not found. Set the {API_KEY_ENV} environment variable "
        f"or place the key in {LOCAL_KEY_FILE} (mode 600)."
    )
