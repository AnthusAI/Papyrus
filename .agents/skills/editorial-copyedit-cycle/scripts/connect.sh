#!/usr/bin/env bash
# Connect the papyrus CLI to one site's deployed newsroom backend (IAM operator lane).
#   connect.sh <workdir> <amplify-app-id> [papyrus-version]
# Creates <workdir>/pv (venv with papyrus-newsroom[markus], humanus[jev], boto3)
# and <workdir>/site/amplify_outputs.json built from the deployed main-branch backend stack.
set -euo pipefail
WORK=${1:?workdir}; APP=${2:?amplify app id}; VER=${3:-}
: "${AWS_PROFILE:=papyrus-production}"; export AWS_PROFILE
REGION=${AWS_REGION:-us-east-1}
mkdir -p "$WORK/site"
if [ ! -x "$WORK/pv/bin/papyrus" ]; then
  python3 -m venv "$WORK/pv"
  "$WORK/pv/bin/pip" install -q "papyrus-newsroom[markus]${VER:+==$VER}" "humanus[jev]" boto3
fi
STACK=$(aws amplify get-branch --app-id "$APP" --branch-name main --region "$REGION" \
  --query 'branch.backend.stackArn' --output text | cut -d/ -f2)
aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].Outputs' > "$WORK/site/outputs.json"
python3 - "$WORK/site" <<'EOF'
import json, sys
d = sys.argv[1]
o = {x["OutputKey"]: x["OutputValue"] for x in json.load(open(f"{d}/outputs.json"))}
custom = json.loads(o["customOutputs"]); custom = custom.get("custom", custom)
json.dump({"version": "1.4",
           "data": {"url": o["awsAppsyncApiEndpoint"], "aws_region": o["awsAppsyncRegion"],
                    "default_authorization_type": o["awsAppsyncAuthenticationType"]},
           "custom": custom}, open(f"{d}/amplify_outputs.json", "w"), indent=1)
print("endpoint", o["awsAppsyncApiEndpoint"]); print("publication", custom.get("publication"))
EOF
echo "export PAPYRUS_SITE_ROOT=$WORK/site PAPYRUS_GRAPHQL_AUTH=iam AWS_PROFILE=$AWS_PROFILE AWS_REGION=$REGION"
