# Papyrus Console Chat Runbook

The Papyrus Console is the editor-only chat surface exposed on `/newsroom`.
It is intentionally built on Papyrus newsroom primitives rather than a separate
chat silo:

- `MessageThread` is the navigable conversation container.
- `Message` rows are the durable turns, tool records, and generated insight
  artifacts.
- raw chat turns use `messageKind = "console_chat_turn"`,
  `messageDomain = "conversation"`, `semanticLayer = "chat_detail"`, and
  `searchVisibility = "explicit"` so they can be excluded from default
  semantic search.
- synthesized durable insights should be separate `Message` rows with
  `messageKind = "insight"` and default-search visibility.

## Runtime flow

1. The Newsroom top bar renders the console icon only for signed-in
   `editor`/`admin` users on `/newsroom` routes.
2. The client creates or reuses a `MessageThread` anchored to
   `primaryAnchorKey = "site#papyrus"`.
3. The client writes a user `Message` with `responseStatus = "PENDING"` and
   `responseTarget = "cloud"`.
4. The DynamoDB stream on the `Message` table invokes the Rust responder
   Lambda.
5. The responder claims the message (`PENDING` -> `RUNNING`), locks the thread,
   loads prompt context from `/tmp/papyrus-console/thread-context` when
   possible, falls back to querying the `messagesByThreadSequence` GSI, calls
   OpenAI, writes assistant/tool `Message` rows, updates the `/tmp` cache, and
   marks the trigger message `COMPLETED` or `FAILED`.

The `/tmp` context cache is opportunistic only. Cold starts and stale caches
must transparently rebuild from DynamoDB or fall back to the triggering message.

## Required AWS configuration

The Rust image is a custom Lambda runtime, so do not rely on Amplify Gen 2
`secret(...)` injection for the OpenAI key. The Lambda expects either:

- `OPENAI_API_KEY`, or
- `PAPYRUS_CONSOLE_OPENAI_API_KEY_SSM_PARAM` pointing to an SSM SecureString.

Production currently uses:

```bash
/amplify/papyrus/ryan-sandbox-adcd88a186/OPENAI_API_KEY
```

Set or verify the Lambda environment:

```bash
AWS_PROFILE=Ryan AWS_REGION=us-east-1 \
aws lambda get-function-configuration \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --query 'Environment.Variables'
```

The responder role also needs `dynamodb:Query` on table index ARNs for the
`Message` and `MessageThread` tables. The CDK stack grants this explicitly;
do not remove the `/index/*` permissions when editing
`amplify/functions/console-chat-responder/resource.ts`.

## Build and update the Rust Lambda image

Use Docker Buildx. A normal `docker build && docker push` can create an OCI
manifest that Lambda rejects with:

```text
The image manifest, config or layer media type ... is not supported.
```

Build with provenance and SBOM disabled:

```bash
export AWS_PROFILE=Ryan
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=335163751677
export RESPONDER_REPO="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/cdk-hnb659fds-container-assets-$AWS_ACCOUNT_ID-$AWS_REGION"
export RESPONDER_TAG="papyrus-console-responder-$(git rev-parse --short HEAD)-lambda-arm64"
export RESPONDER_IMAGE="$RESPONDER_REPO:$RESPONDER_TAG"

aws ecr get-login-password \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker buildx build \
  --platform linux/arm64 \
  --provenance=false \
  --sbom=false \
  -f amplify/functions/console-chat-responder/Dockerfile \
  -t "$RESPONDER_IMAGE" \
  --push .
```

Update the Lambda to the new image:

```bash
aws lambda update-function-code \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --image-uri "$RESPONDER_IMAGE"

aws lambda wait function-updated \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D

aws lambda get-function \
  --function-name amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --query '{ImageUri:Code.ImageUri,LastModified:Configuration.LastModified}'
```

## Smoke test

The preferred smoke test is to send a fresh message from the `/newsroom`
console, then watch Lambda logs:

```bash
AWS_PROFILE=Ryan AWS_REGION=us-east-1 \
aws logs tail /aws/lambda/amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D \
  --since 10m \
  --format short
```

Successful logs include:

```text
processing console chat message
rebuilt prompt context from DynamoDB
console chat message completed
```

You can also verify that an assistant message was created by querying the
thread sequence GSI:

```bash
AWS_PROFILE=Ryan AWS_REGION=us-east-1 \
aws dynamodb query \
  --table-name Message-s4sclnevjjbzpmj4vhallzvw3e-NONE \
  --index-name messagesByThreadSequence \
  --key-condition-expression 'threadId = :threadId' \
  --expression-attribute-values '{":threadId":{"S":"<thread-id>"}}' \
  --expression-attribute-names '{"#r":"role"}' \
  --projection-expression 'id,#r,messageKind,content,responseStatus,responseError,sequenceNumber,createdAt' \
  --scan-index-forward
```

If an existing failed `PENDING`/`FAILED` message needs to be replayed manually,
reset it and invoke the Lambda with a stream-shaped payload. Prefer a fresh UI
message unless you are debugging a specific old row.

```bash
export MESSAGE_TABLE=Message-s4sclnevjjbzpmj4vhallzvw3e-NONE
export MESSAGE_ID=<message-id>
export RESPONDER_FUNCTION=amplify-dbsyytcm9drqa-mai-ConsoleChatResponderFunc-PnFuItfGGO4D

aws dynamodb update-item \
  --table-name "$MESSAGE_TABLE" \
  --key "{\"id\":{\"S\":\"$MESSAGE_ID\"}}" \
  --update-expression 'SET responseStatus = :pending, updatedAt = :now REMOVE responseError, responseStartedAt, responseCompletedAt, responseOwner' \
  --expression-attribute-values '{":pending":{"S":"PENDING"},":now":{"S":"2026-05-23T22:10:00.000Z"}}'

PAYLOAD=$(aws dynamodb get-item \
  --table-name "$MESSAGE_TABLE" \
  --key "{\"id\":{\"S\":\"$MESSAGE_ID\"}}" \
  --output json \
  | jq -c '{Records:[{eventName:"INSERT",eventID:"manual-smoke",dynamodb:{SequenceNumber:"manual-smoke",NewImage:.Item}}]}')

aws lambda invoke \
  --function-name "$RESPONDER_FUNCTION" \
  --cli-binary-format raw-in-base64-out \
  --payload "$PAYLOAD" \
  /tmp/papyrus-console-smoke-response.json

cat /tmp/papyrus-console-smoke-response.json
```

Expected Lambda response for a successful manual smoke:

```json
{"batchItemFailures":[],"processed":1,"skipped":0}
```

## Web UI location context (`console.webUi`)

Each user console turn should persist `metadata.console.webUi` from the Newsroom
route (path + query) so the Rust responder can inject the current page into the
system prompt and pass the same snapshot to `execute_tactus` / `papyrus.web.*`.

Verify a fresh user message in DynamoDB:

```bash
AWS_PROFILE=Ryan AWS_REGION=us-east-1 \
aws dynamodb query \
  --table-name Message-s4sclnevjjbzpmj4vhallzvw3e-NONE \
  --index-name messagesByMessageKindAndCreatedAt \
  --key-condition-expression 'messageKind = :kind' \
  --expression-attribute-values '{":kind":{"S":"console_chat_turn"}}' \
  --no-scan-index-forward \
  --limit 3
```

A healthy row includes `metadata.console.webUi.webPath` and
`metadata.console.webUi.papyrusLocationUri`. If you only see
`metadata.console.author` and the assistant says it cannot see the current
page, production is still running an older frontend bundle. Check the latest
Amplify `main` build: failed backend deploys skip the Next.js phase entirely.

## Troubleshooting

- `OPENAI_API_KEY or PAPYRUS_CONSOLE_OPENAI_API_KEY_SSM_PARAM is required`:
  configure the SSM parameter path on the Lambda environment.
- `query Message tail by threadId/sequenceNumber`: verify the role can
  `dynamodb:Query` the `messagesByThreadSequence` index ARN.
- `builder error: failed to parse header value`: verify the deployed image
  includes trimming for the OpenAI key and rebuild/push the Lambda image.
- repeated `missing DynamoDB stream string field threadId`: the stream is
  delivering non-console `Message` rows. The responder should skip these before
  requiring `threadId`; rebuild/push the image if that skip logic is not live.
- `CloudformationStackCircularDependencyError` involving
  `consolechatresponder`, `storage`, `storagebackups`, and `data`: keep the
  console responder nested stack on the data stack (`Stack.of(messageTable)`)
  and storage backups on the storage stack (`Stack.of(storageBucket)`), then
  rerun the Amplify `main` pipeline.
- Assistant cannot answer “what page are we on?” while `console.author` exists
  but `console.webUi` is missing: redeploy the frontend from a green Amplify
  `main` build; the responder is already running but never received location
  metadata on the trigger message.
- **`Could not resolve JWT signing secret`** when using Papyrus tools
  (`papyrus.reference.*`, `papyrus.knowledge.*`, etc.): the console-chat-responder
  Lambda role needs **both** `ssm:GetParameter` and `ssm:GetParameters` permissions
  on the Amplify SSM parameter paths. The `execute_tactus_runner.py` subprocess
  uses boto3's `get_parameters` (plural) API to fetch `PAPYRUS_JWT_SECRET` from
  SSM. **Fix**: PR #23 (commit `0c39cbb`) added the missing `ssm:GetParameters`
  permission to `amplify/functions/console-chat-responder/resource.ts`. Verify
  the Lambda's IAM role includes this action, or redeploy from the latest `main`
  to pick up the updated CDK stack. See `docs/web-console-chat-iam-fix.md` for
  verification steps.
