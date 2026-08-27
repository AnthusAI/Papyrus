#!/bin/bash
# Quick verification script for production console chat IAM fix
# Run this from ~/Projects/Papyrus-production or ~/Projects/Papyrus

set -euo pipefail

export AWS_PROFILE=Ryan
export AWS_REGION=us-east-1

echo "================================================"
echo "Quick Console Chat IAM Fix Verification"
echo "================================================"
echo ""

# 1. Check if fix commit is present
echo "1. Checking if fix commit is deployed..."
if git log --oneline -20 | grep -q "0c39cbb"; then
    echo "✅ Fix commit 0c39cbb is present on this branch"
else
    echo "❌ Fix commit 0c39cbb NOT found on this branch"
    echo "   Run: git pull origin main"
    exit 1
fi
echo ""

# 2. Find Lambda function
echo "2. Finding console-chat-responder Lambda..."
FUNCTION_NAME=$(aws lambda list-functions \
  --query 'Functions[?contains(FunctionName, `ConsoleChatResponder`)].FunctionName' \
  --output text 2>/dev/null || echo "")

if [ -z "$FUNCTION_NAME" ]; then
    echo "❌ Could not find ConsoleChatResponder Lambda function"
    echo "   May need different AWS profile or region"
    exit 1
fi

echo "✅ Found: $FUNCTION_NAME"
echo ""

# 3. Check IAM permissions
echo "3. Checking IAM permissions..."
ROLE_ARN=$(aws lambda get-function \
  --function-name "$FUNCTION_NAME" \
  --query 'Configuration.Role' \
  --output text)

ROLE_NAME=$(echo "$ROLE_ARN" | awk -F'/' '{print $NF}')

echo "   Role: $ROLE_NAME"

HAS_GET_PARAMETERS=false
POLICIES=$(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames[]' --output text)

for policy in $POLICIES; do
    POLICY_DOC=$(aws iam get-role-policy --role-name "$ROLE_NAME" --policy-name "$policy" --output json)
    
    if echo "$POLICY_DOC" | grep -q "ssm:GetParameters"; then
        echo "✅ Found ssm:GetParameters permission"
        HAS_GET_PARAMETERS=true
        break
    fi
done

if [ "$HAS_GET_PARAMETERS" = false ]; then
    echo "❌ Missing ssm:GetParameters permission"
    echo "   IAM fix may not be deployed yet"
    exit 1
fi
echo ""

# 4. Check recent Lambda invocations
echo "4. Checking recent Lambda logs for errors..."
LOG_GROUP="/aws/lambda/$FUNCTION_NAME"

LATEST_STREAM=$(aws logs describe-log-streams \
  --log-group-name "$LOG_GROUP" \
  --order-by LastEventTime \
  --descending \
  --max-items 1 \
  --query 'logStreams[0].logStreamName' \
  --output text 2>/dev/null || echo "")

if [ -n "$LATEST_STREAM" ]; then
    START_TIME=$(($(date +%s) * 1000 - 300000))
    
    ERRORS=$(aws logs get-log-events \
        --log-group-name "$LOG_GROUP" \
        --log-stream-name "$LATEST_STREAM" \
        --start-time "$START_TIME" \
        --limit 50 \
        --output json 2>/dev/null | jq -r '.events[].message' | grep -i "jwt.*secret\|accessdenied" || echo "")
    
    if [ -n "$ERRORS" ]; then
        echo "⚠️  Found JWT/permission errors in recent logs:"
        echo "$ERRORS"
        exit 1
    else
        echo "✅ No JWT secret errors in recent logs (last 5 minutes)"
    fi
else
    echo "⚠️  No recent log streams found"
    echo "   Lambda may not have been invoked recently"
fi
echo ""

echo "================================================"
echo "✅ Verification PASSED"
echo "================================================"
echo ""
echo "The IAM fix appears to be properly deployed."
echo ""
echo "Next steps:"
echo "1. Test web console chat with a message that uses tools"
echo "2. Try: 'What are the 5 most recent references?'"
echo "3. Watch for successful response (takes 10-60 seconds)"
echo ""
echo "For detailed verification, see:"
echo "  WEB-CONSOLE-CHAT-FIX-VERIFICATION.md"
