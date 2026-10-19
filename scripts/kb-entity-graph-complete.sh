#!/usr/bin/env bash
# Publish + import a Biblicus NER graph snapshot to production GraphQL, recount
# newsroom summary counts, and optionally refresh an edition forum kickoff.
#
# Usage:
#   ./scripts/kb-entity-graph-complete.sh \
#     --snapshot ner-entities:<snapshot_id> \
#     [--config /path/to/papyrus-steering.yml] \
#     [--import-run <existing-import-run>] \
#     [--edition-date 2026-06-05] \
#     [--skip-forum-refresh]
set -euo pipefail
cd "$(dirname "$0")/.."

PROD_ENV="${PAPYRUS_PRODUCTION_ENV:?set PAPYRUS_PRODUCTION_ENV to the production .env file}"
CONFIG="${PAPYRUS_STEERING_CONFIG:-$PROD_ENV/../corpora/papyrus-steering.yml}"
CORPUS_KEY="AI-ML-research"
SNAPSHOT=""
IMPORT_RUN=""
EDITION_DATE=""
SKIP_FORUM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --import-run) IMPORT_RUN="$2"; shift 2 ;;
    --edition-date) EDITION_DATE="$2"; shift 2 ;;
    --skip-forum-refresh) SKIP_FORUM=1; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$SNAPSHOT" && -z "$IMPORT_RUN" ]]; then
  echo "Provide --snapshot ner-entities:<id> or --import-run <id>." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$PROD_ENV"
set +a
export PAPYRUS_GRAPHQL_USE_IAM=1
unset VIRTUAL_ENV

if [[ -z "$IMPORT_RUN" ]]; then
  echo "Publishing graph snapshot $SNAPSHOT ..."
  PUBLISH_LOG="$(mktemp)"
  poetry run papyrus analysis publish-graph-snapshot \
    --corpus-key "$CORPUS_KEY" \
    --snapshot "$SNAPSHOT" \
    --config "$CONFIG" 2>&1 | tee "$PUBLISH_LOG"
  IMPORT_RUN="$(awk -F'\t' '/^analysis-publish\timport-run/{print $3}' "$PUBLISH_LOG" | tail -1)"
  rm -f "$PUBLISH_LOG"
  if [[ -z "$IMPORT_RUN" ]]; then
    echo "Could not parse import-run from publish output." >&2
    exit 1
  fi
fi

echo "Importing graph artifact $IMPORT_RUN (includes newsroom recount when import completes) ..."
poetry run papyrus analysis import-graph-artifact \
  --import-run "$IMPORT_RUN" \
  --config "$CONFIG"

echo "Recounting newsroom summary (authoritative totals for /newsroom tab counts) ..."
poetry run papyrus newsroom recount-summary

if [[ "$SKIP_FORUM" -eq 0 && -n "$EDITION_DATE" ]]; then
  echo "Refreshing edition forum kickoff for $EDITION_DATE ..."
  poetry run papyrus assignments run-story-cycle \
    --date "$EDITION_DATE" \
    --topic "AI in video games" \
    --category AI-ML-research \
    --corpus-key AI-ML-research \
    --coverage-key coverage.ai-in-video-games \
    --sections culture,methods \
    --section-budgets culture:2,methods:1 \
    --through plan \
    --refresh-forum
  poetry run papyrus assignments run-story-cycle \
    --date "$EDITION_DATE" \
    --topic "AI in video games" \
    --category AI-ML-research \
    --corpus-key AI-ML-research \
    --coverage-key coverage.ai-in-video-games \
    --sections culture,methods \
    --section-budgets culture:2,methods:1 \
    --through rotating-desk \
    --allow-fallback
fi

echo "Done."
