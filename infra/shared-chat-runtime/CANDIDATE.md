# Papyrus hosted chat runtime candidate

**Status:** Locally implemented and synthesized for review. Nothing has been deployed or applied. Papyrus private chat remains disabled by default (`PAPYRUS_PRIVATE_CHAT_ENABLED=false`). The existing AppSync send path is unchanged. Transcript retention is intentionally unset pending an approved policy and deletion flow.

**Proposed acceptance target:** stack `PapyrusChatDataCandidate`, site `p-apyr-us`, account `712236451410`, region `us-east-1`. The read-only site config at `/Users/home/Projects/p.apyr.us-cut2/infra/site.json` contains the Prospectus API ARN in that account and region; its `stackName` is `amplify-app-shell-p-apyr-us-cms` (the existing CMS stack). The candidate stack name is separate. The site config has no separate staging role ARN. Papyrus app-shell code provisions one CMS `WEB_COMPUTE` role and exposes `CmsComputeRoleArn`; staging is documented as frontend-only and reads the production backend. Current deployed role state was not queried.

## Runtime composition

Papyrus's existing sealed Prospectus session and account authorization remain the HTTP trust boundary. The gateway derives site, account, and editor identity from the verified session and membership checks; browser-provided identity fields are not trusted. It uses the compiled `chatticus/chat-runtime` package to construct Chatticus's existing `DynamoMessagingStore`, `DynamoTurnAdmission`, `DynamoTurnControlStore`, `SqsTurnRunQueue`, `SqsTurnProbeQueue`, channel listing, and S3-backed transcript storage. Private channel creation ensures the configured bot row under the server-derived tenant. The route resolves the runtime only after its explicit feature gate and fails closed when configuration is missing.

The shared package exports computerless run and probe handler factories. The run handler uses Chatticus's actual `consumeRunJob` and existing OpenAI key resolver; the probe handler calls the existing durable turn recovery path. Papyrus has Node 22 Lambda entry points at `infra/shared-chat-runtime/lambda/{run-worker,probe-worker}.ts`. They are included in the candidate template with SQS event source mappings disabled. The runtime resource names are validated from environment configuration; missing required values fail during composition rather than silently selecting another resource.

The worker reads the existing per-app Amplify secret through SSM parameter `/amplify/shared/papyrus/OPENAI_API_KEY` only when a queued model turn needs it. The secret value was not read or copied. The gateway has no SSM permission and never receives the key. If the site's supported secret wiring does not expose that existing parameter to the worker, model-backed sends must remain off until it does.

## Candidate resources and permissions

`infra/shared-chat-runtime/cdk/synth.cjs` defines the local CDK candidate and `infra/shared-chat-runtime/cdk/PapyrusChatDataCandidate.template.json` is its synthesized output. It contains:

- Two on-demand DynamoDB tables: messaging/events with TTL only for expiring turn events, and the private `IndexedStorage` table with its required `l1`, `l2`, and `l3` LSIs.
- One private, versioned S3 bucket with public access blocked, TLS enforced, and SSE-S3 encryption.
- Run and probe standard SQS queues, each with a DLQ and SQS-managed encryption.
- Separate Node 22 run and probe Lambda functions and roles. Both queue event source mappings are `Enabled: false`.
- A `GatewayRoleArn` parameter and narrowly scoped gateway policy. This can target a dedicated disposable synthetic-test harness role instead of the production CMS role. The gateway policy does not grant model-secret access. Worker policies scope DynamoDB, S3 object-prefix, SQS, SSM, and log actions to candidate resources. The template validator checks exact gateway/probe conversation-index read actions, gateway transcript read, run-worker secret access, and disabled queue mappings.

Synthesized allow actions are scoped as follows:

| Principal | Actions | Resource scope |
| --- | --- | --- |
| Gateway role supplied by `GatewayRoleArn` | DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `TransactWriteItems`, `Query`, `BatchGetItem` on messaging; `GetItem`, `Query`, `BatchGetItem` on conversation index; S3 `GetObject`; SQS `SendMessage` | Candidate messaging table; conversation table and its indexes; candidate bucket `conversations/*`; run/probe queues |
| Run worker role | DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query`, `BatchGetItem`, `TransactWriteItems`; S3 `GetObject`, `PutObject`, `DeleteObject`; SQS `ChangeMessageVisibility`, `SendMessage`, and event-source consume actions; SSM `GetParameter`; CloudWatch Logs `CreateLogStream`, `PutLogEvents` | Candidate tables/indexes, bucket `conversations/*`, run/probe queues, exact parameter `amplify/shared/papyrus/OPENAI_API_KEY`, run-worker log group |
| Probe worker role | DynamoDB full listed actions on messaging and read-only `GetItem`, `Query`, `BatchGetItem` on conversation index; S3 `GetObject`; SQS `SendMessage` plus probe event-source consume actions; CloudWatch Logs `CreateLogStream`, `PutLogEvents` | Candidate tables/indexes, bucket `conversations/*`, run/probe queues, probe-worker log group |

The SQS source mappings grant their respective worker only the source queue's consume actions (`ReceiveMessage`, `ChangeMessageVisibility`, `GetQueueUrl`, `DeleteMessage`, `GetQueueAttributes`). No worker policy grants access to either DLQ. The harness gateway role has no SSM permission; the model parameter permission exists only on the run worker.

The run worker has a 900 second timeout and a 1,800 second queue visibility timeout. The probe worker has a 60 second timeout and 120 second visibility timeout. Table deletion protection and PITR are enabled; durable resources use `RETAIN`. These are candidate safeguards and need to be weighed against the final retention/deletion policy before deployment.

Retention is **not configured for transcripts**: no S3 lifecycle expiration and no transcript-table TTL are set. The messaging table's event TTL is only for transient turn events. Before enabling private history in a real site, approve a transcript retention period and implement/test editor deletion across indexed records and S3 objects. Do not infer indefinite retention from the IaC `RETAIN` removal policy.

## Review decisions before deployment

1. Approve transcript retention and deletion behavior before enabling history writes. The candidate intentionally leaves transcript expiry unset.
2. For initial cloud adapter validation, approve a disposable harness role passed through `GatewayRoleArn`, with no trust or permission relationship to the production CMS role and no model-secret access. This avoids attaching the gateway policy to the production CMS role.
3. Review exact IAM actions and resource ARNs in the synthesized template. The worker secret reference is `/amplify/shared/papyrus/OPENAI_API_KEY`; its value was not read.
4. Decide whether PITR, deletion protection, S3 versioning, and `RETAIN` fit the synthetic-data cleanup plan.
5. Approve any separate non-production deployment and AWS acceptance run. This task made no AWS API calls, grants, or writes.

## Validation and limits

Local checks completed:

- Chatticus `npm run typecheck --workspace=conversation` passed.
- Chatticus targeted Vitest `conversation/test/site-hosted-runtime.test.ts`: 3 passed. These validate required resource configuration, construction of the real adapter types, and run/probe handler factories without AWS calls.
- Papyrus `npm run typecheck` passed in a writable task-local dependency install using the compiled Chatticus package artifact.
- Papyrus `npm run test:papyrus-hosted-chat` passed, including the default-off route and the real runtime adapter configuration assertions.
- Papyrus `npm run test:papyrus-chat-worker` passed: private channel creation, hosted send, actual shared worker reply, refresh/replay, and foreign-editor denial.
- CDK synthesis and `infra/shared-chat-runtime/cdk/validate-template.cjs` passed. The candidate uses Papyrus's declared CDK version. No AWS CLI/API calls, live model calls, deployments, merges, or PR operations were performed.

The adapter tests check the actual production adapter configuration and generated IAM/resource references, but they do not contact DynamoDB, S3, SQS, SSM, or Lambda. A synthetic cloud test can use a dedicated harness role and synthetic records while leaving the gateway gate and queue mappings off; the test must not invoke the model worker. Retention does not block local or adapter-only synthetic tests, but deployment cleanup must be approved because tables/bucket are retained and the bucket is versioned. Real-cloud behavior, secret resolution, queue retry/DLQ configuration, and IAM sufficiency still require a separately approved non-production deployment and acceptance test. No claim is made that the candidate is production-ready before those checks and the retention decision.

## Cost and rollback notes

The candidate has no provisioned database capacity, load balancer, or always-on queue poller. DynamoDB on-demand requests/PITR, Lambda invocations and duration, SQS requests, S3 storage/requests, and model tokens vary with workload; there is no defensible fixed monthly maximum without request, token, and retention limits. Set budgets and per-editor turn/token limits before a model-enabled pilot. Pricing references: [DynamoDB](https://aws.amazon.com/dynamodb/pricing/), [SQS](https://aws.amazon.com/sqs/pricing/), [Lambda](https://aws.amazon.com/lambda/pricing/), [S3](https://aws.amazon.com/s3/pricing/).

Before new writes, rollback can disable the Papyrus feature gate and leave the existing AppSync path in place. After private chat writes begin, freeze admissions and export/reconcile those transcripts before any reversal; do not dual-write or run both model engines for one prompt. Queue mappings are disabled in the candidate, so they require a separate deliberate enablement after the site-specific deployment review.
