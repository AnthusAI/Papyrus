#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKETING_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STACK_NAME="${PAPYRUS_MARKETING_STACK:-PapyrusMarketingSite}"
AWS_REGION="${PAPYRUS_MARKETING_REGION:-us-east-1}"

cd "${MARKETING_DIR}"
npm ci
npm run build

aws cloudformation deploy \
  --region "${AWS_REGION}" \
  --stack-name "${STACK_NAME}" \
  --template-file infra/cloudformation.yml \
  --no-fail-on-empty-changeset

BUCKET_NAME="$(aws cloudformation describe-stacks --region "${AWS_REGION}" --stack-name "${STACK_NAME}" --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)"
DISTRIBUTION_ID="$(aws cloudformation describe-stacks --region "${AWS_REGION}" --stack-name "${STACK_NAME}" --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text)"

aws s3 sync out "s3://${BUCKET_NAME}" --delete --cache-control "public,max-age=31536000,immutable"
aws s3 cp out/index.html "s3://${BUCKET_NAME}/index.html" --content-type "text/html" --cache-control "no-cache"
aws s3 cp out/404.html "s3://${BUCKET_NAME}/404.html" --content-type "text/html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "${DISTRIBUTION_ID}" --paths "/*"

echo "Deployed https://papyrus.anth.us"
