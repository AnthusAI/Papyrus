#!/usr/bin/env bash
# Verify (and optionally re-run find/process) for an archived inbound-email submission.
#
# Examples:
#   AWS_PROFILE=Ryan ./scripts/verify-archived-email-submission.sh \
#     --archive-key 07an4t5f11qb4pd82kv15dv5kh2ufqfnt9vepkg1
#
#   AWS_PROFILE=Ryan ./scripts/verify-archived-email-submission.sh \
#     --message-id message-email-submission-40ca4b073ca02d75f724 --rerun
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${AWS_PROFILE:-Ryan}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="${PAPYRUS_MEDIA_BUCKET_NAME:-amplify-dbsyytcm9drqa-mai-papyrusmediabucket0dab24-4hstaautjdqo}"
GRAPHQL="${PAPYRUS_GRAPHQL_ENDPOINT:-https://64hviw44q5cq5nwjcigmasowlq.appsync-api.us-east-1.amazonaws.com/graphql}"
CORPUS_KEY="${PAPYRUS_INBOUND_EMAIL_CORPUS_KEY:-AI-ML-research}"
RERUN=0
ARCHIVE_KEY=""
MESSAGE_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive-key) ARCHIVE_KEY="${2:-}"; shift 2 ;;
    --message-id) MESSAGE_ID="${2:-}"; shift 2 ;;
    --rerun) RERUN=1; shift ;;
    --bucket) BUCKET="${2:-}"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$MESSAGE_ID" && -z "$ARCHIVE_KEY" ]]; then
  echo "Provide --archive-key <ses-object-id> or --message-id <message-email-submission-...>" >&2
  exit 1
fi

export AWS_PROFILE="$PROFILE" AWS_REGION="$REGION"
export PAPYRUS_MEDIA_BUCKET_NAME="$BUCKET"
export PAPYRUS_GRAPHQL_ENDPOINT="$GRAPHQL"
export PAPYRUS_GRAPHQL_AUTH=iam   # break-glass: AWS credentials on purpose (PPY-5f119a)

ARGS=()
[[ -n "$ARCHIVE_KEY" ]] && ARGS+=(--archive-key "$ARCHIVE_KEY")
[[ -n "$MESSAGE_ID" ]] && ARGS+=(--message-id "$MESSAGE_ID")
[[ "$RERUN" -eq 1 ]] && ARGS+=(--rerun)

poetry run python3 scripts/verify_archived_email_submission.py "${ARGS[@]}"
