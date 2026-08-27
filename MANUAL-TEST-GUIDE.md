# Production Web Console Chat - Manual Test Guide

## Quick Test (After Verification Scripts Pass)

This is the fastest way to confirm the web console chat is working end-to-end.

### Prerequisites

1. ✅ Fix commit `0c39cbb` is deployed (check with `git log`)
2. ✅ IAM permissions verified (run `./verify-console-chat-fix.sh`)
3. ✅ No JWT errors in CloudWatch logs (checked by verification script)

### Test Steps

#### 1. Open Production Newsroom

```
https://papyrus.anthus.ai/newsroom
```

Or whatever your production URL is.

#### 2. Sign In

- Use your editor account
- Must be in `editor` or `admin` Cognito group

#### 3. Open Console Chat

- Look for chat icon in top navigation bar
- Click to open console panel
- Should see empty chat or existing conversation

#### 4. Send Test Message

Type one of these test messages:

**Test 1: List references (uses Reference.list tool)**
```
What are the 5 most recent references?
```

**Test 2: Search references (uses knowledge search)**
```
Show me references about machine learning
```

**Test 3: General question (may or may not use tools)**
```
What can you help me with?
```

#### 5. Wait for Response

- Response typically takes 10-60 seconds
- You'll see a loading indicator
- Assistant message appears when complete

### Success Criteria

✅ **Working correctly if:**
- Response appears within 60 seconds
- Response includes actual reference data (for test 1 or 2)
- No error messages about JWT or secrets
- Subsequent messages also work

❌ **Still broken if:**
- Error message: "Could not resolve JWT signing secret"
- Timeout after 2+ minutes
- Message stuck in "pending" state
- Generic error without reference data

### What to Check if It Fails

#### 1. Browser Console

Open browser DevTools → Console tab

Look for:
- Network errors to GraphQL endpoint
- JavaScript errors
- Failed GraphQL mutations

#### 2. CloudWatch Logs

```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1

# Find function
FUNCTION_NAME=$(aws lambda list-functions \
  --query 'Functions[?contains(FunctionName, `ConsoleChatResponder`)].FunctionName' \
  --output text)

# Get latest logs
aws logs tail "/aws/lambda/$FUNCTION_NAME" --follow
```

Look for:
- "Could not resolve JWT signing secret"
- "AccessDeniedException"
- Python tracebacks
- "FAILED" status

#### 3. DynamoDB Messages

Check if message was created and processed:

```bash
export AWS_PROFILE=Ryan AWS_REGION=us-east-1

# Find Message table
TABLE_NAME=$(aws dynamodb list-tables \
  --query 'TableNames[?contains(@, `Message`)]' \
  --output text | grep -v Thread | head -1)

# Get recent console messages
aws dynamodb scan \
  --table-name "$TABLE_NAME" \
  --filter-expression "messageKind = :kind AND begins_with(createdAt, :today)" \
  --expression-attribute-values '{
    ":kind": {"S": "console_chat_turn"},
    ":today": {"S": "'$(date -u +%Y-%m-%d)'"}}' \
  --projection-expression "id,createdAt,messageRole,responseStatus" \
  --max-items 5 \
  --output table
```

Your test message should show:
- User message with `responseStatus: COMPLETED`
- Assistant message created in response

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| JWT secret error | IAM not deployed | Wait for Amplify deploy to complete |
| Timeout | Lambda timeout | Check Lambda has 120s timeout, 1024MB memory |
| No response | Stream mapping disabled | Check DynamoDB stream is enabled |
| Generic error | GraphQL endpoint wrong | Verify `PAPYRUS_GRAPHQL_ENDPOINT` env var |
| Permission error | JWT minting failed | Check `PAPYRUS_JWT_SECRET` in SSM |

### After Successful Test

1. ✅ Mark the issue as resolved
2. ✅ Document in team chat that web console is working
3. ✅ Monitor CloudWatch for any new errors
4. ✅ Test with a few different queries to confirm stability

### If Test Fails

1. Run detailed verification:
   ```bash
   cd ~/Projects/Papyrus-production
   ./test-production-console-chat.sh
   ```

2. Check the troubleshooting guide:
   ```bash
   less WEB-CONSOLE-CHAT-FIX-VERIFICATION.md
   # Search for "Troubleshooting" section
   ```

3. Review CloudWatch logs for specific error

4. If IAM fix is deployed but still failing:
   - Check `AMPLIFY_SSM_ENV_CONFIG` environment variable
   - Verify JWT secret exists in SSM
   - Confirm GraphQL endpoint is correct
   - Check if Lambda has AppSync IAM permissions

5. See rollback instructions in `WEB-CONSOLE-CHAT-FIX-VERIFICATION.md` if needed

## Additional Test Cases

Once basic test works, try these:

### Test with Multiple Tools

```
Find recent references about neural networks and create an insight
```

Should use multiple tools in sequence.

### Test with Navigation Context

From a specific newsroom page:
```
What references are related to what I'm looking at?
```

Should use web UI context if available.

### Test Error Handling

```
Show me references from nonexistent category
```

Should handle gracefully and explain the issue.

## Performance Benchmarks

Normal response times:
- Simple query (no tools): 2-5 seconds
- Single tool call: 10-30 seconds
- Multiple tools: 30-60 seconds
- Complex research: 60-120 seconds

If consistently slower, check:
- Lambda cold starts (check CloudWatch metrics)
- GraphQL query performance
- Network latency to AppSync

## Questions?

- Detailed guide: `WEB-CONSOLE-CHAT-FIX-VERIFICATION.md`
- Technical details: `README-WEB-CONSOLE-FIX.md`
- Slack: #papyrus-tech channel
