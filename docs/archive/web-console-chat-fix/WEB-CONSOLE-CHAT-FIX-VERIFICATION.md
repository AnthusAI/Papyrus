# Web Console Chat Production Fix - Verification Guide

## Executive Summary

**Status**: ✅ Fix is merged and in code (commit `0c39cbb`)  
**Issue**: Production web console chat was failing with "Could not resolve JWT signing secret" errors  
**Root Cause**: Lambda IAM policy missing `ssm:GetParameters` (plural) permission  
**Fix**: Added `ssm:GetParameters` alongside `ssm:GetParameter` in console-chat-responder IAM policy  

## The Problem

When users attempted to use Papyrus tools in the web console chat (e.g., "list recent references"), the system would fail with JWT signing errors. The console-chat-responder Lambda needs to:

1. Mint a short-lived GraphQL JWT from AWS SSM secrets
2. Pass that JWT to `execute_tactus` for tool execution
3. The Python code uses boto3's `client.get_parameters()` (plural API)
4. The Lambda IAM policy only granted `ssm:GetParameter` (singular)
5. Result: `AccessDeniedException` → "Could not resolve JWT signing secret"

## The Fix (Code)

**File**: `amplify/functions/console-chat-responder/resource.ts` (lines 114-124)

```typescript
// execute_tactus_runner mints PAPYRUS_GRAPHQL_JWT via boto3 get_parameters; branch policies
// often grant GetParameters on path prefixes, not GetParameter per secret name.
this.responderFunction.addToRolePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: ["ssm:GetParameter", "ssm:GetParameters"],  // ← Both added
  resources: [
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/papyrus/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/papyrus/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/dbsyytcm9drqa/*`,
    `arn:aws:ssm:${stack.region}:${stack.account}:parameter/amplify/shared/dbsyytcm9drqa/*`,
  ],
}));
```

**Python Code**: `src/papyrus_content/auth_commands.py` (line 71)

```python
# Uses get_parameters (plural) - requires ssm:GetParameters permission
response = client.get_parameters(Names=[parameter_name], WithDecryption=True)
```

## Verification Steps

### Step 1: Confirm Code Fix is Present (✅ Done)

```bash
cd ~/Projects/Papyrus-production
git log --oneline -1
# Should show: 0c39cbb Fix console-chat-responder SSM permissions...

grep -A 10 "get_parameters" amplify/functions/console-chat-responder/resource.ts
# Should show both GetParameter and GetParameters in actions array
```

### Step 2: Check Amplify Deployment Status

**Option A: Amplify Console**
1. Go to: https://us-east-1.console.aws.amazon.com/amplify/home?region=us-east-1#/dbsyytcm9drqa
2. Click **Backend environments** → **main**
3. Check latest deployment:
   - Should show commit `0c39cbb` or later
   - Status should be **SUCCEED**

**Option B: AWS CLI**
```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1

# Check Lambda IAM policy
aws lambda get-function --function-name \$(aws lambda list-functions --query "Functions[?contains(FunctionName, 'console-chat-responder')].FunctionName | [0]" --output text)

# Get the role name, then:
aws iam list-role-policies --role-name <ROLE_NAME>
aws iam get-role-policy --role-name <ROLE_NAME> --policy-name <POLICY_NAME> | jq '.PolicyDocument.Statement[] | select(.Action | contains("ssm"))'

# Should show BOTH:
# - ssm:GetParameter
# - ssm:GetParameters
```

**Option C: Automated Test Script**
```bash
cd ~/Projects/Papyrus-production
export AWS_PROFILE=Ryan AWS_REGION=us-east-1
python3 scripts/test-console-chat-production.py

# This checks:
# 1. Lambda has correct IAM permissions
# 2. CloudWatch logs for JWT errors (last 15 minutes)
# 3. Recent console chat message status
```

### Step 3: Manual End-to-End Test (2 minutes)

This is the **definitive test** - if this works, the issue is fixed:

1. **Open Production Web Console**
   - Go to: https://papyrus.anthus.ai/newsroom (or https://p.apyr.us/newsroom)
   - Sign in as an editor

2. **Open Console Chat**
   - Click the chat icon in the top right corner
   - The console chat panel should open

3. **Send a Tool-Invoking Message**
   - Type: `What are the 5 most recent references?`
   - Press Enter

4. **Expected Success Behavior**
   - Message shows "Running..." status for ~10-60 seconds
   - You receive a response listing recent references
   - **No error about "JWT signing secret"**

5. **Expected Failure Behavior** (if fix not deployed)
   - Message shows "Running..." briefly
   - Then shows error containing: "Could not resolve JWT signing secret"

### Step 4: Check CloudWatch Logs (If Test Fails)

If the manual test fails, check CloudWatch:

```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1

# Find the log group
LOG_GROUP=$(aws logs describe-log-groups --log-group-name-prefix /aws/lambda/ --query "logGroups[?contains(logGroupName, 'console-chat-responder')].logGroupName | [0]" --output text)

echo "Log group: $LOG_GROUP"

# Get recent error logs
aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --start-time $(date -u -d '15 minutes ago' +%s)000 \
  --filter-pattern "JWT signing secret" \
  --max-items 10

# Or tail live logs
aws logs tail "$LOG_GROUP" --follow --format short
```

## If the Fix Isn't Working

### Scenario A: Fix Not Deployed Yet

**Symptoms:**
- Test script shows missing `ssm:GetParameters` permission
- CloudWatch logs show "Could not resolve JWT signing secret"
- Console chat fails with JWT errors

**Solution:**
1. Check Amplify deployment status (Step 2 above)
2. If commit `0c39cbb` isn't deployed, trigger a deployment:
   ```bash
   # From Amplify Console:
   # Backend deployments → main → Redeploy this version
   
   # Or push a trivial commit to main:
   cd ~/Projects/Papyrus
   git commit --allow-empty -m "Trigger deployment"
   git push origin main
   ```
3. Wait for deployment to complete (~10-15 minutes)
4. Retry manual test

### Scenario B: Different Error

**Symptoms:**
- Test script shows IAM permissions are correct
- But console chat still fails with different error

**Solution:**
1. Check CloudWatch logs for the actual error:
   ```bash
   aws logs tail "$LOG_GROUP" --follow --format short
   ```
2. Look for errors in `execute_tactus_runner` or JWT minting
3. Check SSM parameter exists:
   ```bash
   aws ssm get-parameters \
     --names /amplify/shared/papyrus/PAPYRUS_JWT_SECRET \
     --with-decryption \
     --query "Parameters[0].Name"
   ```

### Scenario C: SSM Parameter Missing

**Symptoms:**
- IAM permissions correct
- But logs show "SSM parameter returned no value"

**Solution:**
1. Verify secret exists in Amplify:
   ```bash
   npx ampx secret list
   ```
2. If missing, set it:
   ```bash
   npx ampx secret set PAPYRUS_JWT_SECRET
   # Paste the secret value (get from team admin or 1Password)
   ```

## Success Criteria

✅ **All checks pass:**
1. Code contains fix (both GetParameter and GetParameters in IAM policy)
2. Amplify deployment succeeded with commit `0c39cbb` or later  
3. Test script reports "ALL CHECKS PASSED"
4. Manual test: Console chat successfully lists references (no JWT error)
5. CloudWatch logs: No "JWT signing secret" errors in last 15 minutes

## Related Files

- **IAM Fix**: `amplify/functions/console-chat-responder/resource.ts` (lines 114-124)
- **JWT Code**: `src/papyrus_content/auth_commands.py` (line 71 - uses `get_parameters`)
- **Lambda Entry**: `amplify/functions/console-chat-responder/py/execute_tactus_runner.py` (line 24)
- **Test Script**: `scripts/test-console-chat-production.py`

## Rollback (Emergency Only)

If the fix causes issues, revert to the previous commit:

```bash
cd ~/Projects/Papyrus
git revert 0c39cbb
git push origin main
# Wait for Amplify deployment
```

**Note**: This will restore the JWT error. Only rollback if the fix introduces a worse issue.

## Timeline

- **Issue Reported**: June 3, 2026, 9:35 PM
- **Fix Merged**: June 3, 2026, 9:39 PM (commit `0c39cbb`, PR #23)
- **Expected Deploy**: Within 15 minutes of push to main (automatic)
- **Verification**: Use this guide after deploy completes

## Support

If verification fails after following all steps:
1. Share the output of `scripts/test-console-chat-production.py`
2. Share recent CloudWatch logs from console-chat-responder
3. Share Amplify deployment status/logs
4. Mention which manual test step failed
