#!/usr/bin/env python3
"""Daily orchestrator: fetch -> predict -> verify -> performance.

Run locally:
    python3 backend/run_daily.py [--competitions PL,BL1]

In CI the FOOTBALL_DATA_API_KEY secret provides the API key.
Each stage logs clearly; a stage failure stops the pipeline.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent


def run_step(name: str, script: str, extra: list[str]) -> None:
    print(f"\n===== {name} =====", flush=True)
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(BACKEND_DIR / script), *extra],
        cwd=BACKEND_DIR,
        capture_output=False,
    )
    elapsed = time.time() - started
    if proc.returncode not in (0, 2):  # 2 = fetch finished with some comps failed
        if script == "fetch_data.py" and proc.returncode == 2:
            print(f"[{name}] completed with partial competition failures "
                  f"({elapsed:.0f}s)", flush=True)
            return
        raise SystemExit(f"[{name}] FAILED (exit {proc.returncode})")
    print(f"[{name}] ok in {elapsed:.0f}s", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FOOTBALL INTELLIGENCE daily run")
    ap.add_argument("--competitions", default=None,
                    help="comma-separated codes (default: all)")
    args = ap.parse_args(argv)

    comp_args = ["--competitions", args.competitions] if args.competitions else []

    print("FOOTBALL INTELLIGENCE -- daily run starting", flush=True)
    run_step("fetch", "fetch_data.py", comp_args)
    run_step("injuries", "fetch_injuries.py", [])
    run_step("predict", "predict.py", comp_args)
    run_step("verify", "verify.py", [])
    run_step("performance", "performance.py", [])
    print("\nFOOTBALL INTELLIGENCE -- daily run complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
