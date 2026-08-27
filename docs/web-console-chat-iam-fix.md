# Web Console Chat Production Fix - Verification Guide

## Issue Summary

**Problem**: Production web console chat was failing when users invoked Papyrus tools (e.g., "list recent references")

**Error**: "Could not resolve JWT signing secret"

**Root Cause**: The `console-chat-responder` Lambda needed to mint GraphQL JWTs from AWS SSM using boto3's `get_parameters` (plural) API, but the IAM policy only granted `ssm:GetParameter` (singular) permission.

**Fix**: PR #23, commit `0c39cbb` - Added `ssm:GetParameters` permission to the Lambda IAM role

## The Code Fix

File: `amplify/functions/console-chat-responder/resource.ts`

Lines 114-124 now include:

```typescript
this.responderFunction.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ["ssm:GetParameter", "ssm:GetParameters"],  // <-- Added GetParameters
  resources: [
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/papyrus/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/papyrus/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/dbsyytcm9drqa/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/dbsyytcm9drqa/*`,
  ],
}));
```

## Deployment Status

- **Code committed**: ✅ Yes (commit 0c39cbb)
- **PR merged**: ✅ Yes (PR #23, merged 2026-06-03T21:37:48Z)
- **On main branch**: ✅ Yes (HEAD is at 0c39cbb)
- **Amplify deployment**: ⚠️  **NEEDS VERIFICATION**

## How to Verify Production Deployment

### Quick Check (30 seconds)

```bash
cd ~/Projects/Papyrus-production
export AWS_PROFILE=Ryan
export AWS_REGION=us-east-1

# Run the verification script
./scripts/test-console-chat-production.sh
```

This script will:
1. ✅ Check AWS credentials
2. ✅ Verify Lambda function exists
3. ✅ **Check if IAM role has `ssm:GetParameters` permission** (THE CRITICAL FIX)
4. ✅ Scan CloudWatch logs for JWT signing secret errors
5. ✅ Query recent console chat messages for failures

### Manual Verification

If you prefer to check manually:

#### 1. Check IAM Role Permissions

```bash
FUNCTION="amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D"

# Get the Lambda's IAM role
ROLE_ARN=$(aws lambda get-function-configuration \
  --function-name "$FUNCTION" \
  --profile Ryan \
  --region us-east-1 \
  --query 'Role' \
  --output text)

ROLE_NAME=$(echo "$ROLE_ARN" | awk -F'/' '{print $NF}')

# List inline policies
aws iam list-role-policies \
  --role-name "$ROLE_NAME" \
  --profile Ryan \
  --region us-east-1

# Check each policy for SSM GetParameters permission
for policy in $(aws iam list-role-policies --role-name "$ROLE_NAME" --profile Ryan --region us-east-1 --query 'PolicyNames[]' --output text); do
  echo "=== Policy: $policy ==="
  aws iam get-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$policy" \
    --profile Ryan \
    --region us-east-1 \
    --query 'PolicyDocument.Statement[?Action[?contains(@, `ssm:`)]]' \
    --output json | jq '.[] | {Effect, Action, Resource}'
done
```

**Look for**: An SSM policy statement that includes **both** `ssm:GetParameter` and `ssm:GetParameters`

#### 2. Check Recent Errors

```bash
# Check for JWT signing secret errors in last hour
aws logs filter-log-events \
  --log-group-name "/aws/lambda/$FUNCTION" \
  --profile Ryan \
  --region us-east-1 \
  --start-time $(($(date +%s) * 1000 - 3600000)) \
  --filter-pattern '"Could not resolve JWT signing secret"'
```

**Expected**: No results (empty events array)

#### 3. Check Recent Console Chat Messages

```bash
# Query recent console chat turns
aws dynamodb query \
  --table-name Message-s4sclnevjjbzpmj4vhallzvw3e-NONE \
  --index-name messagesByMessageKindAndCreatedAt \
  --key-condition-expression 'messageKind = :kind' \
  --expression-attribute-values '{":kind":{"S":"console_chat_turn"}}' \
  --scan-index-forward false \
  --limit 10 \
  --profile Ryan \
  --region us-east-1 \
  --query 'Items[*].[id.S,role.S,responseStatus.S,createdAt.S,responseError.S]' \
  --output table
```

**Look for**: Recent messages with status `COMPLETED` (not `FAILED`)

### 3. Test Live

The most definitive test is to send a message in the production web console:

1. Go to https://papyrus.anthus.ai/newsroom
2. Sign in as an editor
3. Open the console chat (icon in top-right)
4. Send a message that requires tools: **"list the 5 most recent references"**
5. Wait 30-60 seconds for response

**Expected**: You should see a list of recent references, not an error.

## What If It's Not Fixed?

If verification shows the IAM permissions are NOT deployed:

### Option 1: Check Amplify Deployment Status

```bash
# Check recent Amplify deployments
gh run list --limit 10 --json conclusion,displayTitle,createdAt,headSha

# Check the specific commit's deployment
gh run list --commit 0c39cbb
```

Look for:
- Failed builds that need to be rerun
- Backend deployment that succeeded but didn't update IAM
- CDK circular dependency errors (there were some in history)

### Option 2: Manual Amplify Redeploy

If Amplify shows the deployment succeeded but IAM isn't updated:

1. Go to https://console.aws.amazon.com/amplify/home?region=us-east-1#/dbsyytcm9drqa
2. Check the `main` branch deployment status
3. If needed, click **Redeploy this version** on the most recent commit
4. Wait for backend deploy to complete (~10-15 minutes)
5. Re-run verification

### Option 3: Force CDK Update (Last Resort)

If Amplify isn't picking up the IAM changes, you may need to force a CDK deployment:

```bash
cd ~/Projects/Papyrus-production
git pull origin main
export AWS_PROFILE=Ryan AWS_REGION=us-east-1

# This requires the Amplify CLI and proper permissions
npx ampx generate outputs --branch main --app-id dbsyytcm9drqa
```

## Common Issues

### Issue: "Fix is deployed but still getting errors"

**Possible causes**:
1. **Stale Lambda container**: The Lambda image hasn't been updated
2. **Wrong error**: A different error looks similar
3. **Cached failure**: The UI is showing an old failed message

**Solution**:
- Check Lambda last modified time
- Look at the actual error in CloudWatch logs
- Try a fresh browser session / clear cache

### Issue: "IAM has GetParameters but errors continue"

**Possible causes**:
1. **Wrong SSM path**: The parameter doesn't exist at the expected path
2. **Parameter not set**: `PAPYRUS_JWT_SECRET` isn't in SSM
3. **Different error**: Not actually an SSM permission error

**Solution**:
```bash
# Check if the JWT secret exists
aws ssm get-parameter \
  --name "/amplify/papyrus/ryan-sandbox-adcd88a186/PAPYRUS_JWT_SECRET" \
  --profile Ryan \
  --region us-east-1 \
  --with-decryption \
  --query 'Parameter.Name' \
  --output text

# Or check all Amplify secrets
aws ssm describe-parameters \
  --profile Ryan \
  --region us-east-1 \
  --parameter-filters "Key=Name,Values=/amplify/papyrus/" \
  --query 'Parameters[*].[Name,LastModifiedDate]' \
  --output table
```

## Timeline

- **Issue reported**: 2026-06-03 ~21:35 (9:35 PM)
- **Fix created**: PR #23
- **Fix merged**: 2026-06-03 21:37:48Z
- **Current HEAD**: 0c39cbb (the fix commit)
- **Deployment status**: NEEDS VERIFICATION

## Related Documentation

- Main runbook: `docs/console-chat-runbook.md`
- Fix PR: https://github.com/AnthusAI/Papyrus/pull/23
- Slack discussion: Extensive troubleshooting 2026-06-02 to 2026-06-03

## Who to Contact

If issues persist after verification:
- Check #papyrus Slack channel
- Review CloudWatch logs: `/aws/lambda/amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D`
- Check Amplify Console: https://console.aws.amazon.com/amplify/home?region=us-east-1#/dbsyytcm9drqa
