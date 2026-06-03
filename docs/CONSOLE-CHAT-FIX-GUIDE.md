# Console Chat IAM Fix - Quick Guide

## Problem
Production web console chat failed with "Could not resolve JWT signing secret" when using Papyrus tools.

## Root Cause
Lambda IAM role had `ssm:GetParameter` (singular) but Python code uses `get_parameters()` (plural) API.

## Fix
**Commit**: `0c39cbb`  
**File**: `amplify/functions/console-chat-responder/resource.ts`

Added `ssm:GetParameters` to IAM policy:

```typescript
actions: ["ssm:GetParameter", "ssm:GetParameters"],
```

## Verify Deployment

```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1
./scripts/verify-production-console-chat.sh
```

Or manually:
1. Open https://p.apyr.us/newsroom
2. Sign in as editor
3. Open console chat
4. Send: `list recent references`
5. Should respond without JWT errors

## Troubleshooting

Check CloudWatch logs:
```bash
aws logs tail /aws/lambda/amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D --follow
```

Check Lambda IAM role:
```bash
aws lambda get-function-configuration \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --query 'Role'
```
