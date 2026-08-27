#!/bin/bash
set -euo pipefail

# Test script for production console chat IAM fix verification
# This script checks if the SSM IAM permissions are properly deployed

echo "=========================================="
echo "Production Console Chat IAM Fix Test"
echo "=========================================="
echo ""

export AWS_PROFILE=Ryan
export AWS_REGION=us-east-1
FUNCTION_NAME="amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D"

echo "1. Checking Lambda function configuration..."
echo "-------------------------------------------"

# Check if function exists
if ! aws lambda get-function --function-name "$FUNCTION_NAME" &>/dev/null; then
    echo "❌ ERROR: Lambda function not found: $FUNCTION_NAME"
    echo "The function may not be deployed yet or the name may have changed."
    exit 1
fi

echo "✓ Lambda function exists"
echo ""

# Get function details
echo "2. Getting Lambda function ARN and role..."
echo "-------------------------------------------"
FUNCTION_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --query 'Configuration.FunctionArn' --output text)
ROLE_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --query 'Configuration.Role' --output text)
ROLE_NAME=$(echo "$ROLE_ARN" | awk -F'/' '{print $NF}')

echo "Function ARN: $FUNCTION_ARN"
echo "Role ARN: $ROLE_ARN"
echo "Role Name: $ROLE_NAME"
echo ""

# Get role policies
echo "3. Checking IAM role policies for SSM permissions..."
echo "-------------------------------------------"

# Get inline policies
INLINE_POLICIES=$(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames[]' --output text)

if [ -z "$INLINE_POLICIES" ]; then
    echo "⚠️  No inline policies found"
else
    echo "Inline policies found:"
    for policy in $INLINE_POLICIES; do
        echo "  - $policy"
    done
    echo ""
    
    # Check each inline policy for SSM permissions
    echo "Checking for SSM GetParameters permission..."
    HAS_GET_PARAMETERS=false
    HAS_SSM_RESOURCES=false
    
    for policy in $INLINE_POLICIES; do
        POLICY_DOC=$(aws iam get-role-policy --role-name "$ROLE_NAME" --policy-name "$policy" --output json)
        
        # Check for GetParameters action
        if echo "$POLICY_DOC" | grep -q "ssm:GetParameters"; then
            echo "✓ Found ssm:GetParameters in policy: $policy"
            HAS_GET_PARAMETERS=true
        fi
        
        if echo "$POLICY_DOC" | grep -q "ssm:GetParameter"; then
            echo "✓ Found ssm:GetParameter in policy: $policy"
        fi
        
        # Check for proper resource ARNs
        if echo "$POLICY_DOC" | grep -q "parameter/amplify/papyrus/"; then
            echo "✓ Found Amplify Papyrus SSM resource path in policy: $policy"
            HAS_SSM_RESOURCES=true
        fi
        
        if echo "$POLICY_DOC" | grep -q "parameter/amplify/dbsyytcm9drqa/"; then
            echo "✓ Found production app ID SSM resource path in policy: $policy"
            HAS_SSM_RESOURCES=true
        fi
    done
    echo ""
    
    if [ "$HAS_GET_PARAMETERS" = true ] && [ "$HAS_SSM_RESOURCES" = true ]; then
        echo "✅ SUCCESS: IAM permissions are correctly configured!"
        echo ""
        echo "The Lambda has:"
        echo "  - ssm:GetParameters action"
        echo "  - Proper Amplify SSM resource paths"
        echo ""
    else
        echo "❌ PROBLEM: Missing required IAM permissions"
        if [ "$HAS_GET_PARAMETERS" = false ]; then
            echo "  - Missing ssm:GetParameters action"
        fi
        if [ "$HAS_SSM_RESOURCES" = false ]; then
            echo "  - Missing proper SSM resource paths"
        fi
        echo ""
        echo "This indicates the IAM fix has not been fully deployed."
        exit 1
    fi
fi

# Check environment variables
echo "4. Checking Lambda environment variables..."
echo "-------------------------------------------"
ENV_VARS=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --query 'Environment.Variables' --output json)

if echo "$ENV_VARS" | jq -e '.PAPYRUS_GRAPHQL_ENDPOINT' &>/dev/null; then
    GRAPHQL_ENDPOINT=$(echo "$ENV_VARS" | jq -r '.PAPYRUS_GRAPHQL_ENDPOINT')
    echo "✓ PAPYRUS_GRAPHQL_ENDPOINT: $GRAPHQL_ENDPOINT"
else
    echo "⚠️  PAPYRUS_GRAPHQL_ENDPOINT not set"
fi

if echo "$ENV_VARS" | jq -e '.AMPLIFY_SSM_ENV_CONFIG' &>/dev/null; then
    SSM_CONFIG=$(echo "$ENV_VARS" | jq -r '.AMPLIFY_SSM_ENV_CONFIG')
    echo "✓ AMPLIFY_SSM_ENV_CONFIG: $SSM_CONFIG"
else
    echo "⚠️  AMPLIFY_SSM_ENV_CONFIG not set"
fi
echo ""

# Check recent Lambda invocations
echo "5. Checking recent Lambda invocations..."
echo "-------------------------------------------"

# Get CloudWatch log group
LOG_GROUP="/aws/lambda/$FUNCTION_NAME"

# Check if log group exists
if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --query 'logGroups[0].logGroupName' --output text | grep -q "$LOG_GROUP"; then
    echo "✓ CloudWatch log group exists: $LOG_GROUP"
    
    # Get recent log events
    echo ""
    echo "Recent log events (last 5 minutes):"
    echo "-------------------------------------------"
    START_TIME=$(($(date +%s) * 1000 - 300000))  # 5 minutes ago
    
    STREAMS=$(aws logs describe-log-streams \
        --log-group-name "$LOG_GROUP" \
        --order-by LastEventTime \
        --descending \
        --max-items 3 \
        --query 'logStreams[*].logStreamName' \
        --output text)
    
    if [ -n "$STREAMS" ]; then
        for stream in $STREAMS; do
            echo ""
            echo "Stream: $stream"
            aws logs get-log-events \
                --log-group-name "$LOG_GROUP" \
                --log-stream-name "$stream" \
                --start-time "$START_TIME" \
                --limit 20 \
                --query 'events[*].message' \
                --output text | head -20 || true
        done
    else
        echo "No recent log streams found"
    fi
else
    echo "⚠️  CloudWatch log group not found: $LOG_GROUP"
fi

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
