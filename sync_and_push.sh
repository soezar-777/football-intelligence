#!/bin/bash
# FOOTBALL INTELLIGENCE — twice-daily sync: fetch -> predict -> verify -> performance,
# publish JSON to docs/data/, push to GitHub if changed.
set -euo pipefail

PROJ="/home/hatch/workspace/football-intelligence"
KEYFILE="/home/hatch/.config/football-intelligence/api_key"
STATE="/home/hatch/.config/football-intelligence/last_push.sha"

export FOOTBALL_DATA_API_KEY="$(cat "$KEYFILE")"
cd "$PROJ"

PY="$PROJ/.venv/bin/python3"
[ -x "$PY" ] || PY="python3"

echo "[sync] test gate: running pytest before the pipeline..."
if ! "$PY" -m pytest tests/ -q; then
  echo "[sync] ERROR: test suite FAILED -- aborting sync. Nothing was fetched, published or pushed. Fix the failing tests first." >&2
  exit 1
fi
echo "[sync] test gate passed."

echo "[sync] running daily pipeline..."
$PY backend/run_daily.py

# Frontend only needs these files.
PUBLISH_FILES="docs/data/verification.json docs/data/performance.json"
for f in data/predictions_*.json; do
  [ -f "$f" ] || continue
  code=$(basename "$f" .json | sed 's/^predictions_//')
  # skip unknown/empty competition splits
  [ "$code" != "UNK" ] || continue
  cp "$f" "docs/data/predictions_${code}.json"
  PUBLISH_FILES="$PUBLISH_FILES docs/data/predictions_${code}.json"
done
# League tables (published when the fetch succeeds; old files stay otherwise)
for f in data/standings_*.json; do
  [ -f "$f" ] || continue
  cp "$f" "docs/data/"
  PUBLISH_FILES="$PUBLISH_FILES docs/data/$(basename "$f")"
done
# verification + performance change rarely; always publish them too
cp data/verification.json docs/data/ 2>/dev/null || true
cp data/performance.json docs/data/ 2>/dev/null || true

NEWSHA=$(sha256sum $PUBLISH_FILES 2>/dev/null | sha256sum | cut -d' ' -f1 || echo "none")
if [ -f "$STATE" ] && [ "$(cat "$STATE")" = "$NEWSHA" ]; then
  echo "[sync] no changes since last push, skipping."
  exit 0
fi

# NOTE: pushing is done by the calling agent via direct tool calls (the
# GitHub push tooling rejects oversized single requests and nested
# subprocess calls wait on interactive approval). Print the manifest for it.
# DO NOT write $STATE here -- the caller moves $STATE.new into place only
# after every push succeeds, so a failed/skipped push is retried next run.
echo "[sync] changes detected. Files ready to push:"
for f in $PUBLISH_FILES; do
  echo "  $f ($(wc -c < "$f") bytes)"
done
echo "$NEWSHA" > "$STATE.new"
echo "[sync] new state sha: $NEWSHA"
echo "[sync] done (push pending; caller must: mv $STATE.new $STATE after pushing)."
