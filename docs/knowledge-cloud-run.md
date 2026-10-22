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
| `archive` | `knowledge archive` for the week, never `--replace` (step 13) |
| `wiki-sync` | `wiki sync --apply`, then `wiki publish --all-drafts --actor ai --no-trigger` (step 14) |
| `projection` | `ops content project --all` under the projection lease and the deletion guard, never `--allow-deletions` |

Two differences from the runbook order: the AI review comes after the import, because it reviews what the import created, and `wiki publish` is told not to project, because `projection` does that once, last.

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

### Testing a failure

```bash
aws stepfunctions start-execution --state-machine-arn <arn> --name test-fail-$(date -u +%H%M%S) \
  --input '{"publication":"shipped","failStage":"ai-review"}'
```

The stage `ai-review` fails on entry, the machine stops, the failure alarm publishes to SNS and the site is unchanged. A scheduled execution never carries `failStage`, and a name that does not start with `test-` ignores it.

## Cost

The design estimate was 1.50 to 2.50 USD a month. Measured figures are in the "First runs" section below. The levers: the stage list runs about two hours of Fargate a week, so vCPU-hours dominate; Graviton ARM64 is about 20 percent cheaper than x86; there is no NAT gateway (tasks run in public subnets with egress-only security groups) and S3 and DynamoDB are reached through free gateway endpoints; the other costs are cents (ECR storage of the image, CloudWatch Logs, DynamoDB on demand, Step Functions state transitions).

## Another job

The CDK construct `ScheduledContainerJob` (`infra/scheduled-jobs/lib/scheduled-container-job.ts`) takes a pipeline definition (ordered stages, each a container command with its own size, timeout and retries), a schedule, a policy for the task role and an alarm email parameter. The knowledge run is one configuration (`knowledge-pipeline.ts`). A second pipeline, such as the trend-story job, adds its own definition and stack file.
