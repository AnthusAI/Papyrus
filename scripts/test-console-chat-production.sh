#!/bin/bash
# Test console chat production deployment and IAM permissions
#
# This script verifies that the console-chat-responder Lambda has the
# correct SSM permissions needed for execute_tactus JWT minting.
#
# The fix (PR #23, commit 0c39cbb) adds ssm:GetParameters permission
# which was missing and causing "Could not resolve JWT signing secret" errors.

set -euo pipefail

# Configuration
LAMBDA_FUNCTION="amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D"
MESSAGE_TABLE="Message-s4sclnevjjbzpmj4vhallzvw3e-NONE"
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-Ryan}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Papyrus Console Chat Production Verification ===${NC}\n"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI not found. Please install it first.${NC}"
    exit 1
fi

# Check credentials
echo -e "${BLUE}1. Verifying AWS credentials...${NC}"
if ! aws sts get-caller-identity --profile "$PROFILE" --region "$REGION" > /dev/null 2>&1; then
    echo -e "${RED}❌ AWS credentials not configured for profile: $PROFILE${NC}"
    exit 1
fi
ACCOUNT=$(aws sts get-caller-identity --profile "$PROFILE" --region "$REGION" --query 'Account' --output text)
echo -e "${GREEN}✓ Connected to AWS account: $ACCOUNT${NC}\n"

# Check Lambda exists
echo -e "${BLUE}2. Checking Lambda function...${NC}"
if ! aws lambda get-function \
    --function-name "$LAMBDA_FUNCTION" \
    --profile "$PROFILE" \
    --region "$REGION" > /dev/null 2>&1; then
    echo -e "${RED}❌ Lambda function not found: $LAMBDA_FUNCTION${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Lambda function exists${NC}\n"

# Get Lambda configuration
echo -e "${BLUE}3. Checking Lambda configuration...${NC}"
LAMBDA_CONFIG=$(aws lambda get-function-configuration \
    --function-name "$LAMBDA_FUNCTION" \
    --profile "$PROFILE" \
    --region "$REGION")

LAST_MODIFIED=$(echo "$LAMBDA_CONFIG" | jq -r '.LastModified')
RUNTIME=$(echo "$LAMBDA_CONFIG" | jq -r '.PackageType')
IMAGE_URI=$(aws lambda get-function \
    --function-name "$LAMBDA_FUNCTION" \
    --profile "$PROFILE" \
    --region "$REGION" \
    --query 'Code.ImageUri' \
    --output text)

echo "  Last Modified: $LAST_MODIFIED"
echo "  Package Type: $RUNTIME"
echo "  Image URI: $IMAGE_URI"
echo ""

# Check IAM role permissions
echo -e "${BLUE}4. Checking IAM role permissions (THE CRITICAL FIX)...${NC}"
ROLE_ARN=$(echo "$LAMBDA_CONFIG" | jq -r '.Role')
ROLE_NAME=$(echo "$ROLE_ARN" | awk -F'/' '{print $NF}')

echo "  Role: $ROLE_NAME"

# Get attached policies
ATTACHED_POLICIES=$(aws iam list-attached-role-policies \
    --role-name "$ROLE_NAME" \
    --profile "$PROFILE" \
    --region "$REGION" \
    --query 'AttachedPolicies[*].PolicyArn' \
    --output text)

# Get inline policies
INLINE_POLICIES=$(aws iam list-role-policies \
    --role-name "$ROLE_NAME" \
    --profile "$PROFILE" \
    --region "$REGION" \
    --query 'PolicyNames[*]' \
    --output text)

# Check for SSM permissions in inline policies
echo -e "\n${YELLOW}Checking for SSM GetParameters permission...${NC}"
HAS_GET_PARAMETERS=false
HAS_SSM_ACTIONS=false

for policy in $INLINE_POLICIES; do
    POLICY_DOC=$(aws iam get-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "$policy" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --query 'PolicyDocument' \
        --output json)
    
    # Check if policy has SSM actions
    if echo "$POLICY_DOC" | jq -e '.Statement[] | select(.Action[]? | contains("ssm:"))' > /dev/null 2>&1; then
        HAS_SSM_ACTIONS=true
        echo "  Found SSM permissions in policy: $policy"
        
        # Check specifically for GetParameters (plural)
        if echo "$POLICY_DOC" | jq -e '.Statement[] | select(.Action[]? | contains("ssm:GetParameters"))' > /dev/null 2>&1; then
            HAS_GET_PARAMETERS=true
            echo -e "  ${GREEN}✓ Found ssm:GetParameters permission${NC}"
        fi
        
        # Show the SSM-related actions
        echo "$POLICY_DOC" | jq -r '.Statement[] | select(.Action[]? | contains("ssm:")) | .Action[]?' | grep ssm: | sort -u | sed 's/^/    - /'
    fi
done

if [ "$HAS_GET_PARAMETERS" = true ]; then
    echo -e "\n${GREEN}✓ IAM FIX IS DEPLOYED: Lambda has ssm:GetParameters permission${NC}\n"
else
    echo -e "\n${RED}❌ IAM FIX NOT DEPLOYED: Lambda missing ssm:GetParameters permission${NC}"
    echo -e "${RED}   This will cause 'Could not resolve JWT signing secret' errors${NC}\n"
    exit 1
fi

# Check recent Lambda logs
echo -e "${BLUE}5. Checking recent Lambda execution logs...${NC}"
LOG_GROUP="/aws/lambda/$LAMBDA_FUNCTION"

# Get recent log streams
RECENT_STREAMS=$(aws logs describe-log-streams \
    --log-group-name "$LOG_GROUP" \
    --profile "$PROFILE" \
    --region "$REGION" \
    --order-by LastEventTime \
    --descending \
    --max-items 5 \
    --query 'logStreams[*].[logStreamName,lastEventTime]' \
    --output text)

if [ -z "$RECENT_STREAMS" ]; then
    echo -e "${YELLOW}⚠ No recent log streams found${NC}\n"
else
    echo "Recent executions:"
    echo "$RECENT_STREAMS" | while read stream timestamp; do
        DATE=$(date -d "@$((timestamp / 1000))" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r "$((timestamp / 1000))" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "")
        echo "  - $stream ($DATE)"
    done
    echo ""
    
    # Check for JWT errors in recent logs
    echo -e "${YELLOW}Checking for JWT signing secret errors...${NC}"
    ERROR_COUNT=$(aws logs filter-log-events \
        --log-group-name "$LOG_GROUP" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --start-time "$(($(date +%s) * 1000 - 3600000))" \
        --filter-pattern "\"Could not resolve JWT signing secret\"" \
        --query 'length(events)' \
        --output text 2>/dev/null || echo "0")
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo -e "${RED}❌ Found $ERROR_COUNT JWT signing secret errors in last hour${NC}"
        echo -e "${RED}   The fix may not be deployed or a new image is needed${NC}\n"
    else
        echo -e "${GREEN}✓ No JWT signing secret errors found in last hour${NC}\n"
    fi
fi

# Check recent console chat messages
echo -e "${BLUE}6. Checking recent console chat messages...${NC}"
RECENT_MESSAGES=$(aws dynamodb query \
    --table-name "$MESSAGE_TABLE" \
    --index-name messagesByMessageKindAndCreatedAt \
    --key-condition-expression 'messageKind = :kind' \
    --expression-attribute-values '{":kind":{"S":"console_chat_turn"}}' \
    --scan-index-forward false \
    --limit 5 \
    --profile "$PROFILE" \
    --region "$REGION" \
    --query 'Items[*].[id.S,role.S,responseStatus.S,createdAt.S]' \
    --output text 2>/dev/null || echo "")

if [ -z "$RECENT_MESSAGES" ]; then
    echo -e "${YELLOW}⚠ No recent console chat messages found${NC}"
    echo "  This might mean:"
    echo "    - No one has used the console chat recently"
    echo "    - The table name or index has changed"
    echo ""
else
    echo "Recent console chat turns:"
    echo "$RECENT_MESSAGES" | while read id role status created; do
        STATUS_COLOR="$NC"
        if [ "$status" = "COMPLETED" ]; then
            STATUS_COLOR="$GREEN"
        elif [ "$status" = "FAILED" ]; then
            STATUS_COLOR="$RED"
        elif [ "$status" = "RUNNING" ]; then
            STATUS_COLOR="$YELLOW"
        fi
        echo -e "  - $role message $id: ${STATUS_COLOR}$status${NC} ($created)"
    done
    echo ""
    
    # Count failed messages
    FAILED_COUNT=$(echo "$RECENT_MESSAGES" | grep -c "FAILED" || echo "0")
    if [ "$FAILED_COUNT" -gt 0 ]; then
        echo -e "${RED}⚠ Found $FAILED_COUNT failed messages in recent history${NC}"
        echo "  Check Lambda logs for specific errors"
        echo ""
    fi
fi

# Final summary
echo -e "${BLUE}=== Summary ===${NC}"
echo ""
if [ "$HAS_GET_PARAMETERS" = true ] && [ "$ERROR_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✓ VERIFICATION PASSED${NC}"
    echo ""
    echo "The console chat IAM fix is deployed and working:"
    echo "  ✓ Lambda has ssm:GetParameters permission"
    echo "  ✓ No JWT signing secret errors in recent logs"
    echo ""
    echo "If users still report issues:"
    echo "  1. Check if they're actually using production vs sandbox"
    echo "  2. Verify the Lambda image includes the Rust code changes"
    echo "  3. Check for other errors in CloudWatch logs"
    echo ""
elif [ "$HAS_GET_PARAMETERS" = true ]; then
    echo -e "${YELLOW}⚠ PARTIAL DEPLOYMENT${NC}"
    echo ""
    echo "IAM permissions are fixed but there were recent errors."
    echo "The Lambda may need a new image deployment."
    echo ""
else
    echo -e "${RED}✓ VERIFICATION FAILED${NC}"
    echo ""
    echo "The IAM fix is NOT deployed to production."
    echo ""
    echo "To fix this:"
    echo "  1. Verify commit 0c39cbb is on main branch (it is)"
    echo "  2. Check Amplify deployment status for main branch"
    echo "  3. If Amplify shows success, the CDK may need manual redeployment"
    echo "  4. Check: https://console.aws.amazon.com/amplify/home?region=us-east-1#/dbsyytcm9drqa"
    echo ""
fi
