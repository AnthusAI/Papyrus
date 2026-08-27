#!/bin/bash
# Quick verification that the console chat IAM fix is deployed to production

set -euo pipefail

: "${AWS_PROFILE:=Ryan}"
: "${AWS_REGION:=us-east-1}"
export AWS_PROFILE AWS_REGION

FUNCTION_NAME="amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D"
FIX_COMMIT="0c39cbb"

echo "=== Production Console Chat Fix Verification ==="
echo

# 1. Verify fix is in code
echo "1. Checking code..."
if grep -q '"ssm:GetParameters"' amplify/functions/console-chat-responder/resource.ts; then
    echo "   ✓ IAM fix present in code (commit $FIX_COMMIT)"
else
    echo "   ✗ IAM fix NOT found in code"
    exit 1
fi

# 2. Check AWS access
echo "2. Checking AWS access..."
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "   ⚠ AWS credentials not configured"
    echo "   Set AWS_PROFILE=Ryan AWS_REGION=us-east-1 and retry"
    exit 1
fi
echo "   ✓ AWS access confirmed"

# 3. Check Lambda IAM role
echo "3. Checking Lambda IAM permissions..."
ROLE_ARN=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --query 'Role' --output text 2>/dev/null || echo "")

if [ -z "$ROLE_ARN" ]; then
    echo "   ✗ Could not retrieve Lambda function"
    exit 1
fi

ROLE_NAME=$(echo "$ROLE_ARN" | awk -F/ '{print $NF}')
HAS_GET_PARAMETERS=false

for POLICY in $(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames[]' --output text); do
    if aws iam get-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY" --output json | \
       jq -e '.PolicyDocument.Statement[] | select(.Action | contains(["ssm:GetParameters"]))' >/dev/null 2>&1; then
        HAS_GET_PARAMETERS=true
        break
    fi
done

if [ "$HAS_GET_PARAMETERS" = true ]; then
    echo "   ✓ Lambda has ssm:GetParameters permission"
else
    echo "   ✗ Lambda MISSING ssm:GetParameters permission - fix not deployed"
    exit 1
fi

# 4. Check for recent JWT errors
echo "4. Checking CloudWatch logs..."
ERRORS=$(aws logs filter-log-events \
    --log-group-name "/aws/lambda/$FUNCTION_NAME" \
    --start-time $(($(date +%s) - 3600))000 \
    --filter-pattern '"Could not resolve JWT signing secret"' \
    --query 'length(events)' --output text 2>/dev/null || echo "0")

if [ "$ERRORS" != "0" ]; then
    echo "   ✗ Found $ERRORS JWT errors in last hour - fix not working"
    exit 1
else
    echo "   ✓ No JWT errors in last hour"
fi

echo
echo "✓ All checks passed - console chat fix appears to be working"
echo
echo "Manual test: https://p.apyr.us/newsroom → console chat → 'list recent references'"
