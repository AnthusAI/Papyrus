#!/usr/bin/env bash
# Builds the procedure runner image for arm64 Lambda and pushes it to ECR, creating the repository if needed.
# Usage: infra/procedures/build_image.sh  (AWS credentials for the target account in the environment)
# Prints the image URI (by digest) to pass as ImageUri to papyrus-procedure-runner.yaml.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGION="${AWS_REGION:-us-east-1}"
REPOSITORY="${PROCEDURE_RUNNER_REPOSITORY:-papyrus-procedure-runner}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
TAG="${IMAGE_TAG:-$(git -C "$ROOT_DIR" rev-parse --short HEAD)}"

aws ecr describe-repositories --region "$REGION" --repository-names "$REPOSITORY" >/dev/null 2>&1 \
  || aws ecr create-repository --region "$REGION" --repository-name "$REPOSITORY" \
       --image-scanning-configuration scanOnPush=true --image-tag-mutability IMMUTABLE >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null

docker buildx build --platform linux/arm64 --provenance=false \
  -f "$ROOT_DIR/infra/procedures/Dockerfile" -t "$REGISTRY/$REPOSITORY:$TAG" --push "$ROOT_DIR" >&2

DIGEST="$(aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY" --image-ids imageTag="$TAG" \
  --query 'imageDetails[0].imageDigest' --output text)"
echo "$REGISTRY/$REPOSITORY@$DIGEST"
