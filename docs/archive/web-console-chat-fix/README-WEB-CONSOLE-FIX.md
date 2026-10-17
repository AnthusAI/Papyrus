# Web Console Chat IAM Fix

## Problem

Production web console chat was failing when users tried to use Papyrus tools (e.g., listing references, knowledge queries). The error was:

> **"Could not resolve JWT signing secret"**

## Root Cause

- The console-chat-responder Lambda needs to mint GraphQL JWTs by reading secrets from AWS SSM
- Python code uses boto3's `get_parameters()` (plural) API call
- Lambda IAM policy only granted `ssm:GetParameter` (singular) permission
- Result: `AccessDeniedException` when trying to read the JWT secret from SSM

## The Fix

**Commit:** `0c39cbb` (June 3, 2026)  
**PR:** #23 - https://github.com/AnthusAI/Papyrus/pull/23  
**Status:** ✅ Merged to main

### Changes Made

Updated `amplify/functions/console-chat-responder/resource.ts` (lines 114-124):

```typescript
this.responderFunction.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ["ssm:GetParameter", "ssm:GetParameters"],  // Added GetParameters (plural)
  resources: [
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/papyrus/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/papyrus/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/dbsyytcm9drqa/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/dbsyytcm9drqa/*`,
  ],
}));
```

### Why Both Permissions?

The code is designed to work in multiple environments:
- **Lambda with boto3:** Uses `get_parameters()` → requires `ssm:GetParameters`
- **CLI fallback:** Uses `aws ssm get-parameter` → requires `ssm:GetParameter`

The fix ensures both code paths have proper permissions.

## How to Verify

### Quick Check

```bash
cd ~/Projects/Papyrus-production
./verify-console-chat-fix.sh
```

This script will:
1. ✅ Confirm fix commit is deployed
2. ✅ Find the Lambda function
3. ✅ Verify IAM permissions include `ssm:GetParameters`
4. ✅ Check recent CloudWatch logs for JWT errors

### Manual Test

1. Open production Papyrus at `/newsroom`
2. Sign in as an editor
3. Open console chat (icon in top bar)
4. Send: **"What are the 5 most recent references?"**
5. Wait 10-60 seconds for response

**Success:** You get a list of references  
**Failure:** Error about JWT or secrets

### Detailed Verification

See `WEB-CONSOLE-CHAT-FIX-VERIFICATION.md` for:
- Complete step-by-step verification
- CloudWatch log analysis
- DynamoDB message status checks
- Troubleshooting guide
- Rollback instructions

## Files in This Fix

- `verify-console-chat-fix.sh` - Quick automated verification script
- `WEB-CONSOLE-CHAT-FIX-VERIFICATION.md` - Complete verification guide
- `test-production-console-chat.sh` - Detailed IAM & logging inspection
- `test_production_iam.py` - Python-based IAM verification
- `README-WEB-CONSOLE-FIX.md` - This file

## Technical Details

### Code Flow

```
User sends message in web console
  ↓
console-chat-responder Lambda triggered
  ↓
execute_tactus_runner.py runs
  ↓
ensure_graphql_authoring_jwt() called
  ↓
_resolve_secret() tries multiple sources
  ↓
_read_ssm_secret_boto() uses boto3
  ↓
client.get_parameters(Names=[param])  ← Requires ssm:GetParameters
  ↓
JWT minted and stored in PAPYRUS_GRAPHQL_JWT
  ↓
GraphQL queries work, tools execute
  ↓
Response returned to user
```

### Affected Files

**Lambda Runtime:**
- `amplify/functions/console-chat-responder/resource.ts` - IAM permissions (THE FIX)
- `amplify/functions/console-chat-responder/py/execute_tactus_runner.py` - Entry point
- `src/papyrus_content/env.py` - JWT setup logic
- `src/papyrus_content/auth_commands.py` - SSM secret resolution

**IAM Resources:**
- Console-chat-responder Lambda execution role
- SSM parameters under `/amplify/papyrus/*` and `/amplify/dbsyytcm9drqa/*`

## Deployment Status

- ✅ Code merged to `main` branch
- ✅ Commit 0c39cbb on GitHub
- ⏳ Waiting for Amplify production deployment to complete
- ⏳ Needs manual verification after deployment

Check deployment at: https://console.aws.amazon.com/amplify → Papyrus (dbsyytcm9drqa) → main branch

## If It's Still Not Working

### 1. Check if deployed

```bash
cd ~/Projects/Papyrus-production
git log --oneline -5 | grep 0c39cbb
```

Should show the fix commit.

### 2. Check Amplify deployment

Go to Amplify Console → app `dbsyytcm9drqa` → Deployments

Look for successful deployment after June 3, 2026 21:37:48Z

### 3. Force redeploy if needed

If commit is on main but IAM didn't update:
- Trigger manual redeploy from Amplify Console
- Or push a trivial commit to force pipeline

### 4. Temporary workaround

Set JWT secret directly in Lambda environment (not recommended for production):

```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1

SECRET=$(aws ssm get-parameter \
  --name "/amplify/papyrus/ryan-sandbox-adcd88a186/PAPYRUS_JWT_SECRET" \
  --with-decryption \
  --query 'Parameter.Value' \
  --output text)

FUNCTION_NAME=$(aws lambda list-functions \
  --query 'Functions[?contains(FunctionName, `ConsoleChatResponder`)].FunctionName' \
  --output text)

aws lambda update-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --environment Variables="{PAPYRUS_JWT_SECRET=$SECRET,...}"
```

## Related Issues

This fix also resolves similar issues in:
- Slack agent console chat (same responder, same IAM)
- Any other Lambda that uses execute_tactus_runner.py
- CLI authoring with Amplify secrets

## References

- PR #23: https://github.com/AnthusAI/Papyrus/pull/23
- Commit: 0c39cbb
- Slack discussion: June 1-3, 2026
- Console Chat Runbook: `docs/console-chat-runbook.md`
- AGENTS.md: GraphQL auth split section

## Questions?

- Check CloudWatch logs: `/aws/lambda/amplify-*-ConsoleChatResponderFunc-*`
- Review Amplify deployment logs
- See detailed troubleshooting in `WEB-CONSOLE-CHAT-FIX-VERIFICATION.md`
