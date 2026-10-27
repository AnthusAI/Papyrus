# Private newsroom chat, per site

Every Papyrus site can run a private newsroom chat: an authorized editor signs in once, opens Chat in the newsroom
and talks to the site's assistant (the computerless Chatticus profile, `gpt-6-luna`). History is private to
issuer and subject and never crosses sites. Whether a site has chat is configuration, not code: the same Papyrus
package serves the route and the panel everywhere, and they stay off until the site's CMS has the chat environment.

## The `chat` block

In the site's `infra/site.json` (examples in `infra/amplify-app-shell/examples/`):

```json
"chat": {
  "enabled": true,
  "modelKeyParameter": "/papyrus/shipped/openai-api-key"
}
```

| Field | Meaning |
| --- | --- |
| `enabled` | `true` provisions the site's chat data stack and turns chat on. `false` or no block: no stack, no chat environment; the route answers 404 and the panel is not shown. Requires `cms`. |
| `modelKeyParameter` | SSM SecureString holding the site's OpenAI key. Reuse the site's existing parameter: Shipped, Anth.us and Pilobol.us `/papyrus/shipped/openai-api-key`; p.apyr.us `/papyrus/p-apyr-us/openai-api-key`; Threat Intelligence, Distinctive and Data Parade their Amplify shared `/amplify/shared/<app id>/OPENAI_API_KEY`. Only the run worker may read it; the model is the Chatticus default (`gpt-6-luna`). |
| `stackName` | Optional. Default `papyrus-chat-<siteId>`. Only p.apyr.us overrides it (`PapyrusChatDataCandidate`, the activated stack). |
| `logGroupPrefix` | Optional. Default `/aws/lambda/papyrus-chat-<siteId>`; worker log groups are `<prefix>-run-worker` and `<prefix>-probe-worker`. Log group names are account-global, so sites in one account never share a prefix. |
| `workerCodeS3Key` | Optional pin of the worker code to an already uploaded CDK asset (`<sha256>.zip`). Only for adopting a stack whose worker bytes are verified live; nothing is bundled or uploaded. |

With `chat.enabled`, `cms.environment` must not set `PAPYRUS_PRIVATE_CHAT_ENABLED` or any `PAPYRUS_CHAT_*`
variable (validation fails). A site without the block keeps the old hand-managed flag behaviour.

## What each part generates

- **Chat data stack** (`infra/amplify-app-shell/lib/chat-stack.ts`, `papyrus-infra synth --part chat`, or
  `cdk -c part=chat`): two on-demand DynamoDB tables, one private versioned S3 bucket, run and probe queues with
  DLQs, the run and probe worker Lambdas with enabled queue mappings, their scoped roles, log groups, and the
  scoped gateway policy attached to the site's CMS compute role (`GatewayRoleArn`). Tables, bucket and log groups
  are retained; there is no expiry and no deletion flow. Every resource name is derived from the stack name, so
  two sites never share storage.
- **App shell** (`AmplifyAppShellStack`): on the `main` CMS branch only, `PAPYRUS_PRIVATE_CHAT_ENABLED=true`,
  `PAPYRUS_CHAT_{MESSAGING_TABLE,CONVERSATIONS_TABLE,SESSION_BUCKET,TURN_RUNS_QUEUE_URL,TURN_PROBES_QUEUE_URL}`
  imported from the chat stack's exports, and the assistant id and name. The staging branch is always
  `PAPYRUS_PRIVATE_CHAT_ENABLED=false`: staging reads the production backend and never gets chat storage.
- **Identity isolation** is unchanged: the editor's chat tenant and principal are derived on the server from the
  site's own bucket and table, the app client, the Cognito issuer and the subject
  (`lib/papyrus-hosted-chat.ts`), so a different site, issuer or subject can never read a channel.

Specs: `infra/amplify-app-shell/features/per-site-private-chat.feature`, run by `npm run test:infra-chat`.

## Enabling chat on a site

Order matters: the app shell imports the chat stack's exports, so the chat stack comes first, and the frontend
comes last. Use the AWS profile of the site's account (`aws.profile`; all current sites are in
`papyrus-production`, 712236451410).

1. **Prerequisites.** The site's `papyrusVersion` is at least 5.43.0 (the release that carries the route, the
   newsroom identity fix and the panel), its `infra/site.json` has an `aws` block and the current schema, and the
   `modelKeyParameter` exists (read-only check: `aws ssm describe-parameters --parameter-filters Key=Name,Option=Equals,Values=<name>`).
2. **Chat data stack**, from a Papyrus checkout at the release tag (after `npm ci` there and in
   `infra/amplify-app-shell`):

   ```sh
   SITE=/path/to/site-repo/infra/site.json          # with the chat block
   node scripts/bundle-chat-lambdas.mjs --out /tmp/papyrus-chat-lambdas
   ROLE=$(aws cloudformation describe-stacks --stack-name amplify-app-shell-<siteId>-cms \
     --query "Stacks[0].Outputs[?OutputKey=='CmsComputeRoleArn'].OutputValue" --output text)
   cd infra/amplify-app-shell
   npx cdk diff   -c site=$SITE -c part=chat -c chatLambdas=/tmp/papyrus-chat-lambdas papyrus-chat-<siteId>
   npx cdk deploy -c site=$SITE -c part=chat -c chatLambdas=/tmp/papyrus-chat-lambdas papyrus-chat-<siteId> \
     --parameters papyrus-chat-<siteId>:GatewayRoleArn=$ROLE
   ```

   The first deploy of a new site creates the data plane (tables, bucket, queues, workers, roles, log groups) and adds exactly one inline policy to the CMS compute
   role. Review the change set in the console or `cdk diff` before deploying; no other resource may change.
3. **App shell** (adds the flag and names to the CMS production branch): `npx cdk deploy -c site=$SITE`
   (or `papyrus-infra deploy`). Branch variables are replaced as a set, so the site's `infra/site.json` must be the
   one with the `chat` block before any app-shell deploy.
4. **Frontend.** Merge the site repository's `infra/site.json` (the `chat` block and any `papyrusVersion` bump)
   to `main`; the merge deploys the CMS. Open the newsroom, sign in, open Chat, send one clearly labelled test
   message and confirm a reply and that it survives a reload.

To turn chat off again set `chat.enabled` to `false` and redeploy the app shell. The data stack and its retained
storage are left in place on purpose; re-enabling reuses them. Deleting history needs a new decision.

## p.apyr.us: adopting the activated stack

p.apyr.us already runs the stack `PapyrusChatDataCandidate` (activated by hand, with the branch variables set
outside CloudFormation). Its example config names that stack, its log group prefix and its verified worker code
key, and the generalized definition then produces the same template:

- Every resource has byte-identical properties to the live stack's template (`aws cloudformation get-template`,
  compared with metadata ignored): no table, bucket, queue, role, log group, function or event source mapping is
  added, removed, renamed or replaced, the queue mappings stay `Enabled`, and the worker code key is unchanged.
- The only template differences are: the stack description, the descriptions of three parameters, defaults for the
  assistant id and name parameters (their live values are the defaults), `Export` names on five outputs, and the
  `FeatureDefault` output text. All are in-place changes without resource updates.
- Deploy it with the same commands as step 2 (`cdk deploy ... PapyrusChatDataCandidate`; no `chatLambdas`, the code
  is pinned; the existing `GatewayRoleArn` is kept).
- Then the app shell for p.apyr.us (step 3) takes over the branch variables that are set by hand today. Until
  that deploy, an app-shell deploy from a site.json without the `chat` block would reset them, so merge the block first.
- Never deploy `infra/shared-chat-runtime/cdk/PapyrusChatDataCandidate.template.json` (the review candidate) over
  the stack: it predates the activation. It stays as the record the parity test compares against.

`infra/shared-chat-runtime/cdk/synth.cjs` is kept for the synthetic adapter test only; the runtime stack is now
defined in `chat-stack.ts`, and `scripts/test-infra-chat.ts` fails if the two diverge on p.apyr.us.
