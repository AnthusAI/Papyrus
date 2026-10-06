#!/usr/bin/env bash
# Regenerate edition-forum messages for 2026-06-05 (trimmed bodies, three-post sequence).
# Requires AWS credentials for the papyrus-authoring role (set AWS_PROFILE)
set -euo pipefail
cd "$(dirname "$0")/.."

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

echo "Step 1/2: refresh theme message (soft-delete prior forum planning posts)..."
poetry run papyrus "${COMMON[@]}" --through plan --refresh-forum --json

echo "Step 2/2: optional desk + reporting candidates..."
poetry run papyrus "${COMMON[@]}" --through rotating-desk --allow-fallback --json

echo "Done. Check the edition_forum thread for three active messages."
