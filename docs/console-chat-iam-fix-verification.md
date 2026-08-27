# Console Chat IAM Fix Verification

## Issue Summary

**Problem**: Production web console chat failed with "Could not resolve JWT signing secret" error when users tried to invoke Papyrus tools.

**Root Cause**: The `console-chat-responder` Lambda IAM role only had `ssm:GetParameter` (singular) permission, but the Python code uses boto3's `get_parameters()` (plural) API to read JWT secrets from SSM.

**Fix Commit**: `0c39cbb`  
**Fixed File**: `amplify/functions/console-chat-responder/resource.ts`

## The Fix

Added `ssm:GetParameters` to the IAM policy actions:

```typescript
actions: ["ssm:GetParameter", "ssm:GetParameters"],
```

## Automated Verification

Run the verification script (requires AWS credentials):

```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1
./scripts/verify-production-console-chat.sh
```

This will check:
1. ✓ IAM fix is in the code
2. ✓ AWS credentials are configured
3. ✓ Lambda has correct IAM permissions
4. ✓ No JWT errors in recent CloudWatch logs

## Manual Verification

Test the web console chat directly:

1. Navigate to https://p.apyr.us/newsroom
2. Sign in as an editor
3. Click the console chat icon (top right)
4. Send a message: `list recent references`
5. Wait 10-60 seconds
6. **Expected**: Response with list of references
7. **Before fix**: "Could not resolve JWT signing secret" error

## Troubleshooting

### Check CloudWatch Logs

```bash
aws logs tail /aws/lambda/amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --follow --format short
```

### Verify Lambda IAM Role

```bash
aws lambda get-function-configuration \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --query 'Role' --output text
```

### Check Amplify Deployment

```bash
aws amplify list-jobs \
  --app-id dbsyytcm9drqa \
  --branch-name main \
  --max-results 3
```

Or visit: https://us-east-1.console.aws.amazon.com/amplify/home?region=us-east-1#/dbsyytcm9drqa

## Related Changes

This same fix was previously applied to the Slack agent Lambdas in commit `8da24e2`.
