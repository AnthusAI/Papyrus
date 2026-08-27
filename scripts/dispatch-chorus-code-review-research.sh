#!/usr/bin/env bash
# Register chorus.codes, then start two Tavily deep research assignments:
# 1) open-source tools like Chorus; 2) academic literature on the topic.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CORPUS_KEY="${CORPUS_KEY:-AI-ML-research}"
STEERING_CONFIG="${STEERING_CONFIG:-corpora/papyrus-steering.yml}"
TOOLS_SECTION="${TOOLS_SECTION:-technology}"
ACADEMIC_SECTION="${ACADEMIC_SECTION:-science}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${RUN_DIR:-$ROOT/.papyrus-runs/chorus-code-review-$RUN_ID}"
CHORUS_URL="${CHORUS_URL:-https://chorus.codes}"

PAPYRUS_CMD=(env PYTHONPATH=src python3 -m papyrus.cli)

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ensure_authoring_env() {
  export PAPYRUS_GRAPHQL_ENDPOINT="${PAPYRUS_GRAPHQL_ENDPOINT:-https://64hviw44q5cq5nwjcigmasowlq.appsync-api.us-east-1.amazonaws.com/graphql}"
  if [[ -n "${PAPYRUS_GRAPHQL_JWT:-}" ]]; then
    return 0
  fi
  local refresh_args=(auth refresh-jwt)
  if [[ -n "${PAPYRUS_JWT_SECRET:-}" ]]; then
    refresh_args+=(--secret-env PAPYRUS_JWT_SECRET --no-discover-ssm-param)
  elif [[ -n "${PAPYRUS_SANDBOX_JWT_SECRET:-}" ]]; then
    refresh_args+=(--secret-env PAPYRUS_SANDBOX_JWT_SECRET --no-discover-ssm-param)
  elif [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
    export AWS_REGION="${AWS_REGION:-us-east-1}"
    refresh_args+=(
      --ssm-param
      "${PAPYRUS_JWT_SECRET_SSM_PARAM:-/amplify/dbsyytcm9drqa/main-branch-cb38ada667/PAPYRUS_JWT_SECRET}"
    )
  else
    echo "Missing production authoring credentials." >&2
    echo "Set PAPYRUS_GRAPHQL_JWT, or PAPYRUS_JWT_SECRET, or AWS credentials for SSM JWT minting." >&2
    exit 1
  fi
  export PAPYRUS_GRAPHQL_JWT="$("${PAPYRUS_CMD[@]}" "${refresh_args[@]}")"
}

require_tavily() {
  if [[ -z "${TAVILY_API_KEY:-}" ]]; then
    echo "TAVILY_API_KEY is required for research.tavily-deep assignments." >&2
    exit 1
  fi
}

parse_assignment_id() {
  local output="$1"
  echo "$output" | awk -F'\t' '$2=="create-research" && $3=="assignment" {print $4; exit}'
}

register_chorus_reference() {
  mkdir -p "$RUN_DIR"
  local sources="$RUN_DIR/chorus-source.txt"
  local catalog="$RUN_DIR/chorus-catalog.json"
  local prepared="$RUN_DIR/chorus-prepared-catalog.json"
  printf '%s\n' "$CHORUS_URL Chorus — multi-model local-first code review CLI (Apache 2.0)" >"$sources"

  "${PAPYRUS_CMD[@]}" references make-catalog --input "$sources" --output "$catalog"
  "${PAPYRUS_CMD[@]}" references prepare-catalog \
    --config "$STEERING_CONFIG" \
    --corpus-key "$CORPUS_KEY" \
    --catalog "$catalog" \
    --output "$prepared"

  local rationale
  rationale="$(cat <<EOF
Chorus (${CHORUS_URL}) is an Apache 2.0 open-source, local-first CLI that orchestrates parallel multi-model code review across Claude, Codex, Gemini, Kimi, OpenCode, and related tools via MCP. It implements cross-lineage review, threshold quorum, and info-asymmetric red-green patterns. Register as anchor material for surveying custom and multi-agent code review tooling.
EOF
)"

  "${PAPYRUS_CMD[@]}" references create-from-catalog \
    --config "$STEERING_CONFIG" \
    --corpus-key "$CORPUS_KEY" \
    --catalog "$prepared" \
    --status pending \
    --ingestion-rationale "$rationale"
  echo "reference\tchorus\tregistered\t${CHORUS_URL}\tcatalog\t${prepared}"
}

create_and_run_tavily_assignment() {
  local title="$1"
  local summary="$2"
  local instructions="$3"
  local section="$4"
  local queue="$5"

  local create_out
  create_out="$("${PAPYRUS_CMD[@]}" assignments create-research \
    --type research.tavily-deep \
    --title "$title" \
    --summary "$summary" \
    --brief "$summary" \
    --instructions "$instructions" \
    --section "$section" \
    --corpus-key "$CORPUS_KEY" \
    --research-mode source_discovery \
    --priority 85 \
    --queue "$queue" \
    --actor-label "papyrus-automation-chorus-code-review" \
    --tavily-model auto)"

  echo "$create_out"
  local assignment_id
  assignment_id="$(parse_assignment_id "$create_out")"
  if [[ -z "$assignment_id" ]]; then
    echo "Could not parse assignment id from create-research output." >&2
    exit 1
  fi

  echo "assignment\tstart\t${assignment_id}\t${title}"
  "${PAPYRUS_CMD[@]}" assignments run-tavily-deep-research \
    --assignment "$assignment_id" \
    --corpus-key "$CORPUS_KEY" \
    --wait \
    --actor-label "papyrus-automation-chorus-code-review"
  echo "assignment\tcomplete\t${assignment_id}"
}

main() {
  local dry_run=false
  local skip_reference=false
  local skip_tools=false
  local skip_academic=false
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) dry_run=true ;;
      --skip-reference) skip_reference=true ;;
      --skip-tools) skip_tools=true ;;
      --skip-academic) skip_academic=true ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
  done

  if [[ "$dry_run" == true ]]; then
    echo "dry-run\tchorus-code-review\twould register ${CHORUS_URL} and start two research.tavily-deep assignments"
    exit 0
  fi

  ensure_authoring_env
  require_tavily

  echo "Preflight: ops content inspect"
  "${PAPYRUS_CMD[@]}" ops content inspect

  if [[ "$skip_reference" != true ]]; then
    echo "=== Registering Chorus reference ==="
    register_chorus_reference
  fi

  if [[ "$skip_tools" != true ]]; then
    echo "=== Tavily deep research: open-source code review tools ==="
    create_and_run_tavily_assignment \
      "Open-source multi-model code review tools (Chorus landscape)" \
      "Discover open-source and freely available custom code review orchestrators comparable to Chorus." \
      "$(cat <<'INSTRUCTIONS'
Use Tavily deep research to find open-source and freely available custom code review tools similar to Chorus (https://chorus.codes).

Prioritize:
- multi-model or multi-agent PR/code review orchestrators
- local-first review daemons or CLIs (not SaaS-only)
- MCP-based or editor-integrated review flows
- tools that aggregate several LLM reviewers with quorum/threshold patterns

Deprioritize generic static analyzers unless they explicitly orchestrate LLM-based review across models.

For each strong prospect in proposedReferences, include ingestion_rationale explaining similarity to Chorus and relevance to AI/ML engineering practice.
INSTRUCTIONS
)" \
      "$TOOLS_SECTION" \
      "research:technology:chorus-landscape"
  fi

  if [[ "$skip_academic" != true ]]; then
    echo "=== Tavily deep research: academic literature ==="
    create_and_run_tavily_assignment \
      "Academic research on multi-model and LLM code review" \
      "Find peer-reviewed and preprint research on automated, multi-agent, and LLM-assisted code review." \
      "$(cat <<'INSTRUCTIONS'
Use Tavily deep research to find academic research on multi-model, multi-agent, and LLM-assisted code review.

Prioritize:
- peer-reviewed papers and widely cited preprints
- empirical studies and benchmarks on automated program review
- surveys or systematic reviews of AI-assisted code inspection
- work on ensemble or cross-model review, human-AI collaboration in PR review, and evaluation methodology

Include both classical software-engineering venues and recent ML-for-code venues when relevant.

For each strong prospect in proposedReferences, include ingestion_rationale tied to methods/science desk coverage of AI engineering evaluation practice.
INSTRUCTIONS
)" \
      "$ACADEMIC_SECTION" \
      "research:science:chorus-academic"
  fi

  echo "Done. Run artifacts: ${RUN_DIR}"
}

main "$@"
