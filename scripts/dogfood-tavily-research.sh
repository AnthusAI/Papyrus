#!/usr/bin/env bash
# Dogfood Tavily web search: create assignment → harness research → persist packet → register proposals.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TITLE="${1:-Tavily dogfood research}"
QUERY="${2:-$TITLE}"
CORPUS_KEY="${CORPUS_KEY:-AI-ML-research}"

if [[ -z "${TAVILY_API_KEY:-}" && -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${TAVILY_API_KEY:-}" ]]; then
  echo "TAVILY_API_KEY is required (set in .env or environment)." >&2
  exit 1
fi

echo "Creating research assignment: ${TITLE}"
CREATE_OUT="$(poetry run papyrus assignments create-research \
  --title "$TITLE" \
  --corpus-key "$CORPUS_KEY" \
  --research-mode source_discovery \
  --research-questions "$QUERY")"
echo "$CREATE_OUT"
ASSIGNMENT_ID="$(echo "$CREATE_OUT" | awk -F'\t' '$2=="create-research" && $3=="assignment" {print $4; exit}')"
if [[ -z "$ASSIGNMENT_ID" ]]; then
  echo "Could not parse assignment id from create-research output." >&2
  exit 1
fi

PACKET_JSON="$(mktemp -t papyrus-research-packet.XXXXXX.json)"
SNIPPET_FILE="$(mktemp -t papyrus-research-snippet.XXXXXX.tac)"
trap 'rm -f "$PACKET_JSON" "$SNIPPET_FILE"' EXIT

cat >"$SNIPPET_FILE" <<TAC
local search = web_search("${QUERY//\"/\\\"}")
return finish_research_from_search(search, {
  research_mode = "source_discovery",
  recommended_angle = "Editorial source discovery for: ${TITLE//\"/\\\"}",
})
TAC

echo "Running Tavily research harness for: ${QUERY}"
HARNESS_JSON="$(mktemp -t papyrus-harness.XXXXXX.json)"
trap 'rm -f "$PACKET_JSON" "$SNIPPET_FILE" "$HARNESS_JSON"' EXIT
poetry run papyrus procedures execute-tactus \
  --harness research \
  --assignment-id "$ASSIGNMENT_ID" \
  --corpus-key "$CORPUS_KEY" \
  --research-mode source_discovery \
  --file "$SNIPPET_FILE" >"$HARNESS_JSON"

poetry run python -c "
import json, sys
data = json.load(open('$HARNESS_JSON'))
if not data.get('ok'):
    print(json.dumps(data.get('error'), indent=2), file=sys.stderr)
    sys.exit(1)
packet = data['value'].get('research_packet') or data['value']
json.dump(packet, open('$PACKET_JSON', 'w'), indent=2)
trace = packet.get('researchTrace') or {}
print('proposals', len(packet.get('proposed_references') or []))
print('webSearches', trace.get('webSearches'))
"

echo "Persisting research packet..."
poetry run papyrus assignments apply-research-packet \
  --assignment "$ASSIGNMENT_ID" \
  --research-json "$PACKET_JSON"

echo "Registering proposals..."
poetry run papyrus assignments process-proposals \
  --assignment "$ASSIGNMENT_ID" \
  --config corpora/papyrus-steering.yml \
  --corpus-key "$CORPUS_KEY" \
  --status pending \
  --url-text false \
  --metadata-from-text false \
  --json

echo ""
echo "Done. Assignment: ${ASSIGNMENT_ID}"
