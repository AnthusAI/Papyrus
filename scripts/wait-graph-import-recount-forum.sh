#!/usr/bin/env bash
# Wait for the in-flight graph import, then recount newsroom totals and refresh edition forum.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PAPYRUS="${PAPYRUS_ROOT:-$ROOT}"
PROD_ENV="${PAPYRUS_PRODUCTION_ENV:-$PAPYRUS/../Papyrus-production/.env}"
CONFIG="${PAPYRUS_STEERING_CONFIG:-$(dirname "$PROD_ENV")/corpora/papyrus-steering.yml}"
IMPORT_PID="${1:?usage: $0 <graph-import-pid>}"
LOG="/tmp/kb-graph-import.log"

echo "[watch] waiting for import pid=${IMPORT_PID}..."
while kill -0 "$IMPORT_PID" 2>/dev/null; do
  processed=$(grep -o 'processed=[0-9]*' "$LOG" 2>/dev/null | tail -1 | cut -d= -f2 || echo 0)
  echo "[watch] import still running processed=${processed:-0}/345152"
  sleep 300
done

echo "[watch] import process exited"
tail -5 "$LOG"

cd "$PAPYRUS"
set -a
# shellcheck disable=SC1090
source "$PROD_ENV"
set +a
export PAPYRUS_GRAPHQL_AUTH=iam   # break-glass: AWS credentials on purpose (PPY-5f119a)
unset VIRTUAL_ENV

echo "[watch] recounting newsroom summary for /newsroom tab counts..."
poetry run papyrus newsroom recount-summary 2>&1 | tee /tmp/kb-newsroom-recount.log

echo "[watch] refreshing edition forum 2026-06-05..."
COMMON=(
  assignments run-story-cycle
  --date 2026-06-05
  --topic "AI in video games"
  --category AI-ML-research
  --corpus-key AI-ML-research
  --coverage-key coverage.ai-in-video-games
  --sections culture,methods
  --section-budgets culture:2,methods:1
)
poetry run papyrus "${COMMON[@]}" --through plan --refresh-forum 2>&1 | tee /tmp/kb-forum-plan.log
poetry run papyrus "${COMMON[@]}" --through rotating-desk --allow-fallback 2>&1 | tee /tmp/kb-forum-desk.log

echo "[watch] DONE"
