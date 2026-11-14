# The shared stacks: production and staging, inside the Papyrus production account (PPY-daf673)

The shared tier is the same Papyrus backend deployed once with tenancy mode `shared` (see [multi-tenancy](multi-tenancy.md) and the [design note](plans/multi-tenant-architecture.md), "Isolation inside an existing account"). Ryan decided on 2026-11-13 that it lives in the account that already holds every dedicated site and Prospectus: no new account (D10) and no sandbox account (D9). So two stacks, **shared production** and **shared staging**, sit next to the dedicated sites, and five layers keep them apart. Every release lands on staging first; staging is also the only place the live halves of the auth spike (PPY-d4fe2a) and the CDN spike (PPY-2784d2) can run.

This page is the runbook for the first create and the reference for what the templates build. Nothing on it has been created or deployed: it is templates and tests, checked by synthesis (the feature is [shared-stack-bootstrap.feature](../features_backend/shared-stack-bootstrap.feature)).

## What exists in Git

| Piece | Where |
| --- | --- |
| The foundation stack template: the stack's KMS key, its permissions boundary, its budget | [infra/shared-stack/papyrus-shared-foundation.yaml](../infra/shared-stack/papyrus-shared-foundation.yaml), deployed as `papyrus-shared-staging-foundation` and `papyrus-shared-prod-foundation` |
| The names, the tier plans, the deny | [amplify/shared-stack/names.ts](../amplify/shared-stack/names.ts) |
| The key, boundary, name and concurrency pass over the backend | [amplify/shared-stack/isolation.ts](../amplify/shared-stack/isolation.ts) |
| The numbers (reserved concurrency, alarm thresholds, log retention) | [amplify/shared-stack/settings.ts](../amplify/shared-stack/settings.ts) |
| The alarms | [amplify/shared-stack/alarms.ts](../amplify/shared-stack/alarms.ts) |
| The deny on dedicated roles | [amplify/shared-stack/deny.ts](../amplify/shared-stack/deny.ts) (backend), [infra/amplify-app-shell/lib/shared-stack-deny.ts](../infra/amplify-app-shell/lib/shared-stack-deny.ts) (app shell) |
| The pipeline's shared roles | `SharedPlanRole`, `SharedDeployRole`, `SharedCloudFormationRole` in [papyrus-stack-pipeline.yaml](../infra/pipeline/papyrus-stack-pipeline.yaml) |
| The stack list | the two `group: "shared"` entries in [stacks.json](../infra/pipeline/stacks.json), each with a `hold` |

Tenancy mode `shared` takes a tier: `tenancy: { mode: "shared", tier: "staging" | "production" }` (`sharedStackBackendConfig(tier)` in [define.ts](../amplify/shared-stack/define.ts) is the whole configuration). The shared backend bundles no site's files into content-actions (`setSiteFilesForContentActionsBundle([])`; a publication that names a projector or a static directory is refused), serves no host, and holds no tenant row.

## The five layers as built

1. **Separate stacks, made only by the pipeline.** Production names start with `papyrus-shared-prod`, staging names with `papyrus-shared-staging`. The prefixes do not overlap (the design note's example `papyrus-shared-*` would have matched staging too, which would have let a production-scoped role reach staging). Both are created and changed by `.github/workflows/stack-deploy.yml` through a checked change set, with roles of their own: `papyrus-shared-plan-github` (pull requests, read-only dry run), `papyrus-shared-deploy-github` (pushes to `main`; creates change sets only on stacks named `papyrus-shared-*`, and only with the shared service role attached) and `papyrus-shared-deploy-cloudformation` (the service role). The existing `papyrus-stack-*` roles name no shared stack. A stack with a `hold` in `stacks.json` is planned on every pull request (the job summary headed **HELD**) and never deployed; removing the line, in a reviewed pull request, is the go.
2. **One customer-managed KMS key per stack.** The foundation stack creates it: rotation on, 30-day deletion window (the longest KMS allows), retained when the stack is deleted. The key policy has no account-root statement. Use goes to roles whose ARN matches the stack's own role path (`/papyrus-shared-staging/` or `/papyrus-shared-prod/`, which the backend gives every role it creates) and to the platform operator role `papyrus-platform-operator` (matched by name, so it need not exist yet; until it does, no person can use the key). CloudWatch Logs may encrypt the stack's own function log groups and no others. Administration (no use) goes only to `papyrus-shared-deploy-cloudformation`. The backend reads the key's ARN from the SSM parameter `/papyrus/shared/<staging|prod>/kms-key-arn` at deploy time.
3. **A permissions boundary on every shared role, a deny on every dedicated role.** The foundation stack creates the managed policy `papyrus-shared-<tier>-boundary`; the backend gives it to every role it creates, together with the role path. Every Allow in it is on resources tagged `anthus:deployment=shared-staging` (or `shared-prod`), on resources named with the stack's prefix, or, for the actions AWS gives no resource-level permission, in two statements that name each action (`appsync:GraphQL`, `cloudwatch:PutMetricData`, `xray:Put*`, `sts:GetCallerIdentity`, `logs:DescribeLogGroups`, `kms:ListAliases`). Every dedicated role (the site backend's and the app shell's) gets the inline policy `papyrus-deny-shared-stack`, which denies every action on resources tagged with a shared deployment value or named with the shared prefix, and every KMS action through an alias that starts with the shared prefix. The tag values are fixed by the cost tags (#1327): key `anthus:deployment`, values `shared-prod` and `shared-staging` (with `anthus:account=shared`, `anthus:app=papyrus`); a dedicated site cannot take them, because its site id is its deployment value and the site backend refuses those ids. The per-site deploy roles are not widened.
4. **Reserved concurrency.** Every function the stack owns gets reserved concurrency taken from `settings.ts` (`perFunction`, with `overrides` by construct id); the sum may not pass `tierLimit`, so unreserved headroom stays with the dedicated sites. The staging numbers are a documented starting point and **must be replaced from staging traffic**; the production entry is `null` and the production backend refuses to synthesise until it is set (PPY-f40a02; no arbitrary limits).
5. **Alarms and a budget per stack.** The backend adds alarms named `papyrus-shared-<tier>-...`: per function errors, throttles and concurrency against the reserved share; AppSync 5XX and 4XX (AppSync has no throttle metric: a throttled request is a 429, counted in 4XX); DynamoDB read and write throttles (grouped five tables to an alarm); the projection dead-letter queue; and, as soon as the stack has a distribution, the purge count. They have no action: every alarm in the account reaches the operator through the default-bus listener ([operator alerts](operator-alerts.md)). The foundation stack creates one AWS Budget, filtered on the tag `anthus:deployment` with the stack's own value, alerting the same mailbox `papyrus-monitoring` uses (read from SSM at deploy time, never an address in Git).

## What the key could not be attached to

Everything Amplify Gen 2 and the services allow takes the key: the Amplify model tables (through the table wrapper's `sseSpecification`), every other DynamoDB table, every S3 bucket (SSE-KMS with bucket keys on), every queue, the S3 Vectors bucket and index, and a log group per function (the backend names each function and creates its log group so the key can be set). These could not:

- Amplify secrets (secret("GOOGLE_CLIENT_ID") and the other secret() values): Amplify Gen 2 stores them in SSM under /amplify/<app id>/ with the AWS-managed key and has no hook to choose another key.
- SecureString parameters made by custom resources (plugins that write one, such as newsletter): the shared stack runs no plugin that does; a plugin turned on later must be given the key by its custom resource handler.
- CloudFront KeyValueStore of the projection publication: CloudFront key value stores have no KMS option; the store holds redirects only, no tenant content.
- Cognito user pool: Cognito encrypts with AWS-owned keys and offers no customer-managed key.
- AppSync API: AppSync encrypts at rest with AWS-owned keys and offers no customer-managed key; the data lives in the tables and bucket, which take the key.
- Lambda environment variables and code: the Amplify function constructs expose no KMS key for them; the variables hold names and settings, no secrets.

The list is `RESOURCES_THAT_CANNOT_TAKE_THE_KEY` in `isolation.ts`; a scenario fails if this page stops listing one.

## What is not built yet: how the backend stack itself is created

The foundation stacks fit the release pipeline as it is (a CloudFormation template in Git, a change set, `allowed-changes.json`). The shared **backend** is an Amplify Gen 2 stack: a CDK app of nested stacks with Lambda and asset bundles, which `stack_deploy.py` cannot create today (it deploys single templates, and the service role scoped by names cannot cover generated resource names). So the backend templates are tested by synthesis only, and **how the pipeline creates the backend is an open decision** (see the PR). Until it is decided and built, the first create covers the two foundation stacks and nothing else. The shared service role also deliberately has no rights beyond the foundation stacks.

## Before the first pipeline create of the shared staging stack

Ryan says go to these, in this order. An agent never applies or approves any of them.

1. **Merge the pull request to `develop`.** That runs nothing in AWS.
2. **Update the approver stack once.** The pipeline roles change adds three roles, so the small `papyrus-pipeline-approver` stack's rights over the pipeline roles must name them first (`infra/pipeline/papyrus-pipeline-approver.yaml`). A person applies it: `infra/pipeline/bootstrap.sh --account <12-digit account id> --approver-only`, which shows a change set and asks for `yes`. Without it the next step fails "not authorized".
3. **Approve the pipeline-roles change.** Merging the changed `papyrus-stack-pipeline.yaml` starts `role-stack-deploy`; its `plan` job prints the three new roles (and every statement) in the job summary; the reviewer reads it and clicks **Approve** in the `pipeline-roles` environment. This pull request **needs approval after merge**.
4. **Activate the cost-allocation tags** `anthus:deployment`, `anthus:account` and `anthus:app` in Billing, once (a person; the budget and Cost Explorer lines for the stack read them, and they are not active until someone does this; not verified).
5. **Confirm the numbers.** The staging budget (`MonthlyBudgetUsd` in `stacks.json`, 100 USD to start) and the staging values in `settings.ts` are placeholders to be replaced from measurement, and the account's Lambda concurrency quota must have room for the reservations on top of the dedicated sites (read-only Service Quotas check by a person; no AWS read was made for this work).
6. **Say go to the first create.** A pull request removes the `hold` line from `papyrus-shared-staging-foundation` in `stacks.json` (the pull request's dry run shows the resource list below), is merged, and the next release to `main` creates the stack through the change set the pipeline checks. Production keeps its `hold` until staging has run and the production numbers are set.
7. **Then, and only then,** the live halves of the auth spike (PPY-d4fe2a) and the CDN spike (PPY-2784d2) can be gated on the staging backend. They follow the backend, which waits on the open decision above.

## What the pipeline will create

For each foundation stack (`papyrus-shared-staging-foundation`, later `papyrus-shared-prod-foundation`), five resources and three outputs:

| Logical id | Type | What it is |
| --- | --- | --- |
| `Key` | `AWS::KMS::Key` | The stack's customer-managed key (retained). |
| `KeyAlias` | `AWS::KMS::Alias` | `alias/papyrus-shared-<tier>`. |
| `KeyArnParameter` | `AWS::SSM::Parameter` | `/papyrus/shared/<staging|prod>/kms-key-arn`, read by the backend. |
| `Boundary` | `AWS::IAM::ManagedPolicy` | `papyrus-shared-<tier>-boundary`. |
| `Budget` | `AWS::Budgets::Budget` | `papyrus-shared-<tier>-monthly`, filtered on `anthus:deployment` (retained). |

Outputs: `KeyArn`, `KeyAliasName`, `BoundaryPolicyArn`. The new IAM is the boundary policy and, in the pipeline roles stack, the three `papyrus-shared-*` roles. The backend (the key's consumer, not created by this first step) is about 2,100 resources in its first create with the bootstrap stage on (`PAPYRUS_BOOTSTRAP_STAGE=1`), under CloudFormation's 2,500 limit; a scenario fails past it. The dedicated bootstrap stage stays at 1,970 (`scripts/test-bootstrap-stage.ts`, limit 2,000).

## What changes for the dedicated sites

Only the deny: one inline policy, `papyrus-deny-shared-stack`, on each role. No resource is added or removed in any template (the synth test compares each template with and without it). In the site backend it is on every role except the roles of the per-model data stacks (`data/PapyrusCmsApi/<Model>`): a change that touches every per-model nested stack would pass CloudFormation's 2,500-resource limit on a big site (Papyrus 5.99.0 rolled back that way, `amplify/cost-tag-waves.ts`), and a per-model role can reach only its own table. The deny rides each site's next backend deploy; it needs no other action. The private-chat stack of a site (`PapyrusChatStack`) is not changed: its template is checked against the adopted shared chat runtime, so it follows with that stack's own change.

## Residual risks, plainly

- The key administrator, the CloudFormation service role for the shared stacks, can rewrite the key policy; whoever can approve a pipeline-roles change can change what that role may do. The approval click is the control.
- The boundary and the deny match by tag where the service supports it and by name otherwise; the Amplify-generated tables, Cognito pool and AppSync API are named by Amplify, so for them only the tag (and the key) separates the tiers.
- The key policy does not trust the account root, so the one administrator role is the only way to change it. Do not delete `papyrus-shared-deploy-cloudformation`; if it is lost, only AWS Support can restore access to the key's policy.
- An account-level failure (suspension, quota exhaustion, an operator mistake with administrator credentials) still reaches every tier and Prospectus; the layers do not contain it.
