# Papyrus hosted chat runtime candidate

**Status:** Deployed to account `712236451410`, region `us-east-1`; stack `PapyrusChatDataCandidate` reached `CREATE_COMPLETE` on 2026-10-26 at 04:19 UTC from change set `papyrus-chat-20261026`. The site flag is absent on `main`, and both queue mappings are declared disabled. The existing AppSync send path remains unchanged. The approved transcript policy is no automatic expiry; durable resources are retained and there is no editor deletion flow. This prepares resources only; hosted chat is not yet end-to-end testable.

**Proposed acceptance target:** stack `PapyrusChatDataCandidate`, site `p-apyr-us`, account `712236451410`, region `us-east-1`. The app-shell stack is `amplify-app-shell-p-apyr-us-cms` and its `CmsComputeRoleArn` output is `arn:aws:iam::712236451410:role/amplify-app-shell-p-apyr--AmplifyComputeRoleD988057-tLvmjRYBBw3W`. The candidate stack is separate. The site has no separate staging role; staging is frontend-only and reads the production backend.

## Runtime composition

Papyrus's existing sealed Prospectus session and account authorization remain the HTTP trust boundary. The gateway derives site, account, and editor identity from the verified session and membership checks; browser-provided identity fields are not trusted. It uses the compiled `chatticus/chat-runtime` package to construct Chatticus's existing `DynamoMessagingStore`, `DynamoTurnAdmission`, `DynamoTurnControlStore`, `SqsTurnRunQueue`, `SqsTurnProbeQueue`, channel listing, and S3-backed transcript storage. Private channel creation ensures the configured bot row under the server-derived tenant. The route resolves the runtime only after its explicit feature gate and fails closed when configuration is missing.

The shared package exports computerless run and probe handler factories. The run handler uses Chatticus's actual `consumeRunJob` and existing OpenAI key resolver; the probe handler calls the existing durable turn recovery path. Papyrus has Node 22 Lambda entry points at `infra/shared-chat-runtime/lambda/{run-worker,probe-worker}.ts`. They are included in the candidate template with SQS event source mappings disabled. The runtime resource names are validated from environment configuration; missing required values fail during composition rather than silently selecting another resource.

The run worker is configured to read a dedicated p.apyr.us SSM SecureString at `/papyrus/p-apyr-us/openai-api-key` only when a queued model turn needs it. Read-only metadata checks confirmed that parameter is absent. Its value was not read or copied. The gateway and probe worker have no SSM permission and never receive the key. An operator must configure the parameter securely before enabling model-backed sends.

## Candidate resources and permissions

`infra/shared-chat-runtime/cdk/synth.cjs` defines two separately synthesized stacks. Default `PAPYRUS_CHAT_CANDIDATE_MODE=runtime` writes `PapyrusChatDataCandidate.template.json`; `PAPYRUS_CHAT_CANDIDATE_MODE=synthetic` writes `PapyrusChatSyntheticAdapterTest.template.json`.

The runtime candidate contains:

- Two on-demand DynamoDB tables: messaging/events with TTL only for expiring turn events, and the private `IndexedStorage` table with its required `l1`, `l2`, and `l3` LSIs.
- One private, versioned S3 bucket with public access blocked, TLS enforced, and SSE-S3 encryption.
- Run and probe standard SQS queues, each with a DLQ and SQS-managed encryption.
- Separate Node 22 run and probe Lambda functions and roles. Runtime and optional synthetic bundles are built into separate, cleaned directories. Both queue event source mappings are `Enabled: false`.
- A `GatewayRoleArn` parameter and narrowly scoped gateway policy for a later site integration. The gateway policy does not grant model-secret access. Worker policies scope DynamoDB, S3 object-prefix, SQS, SSM, and log actions to candidate resources. The template validator checks exact gateway/probe conversation-index read actions, gateway transcript read, run-worker secret access, and disabled queue mappings.

Synthetic mode uses a distinct `PapyrusChatSyntheticAdapterTest` stack. It has no `GatewayRoleArn` or CMS-role reference, production gateway, run/probe worker, queue mapping, or SSM/model-secret reference. It creates one Lambda-trusted `SyntheticAdapterGatewayRole` and one manually invoked `SyntheticAdapterTest` Lambda in the same stack. The harness uses the pinned Chatticus runtime with a fixed synthetic principal to create and read a private channel, send/replay a synthetic message, verify the queued run, and round-trip an S3 object under `conversations/synthetic-adapter-tests/*`. It does not invoke the model or delete generated records. There are no API, event, or schedule triggers; invocation is explicit via Lambda Invoke. The queue message is made visible again rather than deleted.

Synthesized allow actions are scoped as follows:

| Principal | Actions | Resource scope |
| --- | --- | --- |
| Runtime gateway role supplied by `GatewayRoleArn` | DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `TransactWriteItems`, `Query`, `BatchGetItem` on messaging; `GetItem`, `Query`, `BatchGetItem` on conversation index; S3 `GetObject`; SQS `SendMessage` | Candidate messaging table; conversation table and its indexes; candidate bucket `conversations/*`; run/probe queues |
| Synthetic harness role | Same DynamoDB actions as the runtime gateway; S3 `GetObject`, `PutObject`; SQS `SendMessage` on run/probe plus `ReceiveMessage`, `ChangeMessageVisibility`, `GetQueueAttributes` on run; log-stream writes | Synthetic stack's tables/indexes, bucket `conversations/synthetic-adapter-tests/*`, candidate queues and harness log group |
| Run worker role | DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query`, `BatchGetItem`, `TransactWriteItems`; S3 `GetObject`, `PutObject`, `DeleteObject`; SQS `ChangeMessageVisibility`, `SendMessage`, and event-source consume actions; SSM `GetParameter`; CloudWatch Logs `CreateLogStream`, `PutLogEvents` | Candidate tables/indexes, bucket `conversations/*`, run/probe queues, exact parameter `/papyrus/p-apyr-us/openai-api-key`, run-worker log group |
| Probe worker role | DynamoDB full listed actions on messaging and read-only `GetItem`, `Query`, `BatchGetItem` on conversation index; S3 `GetObject`; SQS `SendMessage` plus probe event-source consume actions; CloudWatch Logs `CreateLogStream`, `PutLogEvents` | Candidate tables/indexes, bucket `conversations/*`, run/probe queues, probe-worker log group |

In synthetic mode, the harness additionally has S3 `PutObject`/`GetObject` only on `conversations/synthetic-adapter-tests/*`, and SQS `ReceiveMessage`, `ChangeMessageVisibility`, `GetQueueAttributes` only on the run queue. It has no S3 delete or SQS delete action. Runtime SQS source mappings grant their respective worker only the source queue's consume actions (`ReceiveMessage`, `ChangeMessageVisibility`, `GetQueueUrl`, `DeleteMessage`, `GetQueueAttributes`). No worker policy grants access to either DLQ. The synthetic role has no SSM permission; the model parameter permission exists only on the runtime run worker.

The run worker has a 900 second timeout and a 1,800 second queue visibility timeout. The probe worker has a 60 second timeout and 120 second visibility timeout. Runtime queues retain messages for four days; synthetic queues use SQS's 14-day maximum. Table deletion protection and PITR are enabled; durable resources use `RETAIN`, consistent with the approved no-automatic-expiry policy.

Transcript retention is **indefinite by approval**: there is no S3 lifecycle expiration or transcript-table TTL. The messaging table's event TTL is only for transient turn events. There is no editor deletion flow. DynamoDB point-in-time recovery and deletion protection, S3 versioning, and `RETAIN` preserve the approved private history. Do not add automatic expiry without a new decision.

## Review decisions before deployment

1. The user approved transcript retention without automatic expiry. This stack has no editor deletion flow; do not add an expiry policy without a new decision.
2. The user approved the production-target private chat resources; a synthetic stack is not a prerequisite.
3. Review exact IAM actions and resource ARNs in the synthesized template. Only the run worker may read `/papyrus/p-apyr-us/openai-api-key`; the parameter is absent and its value was not read. Do not enable a queue mapping until the SecureString exists.
4. The deployed stack is `CREATE_COMPLETE` at `arn:aws:cloudformation:us-east-1:712236451410:stack/PapyrusChatDataCandidate/26f60110-d0f4-11f1-a5d2-0affe23ffc23`. Its reviewed change set had 24 additions and no modifications, removals, or replacements. It added the two tables, private bucket, four queues, two workers and scoped policies; the CMS role received only `PapyrusChatGatewayRolePolicyD9310960`. No key or site flag was added.
5. The first deployed Lambda asset bundled the optional synthetic adapter file alongside the two runtime handlers because both modes used the same `/tmp` asset directory. Only `run-worker.handler` and `probe-worker.handler` are configured, and both queue mappings remain disabled. The synth script is now fixed to use separate cleaned runtime/synthetic directories; the refreshed runtime asset contains only `run-worker.js` and `probe-worker.js`. A code-only Lambda update change set remains to be applied after the AWS SSO session is refreshed.

## Validation and limits

Local checks completed:

- Chatticus `npm run typecheck --workspace=conversation` passed.
- Chatticus targeted Vitest `conversation/test/site-hosted-runtime.test.ts`: 3 passed. These validate required resource configuration, construction of the real adapter types, and run/probe handler factories without AWS calls.
- Papyrus `npm run typecheck` passed in a writable task-local dependency install using the compiled Chatticus package artifact.
- Papyrus `npm run test:papyrus-hosted-chat` passed, including the default-off route and the real runtime adapter configuration assertions.
- Papyrus `npm run test:papyrus-chat-worker` passed: private channel creation, hosted send, actual shared worker reply, refresh/replay, and foreign-editor denial.
- CDK synthesis with Papyrus's exact lockfile versions and `infra/shared-chat-runtime/cdk/validate-template.cjs` passed for both runtime and synthetic modes. The synthetic stack was not deployed. Read-only AWS checks confirmed the target account, site flag absent, and model parameter absent. The reviewed runtime template passed resource/IAM checks before deployment; CloudFormation completed the approved resource setup. No credential or secret value was created or read. The SSO session expired during post-deployment verification; only the run-worker mapping was independently read back as `Disabled`. The change-set template marks both mappings disabled.

The local adapter tests do not contact DynamoDB, S3, SQS, SSM, or Lambda. The optional synthetic template is not part of the approved rollout and is not a prerequisite. Real-cloud adapter behavior and end-to-end editor isolation remain unverified. The production gateway route and model-backed turn flow are not live: the site has no private-chat flag, the model key is absent, and the source branch has not been released to the site. The run mapping was verified `Disabled`; the probe mapping is declared `Enabled: false` in the executed template but its live state could not be independently queried after the SSO session expired.

## Cost and rollback notes

The candidate has no provisioned database capacity, load balancer, or always-on queue poller. DynamoDB on-demand requests/PITR, Lambda invocations and duration, SQS requests, S3 storage/requests, and model tokens vary with workload; there is no fixed monthly maximum in the current implementation. Pricing references: [DynamoDB](https://aws.amazon.com/dynamodb/pricing/), [SQS](https://aws.amazon.com/sqs/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [S3](https://aws.amazon.com/s3/pricing/).

Before new writes, rollback can disable the Papyrus feature gate and leave the existing AppSync path in place. After private chat writes begin, freeze admissions and export/reconcile those transcripts before any reversal; do not dual-write or run both model engines for one prompt. Queue mappings are disabled in the candidate, so they require a separate deliberate enablement after the site-specific deployment review.
