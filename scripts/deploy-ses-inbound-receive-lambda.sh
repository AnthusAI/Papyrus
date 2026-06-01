#!/usr/bin/env bash
# Manually deploy papyrus-ses-inbound-receive with Amplify-compatible bundling (SSM env shims).
# Usage:
#   AWS_PROFILE=Ryan ./scripts/deploy-ses-inbound-receive-lambda.sh [function-name]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${AWS_PROFILE:-Ryan}"
REGION="${AWS_REGION:-us-east-1}"
FUNCTION_NAME="${1:-amplify-papyrus-ryan-sand-papyrussesinboundreceive-cBdcLglWpkys}"

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

BUILD_DIR="$BUILD_DIR" node <<'NODE'
const { readFileSync, writeFileSync } = require("node:fs");
const path = require("node:path");
const esbuild = require("esbuild");

const buildDir = process.env.BUILD_DIR;
if (!buildDir) throw new Error("BUILD_DIR is required");

const shimDir = path.join(
  process.cwd(),
  "node_modules",
  "@aws-amplify",
  "backend-function",
  "lib",
  "lambda-shims",
);
const ssmResolver = readFileSync(path.join(shimDir, "resolve_ssm_params.js"), "utf8");
const invokeSsm = readFileSync(path.join(shimDir, "invoke_ssm_shim.js"), "utf8");
const banner = [ssmResolver, invokeSsm]
  .join("")
  .split(/\r?\n/)
  .map((line) => line.replace(/\/\/.*$/, ""))
  .join("");

esbuild.buildSync({
  entryPoints: [path.join(process.cwd(), "amplify/functions/ses-inbound-receive/handler.ts")],
  outfile: path.join(buildDir, "index.js"),
  bundle: true,
  platform: "node",
  target: "node22",
  format: "esm",
  logLevel: "warning",
  banner: { js: banner },
  inject: [path.join(shimDir, "cjs_shim.js")],
});

writeFileSync(
  path.join(buildDir, "package.json"),
  JSON.stringify({ type: "module" }, null, 2),
);
NODE

(
  cd "$BUILD_DIR"
  zip -q function.zip index.js package.json
)

echo "Deploying to ${FUNCTION_NAME} (${PROFILE}, ${REGION})..."
aws --profile "$PROFILE" --region "$REGION" lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://${BUILD_DIR}/function.zip" >/dev/null

aws --profile "$PROFILE" --region "$REGION" lambda wait function-updated \
  --function-name "$FUNCTION_NAME"

echo "Deployed ${FUNCTION_NAME}"
