# Knowledge cloud run

The weekly [knowledge run](knowledge-workstation-run.md) as an unattended job in AWS: BERTopic, GLiNER2, an AI review, the snapshot and its archive, the wiki and the projection, on a schedule, with nobody's workstation involved. Status: Beta. Story PPY-dca7cd; Shipped (`https://shipped.anth.us`) is the first publication.

The workstation runbook stays the reference for what each step does and why. This page is about the machine that runs those steps.

## What runs

```text
EventBridge Scheduler (weekly)
  -> Step Functions Standard state machine
       corpus-sync -> topic-model -> typed-extraction -> publish-run -> ai-review
       -> publish-relations -> snapshot -> archive -> wiki-sync -> projection
       (each arrow is a Fargate task, with retries; any failure ends the run, never reaching projection)
```

Each stage is one ECS Fargate task (ARM64, CPU, 4 vCPU and 16 GB to start) from one image: Papyrus, Biblicus (pinned commit), BERTopic and GLiNER2 on pinned versions, with the models baked in (`HF_HUB_OFFLINE=1`, nothing is downloaded during a run). The task command is `papyrus knowledge cloud-run --stage <name>`.

| Stage | What it does (the runbook step) |
| --- | --- |
| `corpus-sync` | Checkout of the site repository at the commit of the Amplify app's latest successful deploy (see below), `corpus export`, `reindex`, extraction snapshot (steps 1-3) |
| `topic-model` | BERTopic, weekly trends, topic identity against the previous run kept in S3 (steps 4-6) |
| `typed-extraction` | Front-matter import, registry, GLiNER2 typed entities (steps 7-8) |
| `publish-run` | Import clusters, entities and relations; then record the run as next week's `previousRunId` (steps 9-10) |
| `ai-review` | GPT-6 Luna reviews the extractor's entities, new clusters and relations (step 11); see below |
| `publish-relations` | Import again, so relations between entities accepted by the review land |
| `snapshot` | `knowledge snapshot` to the site bucket, no `--reproject` (step 12) |
| `archive` | `knowledge archive` for the week, never `--replace` (step 13). A week that already has an entry keeps it (entries are immutable), so a second run in the same week skips this step |
| `wiki-sync` | `wiki sync --apply`, then `wiki publish --all-drafts --actor ai --no-trigger` (step 14) |
| `projection` | `ops content project --all` under the projection lease and the deletion guard, never `--allow-deletions` |

Two differences from the runbook order: the AI review comes after the import, because it reviews what the import created, and `wiki publish` is told not to project, because `projection` does that once, last.

### Trend drafts (optional, off by default)

After `projection` the state machine can run one more task, `trend-drafts`: `papyrus ideas trends --site <publication> --snapshot <published index.json> --store proposals --max 2` ([idea pipeline](idea-pipeline.md#trend-stories)). It files private `story_draft` Proposals and raises one soft review request; nothing is published. It is `infra/knowledge-run/trend_drafts.py`, baked into the image, and it is a gate in the state machine, not a stage of `papyrus knowledge cloud-run`.

- **Switch.** Three CloudFormation parameters on the stack, all inert by default: `TrendDraftsEnabled` (`false`), `TrendDraftsEndpoint` (the publication's AppSync GraphQL address) and `TrendDraftsSnapshotUrl` (the published `.../_data/knowledge/index.json`). While `TrendDraftsEnabled` is `false` the execution goes from `projection` to `Done` and no task starts.
- **Fresh snapshot only.** The step reads the published address, not a local file (a local snapshot has no item URLs or summaries). The run week is the Monday on or before the execution start, which is the `asOf` the `snapshot` stage writes. The script checks the published `asOf` against it up to 3 times, 60 seconds apart (the CDN may lag the projection). If it is still another week, the step logs `trend-drafts: skipped: the published snapshot is stale: ...` and stops.
- **Never fails the run.** The script exits 0 on every problem and logs `trend-drafts: skipped: <reason>` or `trend-drafts: failed: <reason>`; the state also catches any task error into `Done`, with no retry. The alarms do not see it; read the task log (`trend-drafts` prefix) after the first runs.
- **Key and permissions.** The OpenAI key comes from the SSM SecureString named by `openAiKeyParameter` (`/papyrus/shipped/openai-api-key`), read by the task role at run time and given only to the command's environment. The task role needs nothing new: `ssm:GetParameter` on that parameter (the AI review reads it too) and `appsync:GraphQL` on the publication's API (`SignAppSyncRequests`) already cover what the command uses under IAM (listing stories, sections and review requests, `fileProposal`, and the review-request mutation).
- **Repeat runs.** Under IAM the command cannot read earlier Proposals, so it cannot dedupe against them; a second execution in the same week files the drafts again. Decline the extras in the console.

### Monitor records (optional, off by default)

A monitor ([monitoring-cloud.md](monitoring-cloud.md)) can deliver models, say from the Hugging Face Hub, as pending References for a person to judge. They are signal before anyone has judged them, so a site can have the run **count them as data**: in entities and in the weekly trends, and never as pages or as members of topic-model clusters. The setting lives in the site's `knowledgeRun` block of `infra/site.json`, like `conceptKinds`:

```json
"knowledgeRun": {
  "monitorSources": ["huggingface"],
  "monitorWeeks": 52
}
```

`monitorSources` (the only supported source is `huggingface`) turns it on; `monitorWeeks` (1 to 260, default 52) is how far back a record counts. Without `monitorSources` nothing below happens and the snapshot is byte for byte what it was. The stack sets `KNOWLEDGE_MONITOR_SOURCES` and `KNOWLEDGE_MONITOR_WEEKS` on the task; `cdk deploy` the stack after changing them.

| Stage | What changes |
| --- | --- |
| `corpus-sync` | `corpus export --monitor-sources huggingface --monitor-weeks N --corpus-key <publication> --as-of <Monday> --monitor-records-out <run>/monitor-records.json`. Every current Reference of the publication's corpus whose address is the Hub and whose curation state is not `rejected` (`pending` and `accepted` both count) and whose **source date** (the model's `createdAt`) is inside the window becomes a row of `monitor-records.json`, kept with the week's run state in S3. The record's Hub fields come from the `details` on its provenance relation (one indexed query per record). **It does not become a corpus document**: records are data for counts and relations, and the topic model reads only the site's own items (see `topic-model` below). At most 5,000 records, newest first; a warning says when more fall in the window. A 12-month backfill therefore produces real weekly history. |
| `topic-model` | **Records are not documents.** The topic model reads only the site's own items. On 2026-10-26 the records were corpus documents and 5,000 Hub model lines split into 27 maker-named clusters ("NVIDIA AI Models", "LiquidAI LFM models") that drowned the four editorial ones (Decision models, Open-weights language models, Open text-to-speech models, Safety and guard models). `corpus export --records-in-topic-model` brings the old behaviour back for an experiment; the cloud run never passes it. |
| `typed-extraction` | GLiNER2 reads only the site's items; entities of records are never AI-extracted. |
| `publish-run`, `publish-relations` | `--monitor-records <file>` adds the **structured entities and relations**, deterministically, with no AI review (below). |
| `ai-review` | Record titles (model ids) count as member titles, so a cluster of Hub models can be named. Source facts are `confirmed` already, so no entity or relation of a record is reviewed. |
| `snapshot`, `archive` | `--monitor-records <file>`: records count in clusters, entities and weekly series (below). |
| `wiki-sync` | `--monitor-records <file>`: an entity that only records mention gets **no wiki page**, and no page lists it as related. |

**Structured entities.** Each record links (`mentions` from the Reference, marked `knowledge.record_mention`, always confirmed) to an entity per Hub field: the model (`model--org-name`, named by the model id), its maker (the Hub author, `maker--org`), its licence (`licence--apache-2-0`; the Hub's `other` and `unknown` are not licences) and its task (the pipeline tag, `task--text-to-speech`). An existing entity of the site is matched first by key, so the entities of the site's own items are reused; a new one is accepted by `ai` under the name `Hugging Face Hub import`. A rejected entity is never linked. The Hub's platform (`platform--hugging-face`) is deliberately not linked: it would swamp the platform's own weekly counts.

**Structured relations.** A base model the Hub names becomes a `built_on` relation from the model to its base, confirmed, with `subtype` (`finetune`, `quantized`, `adapter`, `merge` or `declared`), `evidence` (the Hub card) and `provenance` (`from the Hugging Face Hub`) in its metadata, shown on the entity file's neighbour row. Both ends must already be entities: a model with a record in the window, or an accepted entity named by that id. A base model that is neither stays in the record. Nothing is superseded or deleted on the way, except that a record whose Hub fields changed supersedes the links it no longer has.

**In the snapshot.** Records are dated items for the counts of **entities**, so `itemCount`, `series8` and the four-week change of an entity include them (a cluster counts only the site's own items, because the topic model does not read records, so a cluster row has no `recordCount` unless `--records-in-topic-model` is used), and a 52-week window gives a year of history. Beside that: an entity or cluster row has `recordCount` (how many of its items are records), the entity file lists the newest records apart from the site's items in `relatedRecords` (`title` = model id, `url` = the Hub card, `publishedAt`, `summary` from the structured fields, `source`, `provenance`), and `relatedItems` stays the site's own pages. An entity only records mention has `href: null`, and appears at all only when at least two records link it or it takes part in a confirmed relation, so a lone model does not clutter the map. Without records none of these fields exist.

**Verify on the next run.** In the `corpus-sync` task log: `knowledge corpus-export ... N monitor records`. In S3: `runs/<week>/monitor-records.json`. In the `publish-run` log: `recordNodesCreated`, `recordLinks`, `recordRelations`, `recordBaseModelsOffMap`. On the site: `_data/knowledge/index.json` entities with `recordCount`, `entities/<key>.json` with `relatedRecords` and `built_on` neighbours with `subtype`, and no new `/wiki/` page for a Hub-only entity. The first run after turning it on pays for reading every record's provenance once (two requests per record).

**Promotion.** A person turns a record into a normal item with `papyrus references promote <reference id> --section <section>` ([monitoring-cloud.md](monitoring-cloud.md#promoting-a-record-to-an-item)): a **draft** article carrying the source link and the record's facts, for an editor to write and publish. The weekly run can also ask for a first look: set `monitorSuggestions` (0 to 20, default 0 = off) in `knowledgeRun` (it sets `KNOWLEDGE_MONITOR_SUGGESTIONS`) and the `ai-review` stage raises **one soft review request** per week (`rr-monitor-records-<publication>-<week>`, seven days, idempotent) that lists that many records. The first pass has no model: among the records of the last four weeks that no item carries yet, the Hub's own interest decides (likes, then downloads, then the model id). The request asks nobody to publish anything; the stage log `ai-review.json` has the same list under `monitorSuggestions` (`status` `requested`, `none` or `not_raised` with the error). A site that cannot take review requests, or a missing records file, never fails the run.

### The AI review

For each unreviewed entity (`generated`), each new cluster and each proposed relation between accepted entities, the stage gives GPT-6 Luna (the Responses API, a structured answer, `store: false`) short snippets of the site's own text and asks for `accept`, `reject` or `unsure`. The model never decides alone:

- An `accept` counts only if the evidence it quotes is a verbatim piece of a snippet it was given and names the thing. For a relation (`member_of` too) the quote must name both ends. A cluster is accepted only with a name and at least three quoted member titles.
- Anything else is treated as `unsure` and the row is left as the extractor left it. `reject` is for junk (sizes, file formats, generic nouns).
- Everything is recorded as accepted or rejected by the actor `ai` (shown as "AI" on the site) with the day. The decisions, quotes and reasons of each run are kept in `runs/<week>/ai-review.json` in the state bucket.
- The OpenAI key is read from the SSM SecureString `/papyrus/<publication>/openai-api-key` by the task role at run time. It is never in the image, the template or a log. `KNOWLEDGE_REVIEW_MAX_CALLS` (default 150) caps the calls of one run.

`config/review-guidance.md` in the state bucket, if present, is appended to the instructions: the publication's editors' preferences, kept out of code.

## State, ledger and idempotency

State is per publication in the stack's S3 bucket (versioned, private), under `publications/<publication>/`:

| Prefix | Holds |
| --- | --- |
| `config/` | What an operator maintains: `vocabulary.yml`, `stop-words.txt`, `review-guidance.md` (optional), `amplify_outputs.json` (endpoint only, no secrets) |
| `corpus/` | The long-lived Biblicus corpus, including `knowledge-run.json` (the previous run's identity state) |
| `runs/<ISO week>/` | Scratch of a run: topics, trends, identity, registry, typed output, `ai-review.json`, `state.json` |

A stage downloads what it needs, runs, uploads what changed. A container keeps nothing between stages.

The run ledger is a DynamoDB table: partition key `publication`, sort key `runKey` = `<ISO week>#<execution name>#<stage>`, with `status` (`running`, `succeeded`, `failed`), `attempts`, timestamps, the error and a small details object. Query a week with `publication = shipped AND begins_with(runKey, '2026-W44')`.

Every stage is idempotent. Within one execution a stage that already succeeded is skipped when Step Functions starts it again; another execution of the same week (a manual run after the scheduled one) runs every stage again. The site checkout is a fresh shallow clone checked against the branch tip, so a stale checkout cannot be used. Step Functions retries each stage with backoff (two retries, 60 s, doubling).

## Failure behaviour

A stage that fails after its retries ends the execution in a `Failed-<stage>` state. `projection` is the last stage, so nothing is projected, no page is deleted and the site keeps serving the last good projection. Records the earlier stages wrote (accepted entities, clusters) stay in the backend. The deletion guard of the projection engine refuses a projection that would delete a large share of the site's pages; the cloud run never passes `--allow-deletions`.

**Site code.** Every stage that needs the site (`web/` templates and hooks, the beats config) checks out the commit of the CMS Amplify app's most recently finished successful deploy of the branch (`amplify:ListJobs`, the `SUCCEED` job with the latest `endTime`, whatever order the jobs are listed in), not whatever `main` is by then, so the pages a run renders are the pages the live site was built from. If the app has no successful deploy, the fetch fails or the checkout is another commit, the stage fails before it writes. The `projection` stage then installs the Papyrus release the site pins in its `requirements-publication.txt` (`pip install --no-deps --target`, first on `PYTHONPATH`), the release its Lambda runs, and refuses to project if that release lacks the projection lease.

**The run only writes.** No stage runs `project --reconcile`, passes `--allow-deletions` or `--replace`, or cleans anything up. The snapshot stage rewrites the knowledge JSON and drops only the entity files of entities that no longer exist.

**Plugins.** A projection without the site's plugins renders no plugin pages (the newsletter pages, for one), and a cleanup would then call them orphans. The stack therefore sets `PAPYRUS_PLUGINS` on the task from the `plugins` list of the site's `knowledgeRun` config, and the stages that write to the site (`snapshot`, `archive`, `projection`) compare it with `PAPYRUS_PLUGINS` on the site's deployed content-actions Lambda (`contentActionsFunction`, read with `lambda:GetFunctionConfiguration`). If the lists differ the stage fails before it writes anything.

The projection also takes the [projection lease](site-hosting.md#projection-lease) of the publication. If a deploy or a manual projection holds it, the stage waits (up to `lockWaitSeconds`, 1800 by default), then fails and alarms, still before anything is written.

Alarms (SNS topic `papyrus-scheduled-job-knowledge-run-<publication>`, email subscription from the SSM parameter `/papyrus/<publication>/knowledge-run/alarm-email`; the address is never in the repository):

- Execution failed, aborted or timed out: any of them in a 5-minute window.
- Missed week: no successful execution in 8 days. CloudWatch cannot evaluate an alarm over more than 7 days, so a small daily Lambda (12:17 UTC) publishes the days since the last success as a metric and the alarm fires at 8 or more. If that Lambda stops, the alarm fires too.

A new subscription must be confirmed once from the mailbox. A stack that has never run alarms for a missed week until its first success.

## Operating it

The stacks are CDK (`infra/scheduled-jobs/`, config from the publication's `infra/site.json` `knowledgeRun` block; example `infra/amplify-app-shell/examples/shipped.site.json`). All commands use the production profile and assert the account first.

```bash
export AWS_PROFILE=papyrus-production
aws sts get-caller-identity --query Account --output text      # 712236451410
infra/knowledge-run/build_image.sh                              # builds arm64, pushes, prints the tag
cd infra/scheduled-jobs && npm ci
SITE=../amplify-app-shell/examples/shipped.site.json
npx cdk diff   -c site=$SITE -c imageTag=<tag> KnowledgeRun-shipped    # read the change set
npx cdk deploy -c site=$SITE -c imageTag=<tag> KnowledgeRun-shipped
```

Start a run by hand (the same state machine the schedule starts). Name it `manual-...`; a name starting `test-` is the only kind that honours `failStage`:

```bash
aws stepfunctions start-execution --state-machine-arn <StateMachineArn> \
  --name manual-$(date -u +%Y%m%dT%H%M%S) --input '{"publication":"shipped"}'
```

Inspect: the Step Functions console (one state per stage), the log group of the stack (`/aws/ecs/...`, one stream per task, each line prefixed by the command run), the ledger rows, and `runs/<week>/ai-review.json`. Change the schedule or pause it with `schedule` and `scheduleState` in `knowledgeRun`, then `cdk deploy`.

Seeding state for a new publication: upload `vocabulary.yml`, `stop-words.txt` and `amplify_outputs.json` to `config/`, and, to carry cluster identity from an earlier workstation run, the whole workstation corpus to `corpus/` (its `knowledge-run.json` names the previous run, and that run's analysis must be in the corpus).

### Building and pushing the image

`infra/knowledge-run/build_image.sh` builds the arm64 image from `infra/knowledge-run/Dockerfile` (Papyrus and Biblicus from PyPI at `PAPYRUS_VERSION` (5.39.0 in the Dockerfile; `ideas trends` needs 5.39.0 or later) and `BIBLICUS_VERSION`, `awscrt`, the models baked in at pinned revisions) and pushes it with the tag you give in `IMAGE_TAG` (default the git sha). `PAPYRUS_SPEC='papyrus-newsroom[markus] @ git+https://github.com/AnthusAI/Papyrus@<sha>'` builds a commit that is not released yet. The first build takes about 15 minutes, later ones one layer. To move to a newer release, change `ARG PAPYRUS_VERSION` in the Dockerfile (or build with `PAPYRUS_VERSION=<x.y.z>`), commit, and run the script again: the tag is the commit, and ECR tags are immutable. If Docker Desktop's credential helper hangs, point `DOCKER_CONFIG` at an empty directory containing `{}` and set `DOCKER_HOST=unix://$HOME/.docker/run/docker.sock`. Deploy the tag with `cdk deploy ... -c imageTag=<tag>` (a new task-definition revision; the state machine picks up the latest revision at the start of each stage, so do not deploy during a run).

### Testing a failure

```bash
aws stepfunctions start-execution --state-machine-arn <arn> --name test-fail-$(date -u +%H%M%S) \
  --input '{"publication":"shipped","failStage":"ai-review"}'
```

The stage `ai-review` fails on entry, the machine stops, the failure alarm publishes to SNS and the site is unchanged. A scheduled execution never carries `failStage`, and a name that does not start with `test-` ignores it.

## First runs

Shipped, October 2026, 4 vCPU and 16 GB ARM64 for every stage, image `papyrus-newsroom` 5.31.0 and Biblicus 1.16.0 on CPU.

| Execution | Result | Time |
| --- | --- | --- |
| `manual-20261022T211018` | Nine stages passed. `projection` failed all three attempts: botocore needs `awscrt` to sign the CloudFront KeyValueStore call (SigV4a), at the first line of the projection, before any write. The failure alarm fired and published to SNS. Fixed by adding `awscrt` to the image. | 75 min (a backlog: the first AI review judged 719 entities, 35 calls, 80 accepted and 577 rejected) |
| `manual-20261023T041010` | Succeeded: 10 stages. Projection wrote 1,224 files and deleted 0. | 46 min |
| `test-fail-20261023T045833` (`failStage` `ai-review`) | Failed at `ai-review` after three attempts, stopped before `snapshot`; alarm fired. Site byte-identical before and after (all 2,110 keys, the `newsletter/` and `_plugins/` listings with sizes and ETags, the knowledge index and archive). | 24 min |
| `da6adaf1-...` (started by the weekly schedule at a test time, then the cron was set back) | Succeeded: 10 stages, nobody involved. Projection wrote 1,224 files and deleted 0. | 42 min |

Stage times of the second run (state entered to next state, including about 1.5 minutes of task start and image pull): `corpus-sync` 3.0, `topic-model` 3.4, `typed-extraction` 6.5, `publish-run` 5.9, `ai-review` 6.8, `publish-relations` 5.5, `snapshot` 2.7, `archive` 1.6, `wiki-sync` 7.7, `projection` 4.2 minutes.

What the first runs taught:

- `awscrt` is needed for the redirect store, so it is in the image.
- A week that has an archive entry already (the one-off run made it) keeps that entry: the archive stage skips and says so in the ledger, `archive: kept-existing (run <id>)`. A corrupt entry, or one for another week, fails the stage.
- The Amplify job list is ordered by job id, which is not the order deploys finish in, so the deployed commit is the `SUCCEED` job with the latest `endTime`.
- CloudWatch refuses an alarm that looks back more than 7 days, hence the watchdog Lambda for the missed-week alarm (it needs the `stepfunctions` boto3 client; `states` is only the IAM prefix).
- The deploys of the site itself also render the wiki pages that the run publishes, so the wiki can show new pages before the run's own projection.

## Cost

The design estimate was 1.50 to 2.50 USD a month. Measured with the run times above at the ARM64 Fargate rate (4 vCPU at 0.03238 USD per hour, 16 GB at 0.00356 per GB-hour, 20 GB of extra storage, about 0.189 USD per hour):

| Item | Per run | Per month (4.33 runs) |
| --- | --- | --- |
| Fargate, 42 to 46 minutes | about 0.14 USD | about 0.6 USD |
| Public IPv4 of the tasks, Step Functions, logs | under 0.01 USD | about 0.03 USD |
| Alarms (the failure alarm sums three metrics) | | 0.40 USD |
| ECR storage of the image (about 4 GB per image, layers shared) | | 0.5 to 1.2 USD |
| DynamoDB, S3 state, Lambda, EventBridge, SNS | | cents |
| GPT-6 Luna reviews (35 calls on the first backlog, a handful in a normal week) | | cents |
| Total | | about 2 USD |

No NAT gateway (tasks run in public subnets with egress-only security groups) and S3 and DynamoDB are reached through the free gateway endpoints. Cost Explorer lags a day and does not yet break Fargate out by tag; check `Amazon Elastic Container Service` after a week. The stages that do little (`snapshot`, `archive`, `wiki-sync`, `projection`) could run at 2 vCPU and 8 GB for under 0.1 USD a month; that is a per-stage `vCpu` and `memoryMiB` in the pipeline definition if the bill ever matters.

## Another job

The CDK construct `ScheduledContainerJob` (`infra/scheduled-jobs/lib/scheduled-container-job.ts`) takes a pipeline definition (ordered stages, each a container command with its own size, timeout and retries), a schedule, a policy for the task role and an alarm email parameter. The knowledge run is one configuration (`knowledge-pipeline.ts`). A second pipeline, such as the trend-story job, adds its own definition and stack file.
