# Monitoring in the cloud (HN collector)

PPY-3212f1, step 1: the Hacker News collector runs on a schedule in AWS instead of
on an operator's machine. It is a dedicated stack, `papyrus-monitoring`, not part
of any site backend: the monitor is shared by several publications, no one site
owns it, and an Amplify backend deploy would tie HN collection to one site's
pipeline. Like the edge stacks (`infra/edge/README.md`) it is a hand-run
CloudFormation stack in account 712236451410, us-east-1, applied with a change set.

## What it does, and does not do

The **collector** collects, dedupes, checkpoints and records receipts. It holds no
provider keys, no outbound credentials and no AppSync access, and it writes nothing
to any publication. Each discovery sits in the table with `routing: collected`.

The **router** (step 4, below) is a second Lambda in the same stack. It asks the
shared Cyclotron which collected items each publication wants and delivers only the
ones its relevance output labels `include` into that publication's References queue
as `pending`, so unscreened HN items never flood a queue.

## Pieces

| Resource | Notes |
| --- | --- |
| DynamoDB table (auto-named) | On-demand, encrypted, point-in-time recovery, `Retain` on delete and replace |
| Lambda `papyrus-monitoring-collector` | Python 3.13, arm64, 256 MB, 120 s, reserved concurrency 1 when the account quota allows (parameter `ReservedConcurrency`; 0 leaves it unreserved), logs kept 30 days |
| Schedule `papyrus-monitoring-hn-collect` | EventBridge Scheduler `rate(15 minutes)`, no flexible window, 3 retries, SQS dead-letter queue |
| Alarm `papyrus-monitoring-collector-errors` | Lambda `Errors` >= 1 in 15 minutes (no notification action yet) |
| Roles | Collector: this table and its own log group only. Schedule: invoke this function, send to its DLQ |

Code: `src/papyrus_content/monitoring_cloud.py` (stdlib and boto3 plus the existing
`monitoring.py` feed parser, fingerprint and 2 MB / 100 item bounds). The local SQLite
collector is unchanged. Build and upload with `infra/monitoring/build.py` (a
deterministic zip named by its SHA256 under `papyrus-monitoring/` in the CDK assets
bucket).

## Table layout

Keys are `pk` and `sk`; every item of the HN monitor has `pk = MONITOR#hn`.

| `sk` | Meaning |
| --- | --- |
| `CONFIG` | Config as data: `sourceUrl` (an https news.ycombinator.com feed), `intervalSeconds` (>= 60), `limit` (1 to 100), `enabled`. Seeded by `infra/monitoring/seed_config.py`, edited in the table, never in Lambda environment |
| `STATE` | Checkpoint: `nextDueAt` (epoch seconds), `lastRunId`, `lastStatus` |
| `LOCK` | Lease: `owner`, `expiresAt`. Taken by conditional write when absent or expired, released only by its owner. Lease is 150 s, longer than the timeout, so a crashed run cannot block longer than that |
| `ITEM#<sourceId>` | Current `fingerprint` and `revision` for an HN item (the dedupe record) |
| `DISC#<sourceId>#<revision, 6 digits>` | One discovery per revision: title, canonical and HN item URLs, source time, fingerprint, `eventId`, `observedAt`, `runId`, `routing` |
| `RUN#<startedAt>#<runId>` | Receipt: status, `new`, `revised`, `unchanged`, `itemCount`, `errorCount`, first errors, `nextDueAt`; expires after 30 days (`ttl`) |

Dedupe has the same semantics as the local collector: an unchanged fingerprint is
skipped, a changed one writes revision + 1, and `eventId` is the same digest. Each
item is committed on its own (discovery first, then the current-item record), so a
later failure never erases earlier progress and a crash between the two writes is
repaired by the next run. The schedule fires every 15 minutes; a run inside the
interval (less a 60 s jitter allowance) returns `not_due` and writes no receipt.

Sparse GSI `routing` (`gsi1pk = ROUTING#hn#collected`, `gsi1sk = <observedAt>#...`)
lists discoveries still waiting for the router. The router should set `routing` to
its next status and remove `gsi1pk` and `gsi1sk`.

## Reading it

Account 712236451410, `AWS_PROFILE=papyrus-production`, region us-east-1. Latest receipts:

```sh
aws dynamodb query --table-name "$TABLE" --key-condition-expression 'pk = :p AND begins_with(sk, :r)' \
  --expression-attribute-values '{":p":{"S":"MONITOR#hn"},":r":{"S":"RUN#"}}' --scan-index-forward false --limit 3
aws logs tail /aws/lambda/papyrus-monitoring-collector --since 1h
```

Table, function and schedule names are the stack outputs.

## Operating and rolling back

- Pause: set `enabled` to false in the `CONFIG` item, or update the stack with `ScheduleState=DISABLED`.
- Debug run: invoke the function with `{"force": true}`; the schedule never does.
- Roll back code: build an earlier commit, upload, and update the stack with that `CodeKey`.
- Remove: delete the stack. The table is retained with its data; delete it separately.
- Deploy with a change set and read it first (`create-change-set`, `describe-change-set`, then execute).

## Concurrency note

Serial runs are guaranteed by the table lease, not only by reserved concurrency.
The papyrus-production account's Lambda concurrency quota is 10, and Lambda requires
10 to stay unreserved, so no function there can reserve any. The first deploy ran with
`ReservedConcurrency=0`. After a quota increase, update the stack with the default (1).


# The router (step 4)

`papyrus-monitoring-router` (same stack, same table, separate role and zip) turns
`collected` discoveries into pending References. Everything it needs is data in the
`CONFIG#router` item; the Lambda hard-codes no endpoint, account, run, binding or
publication. It runs on its own schedule `cron(7/15 * * * ? *)` (minutes 7, 22, 37,
52), offset from the collector's `rate(15 minutes)`. Independent schedules keep the
failure domains apart (a Cyclotron outage never touches collection, and collector
code is not redeployed with the router); the cost is up to 15 minutes of latency.
Feedback runs in the same invocation after routing (one lock, one schedule); a
failed feedback pass never fails routing, and `{"task":"route"}` or `{"task":"feedback"}`
limits an operator-invoked run.

## Dry-run and live

`mode: dry-run` makes **no** Cyclotron call and writes nothing to any publication.
For each of up to `maxItemsPerRun` discoveries (oldest first) it builds the exact
`decide` body for every configured publication, validates it structurally (contract
version, operation, `requestId` 8 to 128 characters, payload shape, item values,
32 KiB bound), reads each publication's editorial context hash through the existing
`editorial_context` code (read-only; `contextHash: null` plus the reason when the
publication stores no policy, never a failure) and records a receipt.

`mode: live` performs one `decide` per binding per item (the bindings share one
native decision, which is checked), polls only, records the decision receipt and
delivers.

`requestId` is `sha256(accountId \n runId \n publicationId@bindingRevision \n itemId \n fingerprint)`.
It is identical in dry-run and live, so flipping to live cannot duplicate a decision.

## `routing` state machine

| `routing` | GSI partition | Meaning |
| --- | --- | --- |
| `collected` | `ROUTING#hn#collected` | Written by the collector; waiting |
| `dry-run-validated` | `ROUTING#hn#dry-run-validated` | Dry-run receipt written; live mode treats it exactly like `collected` |
| `decided` | `ROUTING#hn#decided` | Decision recorded; at least one positive publication is not yet delivered (retried with backoff: 5 min doubling to 6 h) |
| `routed` | none | Final: every positive publication delivered (or every output said `exclude`) |
| `refused` | none | Final: `source_refused` from Cyclotron |
| `uncertain` | none | Final: a `decide` POST got no usable answer. A POST is never repeated; reconcile by hand (below) |
| `error` | none | Final: invalid request or response, divergent decisions, or a job pending over 6 h |

Live mode reads `decided` first, then `collected` and `dry-run-validated` merged oldest
first, up to `maxItemsPerRun` items. Stop conditions (`provider_key_unavailable`,
`request_ceiling_reached`, `standing_capacity_reached`, `run_busy`, any 401/403/404/429/503/507/409,
and a job still running after `pollSeconds`) end the sweep cleanly: the run receipt says
`status: stopped` with `stoppedBy`, items stay where they were, and nothing is retried
until the next schedule. A refused POST leaves no job marker, so it may be sent later; an
accepted job keeps its `jobId` under `ROUTE#...`.`jobs` and is only polled.

## Router items

| `sk` | Meaning |
| --- | --- |
| `CONFIG#router` | Config (below) |
| `LOCK#router` | Lease (660 s, longer than the 600 s timeout), separate from the collector's `LOCK` |
| `ROUTE#<sourceId>#<rev6>` | `dryRun` (`count`, `validatedAt`, `requests.<pub>` = path, `requestId`, bytes, body; `contexts.<pub>` = `contextHash`/`reason`), `jobs.<pub>` (`requestId`, `jobId`, `checked`), `decision` (`decisionId`, `source` = id/revision/fingerprint, per-publication `output`, `label`, `fingerprint`, `version`, plus account, run, binding revision), `publications.<pub>` (`delivered`, `referenceId`, `attempts`, `lastError`), `final` |
| `DELIV#<pub>#<referenceId>` | A Reference this router delivered; feedback source. In `FEEDBACK#hn#pending` while feedback is outstanding |
| `FB#<requestId>` | Feedback receipt: outcome, label, curation status, publication |
| `ROUTERUN#<startedAt>#<runId>` | Run receipt: mode, status, `stoppedBy`, counts, feedback summary, errors; 30 days |

Receipts contain public HN data and identifiers only; no editorial policy text
or credentials. Read them like the collector's:

```sh
aws dynamodb query --table-name "$TABLE" --key-condition-expression 'pk = :p AND begins_with(sk, :r)' \
  --expression-attribute-values '{":p":{"S":"MONITOR#hn"},":r":{"S":"ROUTERUN#"}}' --scan-index-forward false --limit 3
aws dynamodb get-item --table-name "$TABLE" --key '{"pk":{"S":"MONITOR#hn"},"sk":{"S":"ROUTE#<sourceId>#000001"}}'
```

## Config shape

`docs/monitoring-router-config.example.json`; seeded with `infra/monitoring/seed_router_config.py`.

```json
{"mode": "dry-run|live", "maxItemsPerRun": 5, "feedback": false, "enabled": true,
 "publications": [{"publicationId": "...", "site": "...", "appsyncEndpoint": "https://<id>.appsync-api.<region>.amazonaws.com/graphql",
                   "corpusId": "knowledge-corpus-<publicationId> (default)"}],
 "cyclotron": {"endpoint": "https://<id>.execute-api.<region>.amazonaws.com", "accountId": "...", "runId": "...",
               "bindingRevision": "1", "roleArn": "arn:aws:iam::<account>:role/<machine invoker>", "pollSeconds": 45}}
```

The output is `<publicationId>-relevance` with labels `include` and `exclude` (override per
publication with `output`, `positiveLabel`, `negativeLabel`). The validator refuses non-`execute-api`
Cyclotron origins and non-AppSync publication endpoints, so credentials cannot be pointed elsewhere
by a data edit. A publication that is not in `publications` is never called.

## Delivery

For each positive publication the router runs the existing `ReferenceIntake` over IAM-signed
AppSync: a `pending` Reference (never an upsert, so human curation is never reset), plus the
provenance Message whose body holds the Cyclotron decision (`decisionId`, `output`, `label`,
`fingerprint`, `version`, account, run, binding revision, "machine decision"). The
Reference's rationale line ends with the decision so editors see it in the queue. Delivered
flags, attempts and errors are kept per publication per item; one failing backend never loses
the others, and a rerun skips what is already delivered. The publication needs exactly one
canonical `KnowledgeCorpus`.

## Feedback

Only when `mode` is `live` **and** `feedback` is `true`. For each `DELIV#` row still pending
(25 per run, rotated) the router reads the Reference. `pending` is ignored. `accepted` maps to
`include` and `rejected` to `exclude` for that publication's output. The editor comes from
`curationStatusUpdatedBy` (`user:<sub>`, sent as the subject with the configured `site`); a missing
actor, the worker's own actor or anything not `user:` is skipped and the reason recorded on the row.
`requestId = sha256(referenceId \n curationStatus \n curationStatusUpdatedAt)`, so repeats are
idempotent; the item revision and output come from the stored decision receipt.

## IAM (role `RouterRole`)

| Statement | Why |
| --- | --- |
| DynamoDB `GetItem`, `PutItem`, `DeleteItem`, `Query` on the table and its `routing` index | Config, state, receipts, lease. No `Scan`, no `UpdateItem` |
| Logs `CreateLogStream`, `PutLogEvents` on its own group | Logging |
| `sqs:SendMessage` on its dead-letter queue | Failed invocations and failed schedule deliveries |
| `sts:AssumeRole` on exactly `CyclotronInvokerRoleArn` | The only way to reach the Cyclotron machine API (the invoker role trusts this role's exact ARN) |
| `appsync:GraphQL` per API per field, three APIs (parameters `AnthUsApiId`, `PapyrusApiId`, `ThreatIntelApiId`) | Query: `getKnowledgeImportRun`, `getMessage`, `getModelAttachment`, `getReference`, `getReferenceAttachment`, `getSemanticRelation`, `itemBySlug`, `listKnowledgeCorpuses`, `listKnowledgeCorporaByRoleAndName`, `listReferences`. Mutation: `completeModelAttachmentUpload`, `createKnowledgeImportRun`, `createMessage`, `createModelAttachmentUpload`, `createReference`, `createReferenceAttachment`, `createSemanticRelation`, `updateReferenceAttachment` |

The field list was captured by running the real intake and editorial-context code against a
recording client. `updateReferenceAttachment` is there because a second HN item for an
existing URL re-points the shared source attachment. There are no deletes, no other updates (a
Reference is never updated), no wildcard resources, no admin. The provenance upload uses the
presigned URL AppSync returns, so the role needs no S3 permission.

Limits: Python 3.13 arm64, 512 MB, 600 s timeout, retry 0 on async invocation, dead-letter queue,
logs kept 30 days, reserved concurrency parameter `RouterReservedConcurrency` (0 where the
account quota cannot reserve any; the table lease serializes runs anyway). Alarms:
`papyrus-monitoring-router-errors` and `papyrus-monitoring-router-dead-letters`.

## Packaging

`python3 infra/monitoring/build.py --router [--upload BUCKET]` builds a separate deterministic zip
(`papyrus-monitoring/router-<sha256>.zip`, about 130 KB): the in-package import closure of the
router, the two YAML data files the shared Reference factories read, and pure-Python PyYAML (the
runtime has boto3/botocore only). `PAPYRUS_ROOT=/var/task` lets the factories find `corpora/`. A test
imports the extracted zip with a stdlib-only interpreter. The collector zip and its hash are unchanged.

## Operating the router

- Seed: `seed_router_config.py --table TABLE --file router.json` (starts as `dry-run`, `feedback: false`).
- **Flip to live** (data change, no deploy): `seed_router_config.py --table TABLE --set mode=live`.
  Dry-run receipts are harmless; `dry-run-validated` items are processed as live items.
- **Enable feedback** (after the Cyclotron operators approve the editor claim): `--set feedback=true`.
  Disable with `feedback=false`; back to dry-run with `mode=dry-run`; stop entirely with `enabled=false`
  or `ScheduleState=DISABLED`.
- Reconcile an `uncertain` item: check Cyclotron for its `requestId` (in `ROUTE#...`.`jobs`), then
  delete that `jobs` entry or set the discovery back to `routing=collected` with
  `gsi1pk=ROUTING#hn#collected` to let it be sent again.
- Roll back code: build an earlier commit with `--router`, upload, update the stack with that
  `RouterCodeKey`. Delivered References stay (they are pending and editor-owned); nothing is deleted.
- Deploy with a change set and read it first; a router-only change set should show only router resources.
