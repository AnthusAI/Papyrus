#!/usr/bin/env bash
# Build the knowledge-run image for arm64 and push it to the job stack's ECR repository (created by the CDK stack).
# Usage: AWS_PROFILE=papyrus-production infra/knowledge-run/build_image.sh   (asserts the account first)
# Prints the pushed image tag; pass it to `cdk deploy -c imageTag=<tag>`.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGION="${AWS_REGION:-us-east-1}"
EXPECTED_ACCOUNT="712236451410"
REPOSITORY="${KNOWLEDGE_RUN_REPOSITORY:-papyrus-scheduled-jobs/knowledge-run}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[ "$ACCOUNT_ID" = "$EXPECTED_ACCOUNT" ] || { echo "wrong account $ACCOUNT_ID (expected $EXPECTED_ACCOUNT)" >&2; exit 1; }
[ -z "$(git -C "$ROOT_DIR" status --porcelain -- infra/knowledge-run)" ] || { echo "commit your changes first: the tag is the git sha" >&2; exit 1; }
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
TAG="${IMAGE_TAG:-$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)}"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
PROVENANCE_FLAG=()
docker buildx build --help 2>/dev/null | grep -q -- "--provenance" && PROVENANCE_FLAG=(--provenance=false)
docker buildx build --platform linux/arm64 "${PROVENANCE_FLAG[@]}" \
  -f "$ROOT_DIR/infra/knowledge-run/Dockerfile" -t "$REGISTRY/$REPOSITORY:$TAG" ${PAPYRUS_VERSION:+--build-arg PAPYRUS_VERSION=$PAPYRUS_VERSION} --push "$ROOT_DIR" >&2
echo "$TAG"
