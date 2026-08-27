# Web Console Chat Fix - Quick Reference

## The Problem
Production web console chat fails with "Could not resolve JWT signing secret" when using tools.

## The Fix
✅ **MERGED**: PR #23, commit `0c39cbb`
- Added `ssm:GetParameters` permission to console-chat-responder Lambda IAM role
- File: `amplify/functions/console-chat-responder/resource.ts` lines 114-124

## Current Status
- ✅ Code is on `main` branch  
- ✅ PR #23 merged at 2026-06-03T21:37:48Z
- ⚠️  **Amplify deployment needs verification**

## Quick Test (3 steps)

### 1. Run Verification Script
```bash
cd ~/Projects/Papyrus-production
export AWS_PROFILE=Ryan AWS_REGION=us-east-1
./scripts/test-console-chat-production.sh
```

### 2. Check for Success Indicators
The script should show:
- ✅ Lambda has `ssm:GetParameters` permission
- ✅ No JWT errors in recent logs
- ✅ Recent console messages completed successfully

### 3. Live Test
Go to https://papyrus.anthus.ai/newsroom, open console chat, send:
```
list the 5 most recent references
```

**Expected**: Get a list of references (not an error)

## If Verification Fails

### Check Amplify Deployment
```bash
# See recent deployments
gh run list --limit 5

# Check Amplify console
open "https://console.aws.amazon.com/amplify/home?region=us-east-1#/dbsyytcm9drqa"
```

### Manual IAM Check
```bash
FUNCTION="amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D"
ROLE_ARN=$(aws lambda get-function-configuration --function-name "$FUNCTION" --profile Ryan --region us-east-1 --query 'Role' --output text)
ROLE_NAME=$(echo "$ROLE_ARN" | awk -F'/' '{print $NF}')

# Check inline policies for SSM permissions
aws iam list-role-policies --role-name "$ROLE_NAME" --profile Ryan --region us-east-1
```

Look for a policy with **both** `ssm:GetParameter` AND `ssm:GetParameters`

## Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| IAM permissions not updated | Amplify deploy didn't run | Check Amplify console, trigger redeploy |
| Permissions updated but still errors | Lambda image is stale | Check Lambda last modified time |
| No recent console messages | No one testing yet | Send a test message |

## Full Documentation

See `docs/web-console-chat-iam-fix.md` for complete details.

## Quick Commands

```bash
# Check Lambda last modified
aws lambda get-function-configuration \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --profile Ryan --region us-east-1 \
  --query '[LastModified,Runtime,Role]' --output table

# Check recent logs
aws logs tail /aws/lambda/amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --profile Ryan --region us-east-1 --since 30m --format short

# Check for JWT errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --profile Ryan --region us-east-1 \
  --start-time $(($(date +%s) * 1000 - 3600000)) \
  --filter-pattern '"Could not resolve JWT signing secret"'
```
