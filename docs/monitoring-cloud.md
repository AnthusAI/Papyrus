# Monitoring in the cloud (HN collector)

PPY-3212f1, step 1: the Hacker News collector runs on a schedule in AWS instead of
on an operator's machine. It is a dedicated stack, `papyrus-monitoring`, not part
of any site backend: the monitor is shared by several publications, no one site
owns it, and an Amplify backend deploy would tie HN collection to one site's
pipeline. Like the edge stacks (`infra/edge/README.md`) it is a hand-run
CloudFormation stack in account 712236451410, us-east-1, applied with a change set.

## Monitors and source types

Each monitor is its own `MONITOR#<id>` partition with its own schedules. `CONFIG.sourceType` names what
it reads: `hn-rss` (the default, the Hacker News feed), `huggingface-models` (the Hugging Face Hub model list,
[below](#hugging-face-hub-monitor-huggingface-models)) or `ttab-decisions` (the USPTO TTAB Reading Room
decision search, `lookbackDays` 1 to 180, `finalDecisionsOnly` true by default, and `precedentialLookbackDays`:
when set, a second search over that longer window asks only for precedential decisions of any type, because the
Board can designate a decision precedential months after it issues). A TTAB item also lists the decision's other
addresses (the TTABVUE PDF, the Reading Room's double-slash path), and intake reuses a Reference stored under
any of them rather than creating a second one for the same decision. Each source type only
accepts a `sourceUrl` on its own host. `CONFIG#router.decisions` is `cyclotron` (the default: ask the shared
Cyclotron per publication) or `direct` (deliver every collected item to every configured publication,
recorded as the monitor's own rule; no Cyclotron block, no feedback). Seed a TTAB monitor with
`seed_config.py --monitor-id ttab --source-type ttab-decisions --interval-seconds 86400 --limit 100` and
`seed_router_config.py --monitor-id ttab --file router.json` with `"decisions": "direct"`.

| Monitor | Source | Collect | Route | Decisions | Publications |
| --- | --- | --- | --- | --- | --- |
| `hn` | `hn-rss` | `papyrus-monitoring-hn-collect`, every 15 min | `papyrus-monitoring-hn-route`, :07/:22/:37/:52 | cyclotron | anth-us, p-apyr-us, threat-intelligence |
| `ttab` | `ttab-decisions` | `papyrus-monitoring-ttab-collect`, every 6 h (collects daily) | `papyrus-monitoring-ttab-route`, hourly at :41 | direct | distinctive |
| `huggingface` | `huggingface-models` | `papyrus-monitoring-huggingface-collect`, every 6 h (collects daily) | `papyrus-monitoring-huggingface-route`, hourly at :17 | direct, with a `rule` | shipped |

A publication the router delivers to needs its AppSync grants in the router role. The inline policy holds
three sites; Distinctive Mark's are in the managed policy `RouterDistinctiveIntakePolicy`, and further
sites should follow that pattern (a role's inline policies are limited to 10,240 characters).

Shipped (`ShippedApiId`, default `6sw6454pozbgvdgm233gqkxsxu`) has its grants in place (`RouterShippedIntakePolicy`, and
its `relevance_decision_is` fields in `RouterDecisionRelationPolicy`), but no router config yet. The `hn` router config
adds a `shipped` publication only once Cyclotron r3 adds the publication `shipped` with output `shipped-relevance`.

**Lab decisions in the References tab.** When the router delivers a Cyclotron lab decision it also writes a
`relevance_decision_is` relation for the Reference, in the same persist batch as the Reference and its provenance
Message, so the Suggestion row, Agree/Overrule and status read it like a sweep decision. `metadata.cyclotronId` and
`classifierId` name the lab output (`<publication>-relevance`); `metadata.provenance` records account, run, binding
revision, decision id, fingerprint and version. Any current decision relation for the Reference is superseded; the
relation id derives from the decision id, so re-delivering the same decision writes nothing. Cost per item: one
`listSemanticRelationsBySubjectState` query, a get each for the label's SemanticNode and the relation, a create for the
relation (plus the node the first time, and one get and update per superseded relation); no Cyclotron call. The grants
are in the managed policy `RouterDecisionRelationPolicy` (cyclotron-decided sites only), which must be deployed with
the stack before this code runs against a site, or delivery fails on the first write. `direct` monitors write none.

**Backfilling relations for earlier deliveries.** References the router delivered before the relation code
shipped have no decision relation, so their Suggestion row is empty. `papyrus monitors backfill-decision-relations`
(account 712236451410, table from `/papyrus/monitoring/table-name`) reads the `ROUTE#` receipts, and for each
publication that delivered a lab decision it builds the same records with the router's own `lab_decision_records`
and writes them over the publication's AppSync endpoint with IAM. It is a dry run unless `--apply` is given, and
prints the planned writes (reference id, label, confidence) and the skip counts per publication. A Reference that
has any current decision relation is skipped, a decision already recorded (even if superseded since) is not
recreated, and nothing is ever superseded, so a re-run writes nothing. Options: `--publication <id>` (repeatable),
`--since <iso>` (delivery time, needs a timezone), `--monitor <id>` (default `hn`).

## Hugging Face Hub monitor (`huggingface-models`)

Feeds Shipped's knowledge map. It reads the public model list (`https://huggingface.co/api/models`, no key). The
Hub cannot filter by date or by likes, so the monitor's `CONFIG` describes a few **queries** and the reader pages each
one (cursor from the `Link` header; `pageSize` rows a page, at most `pagesPerQuery` pages) until it passes the window:

- one query per `authors` entry (a watchlist of organisations), newest first;
- one per `search` term, newest first;
- one per `pipelineTags` entry, in the configured `sort` (`createdAt` newest first, `trendingScore`, `likes` or `downloads`).

A model is **kept** when it was created inside the window (`lookbackDays`), matches `pipelineTags` (when given), and is
either from a watchlisted author, or has at least `minLikes` likes, or at least `minDownloads` downloads (30-day count).
With neither threshold set, every match is kept. Each day's run re-reads the whole window, so a model that reaches a
threshold within `lookbackDays` of its release is picked up then; one that gets there later is not. Only
`https://huggingface.co/api/models` is ever requested (the source URL, and every cursor, are checked), with a
descriptive `User-Agent` and a pause between requests. A 429 ends the read and the receipt says `stoppedBy:
rate_limited`; a query that fails does not stop the others; reads stop after 70 s (`stoppedBy: time_budget`).

| `CONFIG` field | Meaning |
| --- | --- |
| `sourceUrl` | exactly `https://huggingface.co/api/models` |
| `pipelineTags` | Hub pipeline tags to keep and to query, for example `text-generation`, `text-to-speech`, `text-classification` |
| `authors` | watchlist of organisations or users: always kept (subject to `pipelineTags`) |
| `search` | up to 10 search terms, each its own newest-first query (thresholds apply) |
| `sort` | for the `pipelineTags` queries: `createdAt` (default), `trendingScore`, `likes`, `downloads` |
| `minLikes`, `minDownloads` | thresholds; a model passes with either |
| `excludeTags` | Hub tags that mark a repackaged copy (`gguf`, `mlx`, `exl2`, `awq`, `4-bit`, ...); a model carrying any is not collected. Case-insensitive; default none |
| `excludeBaseRelations` | skip a model whose `baseModels` has one of these relations (`finetune`, `quantized`, `adapter`, `merge`, `declared`). Default none; `finetune` and `adapter` are real work, so list only `quantized` and `merge` unless you want them gone too |
| `excludeIdPatterns` | up to 50 case-insensitive regular expressions searched in the model id (`org/name`), for repackagers that do not tag (`-(q|iq)[0-9]`, `abliterat`, `bpw`) |
| `lookbackDays` (7), `pageSize` (200, up to 1000), `pagesPerQuery` (10) | window and bounds per query |
| `intervalSeconds`, `limit` | as for every monitor; `limit` is the most models stored per run, up to 1000 here (100 elsewhere) |

**Repackaged models.** A week of Shipped's models was mostly copies of existing ones (89 of 127): quantisations, "abliterated" or
uncensored variants, wrappers. The three `exclude*` fields drop them at collection, so they are never stored as
discoveries and never reach the Knowledge Map counts. They apply after the inclusion rule (a model that would have been
dropped anyway is not counted), the first matching reason wins (`tag`, then `baseRelation`, then `idPattern`), and the `RUN#`
receipt records `read.skipped`, for example `{"tag": 61, "idPattern": 20, "baseRelation": 8}`, with each model counted once
however many queries returned it. `excludeTags` sees a model's first 80 tags; relations are read from all of them. Backfill uses
the same filter (a changed filter starts a new backfill checkpoint) and prints and returns the skip counts. All three default
to empty: with none set nothing changes.

At least one of `pipelineTags`, `authors`, `search` is required. Each kept model is a discovery with `sourceType`,
`routing: collected` and a structured `details` map: `modelId`, `author`, `createdAt` (the release date, also
`sourcePublishedAt`), `lastModified`, `pipelineTag`, `tags`, `license`, `libraryName`, `likes`, `downloads`, `sha`, and
`baseModels`: `[{"modelId": "org/base", "relation": "finetune"|"quantized"|"adapter"|"merge"|"declared"}]`, read from the Hub's
`base_model:<relation>:<id>` tags and from `cardData.base_model` (relation `declared` when the tags do not already name
it). Only these fields are kept; model card text never is. `baseModels` is the "built on" relation, ready for typed
extraction. The source id is `org--name` (hashed when a character or the length does not fit a table key); the item is the
model page; the title is `org/name: <pipeline tag> model`.

**Dedupe is on the model's revision.** The fingerprint includes the Hub's `sha` (its latest commit): the same `sha` is
`unchanged` however its likes and downloads moved, and a new commit is the next revision of the same item. Likes and
downloads in `details` are as of the revision's collection.

**Routing.** Router config `decisions: "direct"` delivers every collected model to every configured publication, as
for TTAB. Add a **`rule`** to deliver only some: `{"pipelineTags": [...], "authors": [...], "minLikes": N, "minDownloads": N}`
(same meaning as above: the filters, then watchlist or a threshold) plus the same `excludeTags`, `excludeBaseRelations` and
`excludeIdPatterns`, which are checked first and apply even to a watchlisted author (defence in depth: a collector with the
exclusions already stored nothing to exclude, but older discoveries or a differently configured collector are still filtered). A model that fails it is finished as `routed`
with `reason: "excluded by the monitor's rule"` and delivered nowhere; in a dry run the receipt says `wouldDeliver: false`.
The rule is evaluated once, on the first collected revision. It is allowed only with `direct`, so it can stand in
until Cyclotron criteria exist; `cyclotron` routing also works, and sends `values.source: "huggingface"` (the Cyclotron
machine API must accept that source). The delivered Reference's rationale line carries the pipeline tag, license, likes
and base models, and the provenance Message body carries the whole `details` map.

### Feeding the Knowledge Map

Delivered models are References, so they stay out of the evidence sets until a person accepts them, and they never become pages. A site that wants them in its weekly Knowledge Map **as data** sets `monitorSources: ["huggingface"]` in the `knowledgeRun` block of its `infra/site.json` ([knowledge-cloud-run.md](knowledge-cloud-run.md#monitor-records-optional-off-by-default)). The next knowledge run then counts every delivered model that is not rejected, dated by its `createdAt`, in clusters, entities (the model, its maker, licence and task) and weekly trends, and imports `baseModels` as `built_on` relations with the Hub card as evidence. To make that possible without downloading each provenance Message, the router now also writes the model's structured `details` into the `metadata` of the `ingestion_rationale` relation that links the provenance Message to the Reference (a model delivered before this change is still counted, with its title, date and author only). Backfill the year you want counted before the first run; a record's weekly history is its release week, not its delivery week.

### Promoting a record to an item

A delivered model counts in the Knowledge Map as data and is never a page. To write about one, a person promotes it:

```bash
papyrus references promote <reference-id> --section <section>        # --dry-run shows what it would save
```

It saves a **draft** article `item-<section>-<org>-<name>` (type `article`, status draft) whose front matter has the title (the model id), the deck (the record's structured line), `entities` (the model, maker, licence and task), `sources` (the Hub card and "from the Hugging Face Hub") and `monitorRecord` (reference id, release date, licence, pipeline tag, likes, downloads, base models). There is no `date`: publishing stamps it. The body is a stub with the card link and a note that an editor writes the story. Nothing is published, the Reference's curation state is not changed, and promoting twice leaves the draft, and whatever the editor wrote in it, alone. The reference may be given by id, lineage id or external item id (as the first argument or `--reference`); `--actor-label` names who promoted it (default `papyrus-cli`). Only Hub models can be promoted.

### Backfill: loading history

`papyrus monitors backfill --monitor huggingface --since 2025-10-25T00:00:00Z` loads the models created since then that
the monitor's `CONFIG` would accept, through the same `ITEM#` dedupe as the live collector (so it is idempotent and can
run beside the schedule). It is a **dry run** (reads the Hub, counts what it would add, writes nothing) unless `--apply`.
Because the Hub cannot filter by date, it pages each author and search query newest first until `--since`, and each
`pipelineTags` query in `likes` order (and again in `downloads` order when `minDownloads` is set) until the metric falls
under the threshold, keeping only models created inside the window. Options: `--until`, `--max-pages` per query
(default 50), `--max-requests` per run (default 300; the Hub allows 500 requests per 5 minutes). It **pauses** on either
bound or on a 429 and keeps a `BACKFILL#<since>#<scope>` checkpoint (each query's cursor); running the same command again
resumes there, and a finished backfill reads nothing. Backfilled discoveries are `collected` like any other, so the router
delivers them at `maxItemsPerRun` (at most 25) per hourly run, oldest collection first.

### Starting Shipped

Nothing here has been deployed. In account 712236451410 with `AWS_PROFILE=papyrus-production`
(`aws sts get-caller-identity --query Account --output text` must print `712236451410`):

1. Merge, then build and upload both zips (the collector zip gained `monitoring_huggingface.py`; the router imports it too):
   `python3 infra/monitoring/build.py --upload "$CODE_BUCKET"` and `python3 infra/monitoring/build.py --router --upload "$CODE_BUCKET"`
   (each prints its `CodeKey`; the bucket is the stack's `CodeBucket` parameter).
2. Change set on `papyrus-monitoring` (reads first, then executes). Against the deployed stack it should show the two function
   code updates and the new schedules `papyrus-monitoring-huggingface-collect` and `-route` (plus the Shipped grants
   `RouterShippedIntakePolicy` if they are not deployed yet). Every other parameter is `UsePreviousValue`, which keeps
   `EditorUserPoolArns` (never omit it).
   ```sh
   aws cloudformation create-change-set --stack-name papyrus-monitoring --change-set-name huggingface-monitor \
     --template-body file://infra/monitoring/papyrus-monitoring.yaml --capabilities CAPABILITY_NAMED_IAM \
     --parameters ParameterKey=CodeKey,ParameterValue=<collector CodeKey> ParameterKey=RouterCodeKey,ParameterValue=<router CodeKey> \
       $(for p in $(aws cloudformation describe-stacks --stack-name papyrus-monitoring --query 'Stacks[0].Parameters[].ParameterKey' --output text); \
         do case $p in CodeKey|RouterCodeKey) ;; *) printf 'ParameterKey=%s,UsePreviousValue=true ' $p;; esac; done)
   aws cloudformation describe-change-set --stack-name papyrus-monitoring --change-set-name huggingface-monitor
   aws cloudformation execute-change-set --stack-name papyrus-monitoring --change-set-name huggingface-monitor   # after a human has read it
   ```
3. Seed the collector config (validated with the Lambda's own validator before it is written) and the router config.
   `TABLE` is in SSM `/papyrus/monitoring/table-name`.
   ```sh
   TABLE=$(aws ssm get-parameter --name /papyrus/monitoring/table-name --query Parameter.Value --output text)
   python3 infra/monitoring/seed_config.py --table "$TABLE" --monitor-id huggingface --source-type huggingface-models --file shipped-huggingface-config.json
   python3 infra/monitoring/seed_router_config.py --table "$TABLE" --monitor-id huggingface --file shipped-huggingface-router.json   # starts in dry-run
   ```
4. Check a dry run, then flip: `aws lambda invoke --function-name papyrus-monitoring-collector --cli-binary-format raw-in-base64-out --payload '{"monitorId":"huggingface","force":true}' /dev/stdout`, read the `RUN#` receipt and the router's dry-run receipts
   (`wouldDeliver`), then `seed_router_config.py --table "$TABLE" --monitor-id huggingface --set mode=live`.
5. Load history, dry run first, then apply (repeat the apply until it reports `complete`):
   ```sh
   papyrus monitors backfill --monitor huggingface --since 2025-10-25T00:00:00Z
   papyrus monitors backfill --monitor huggingface --since 2025-10-25T00:00:00Z --apply
   ```

Recommended `shipped-huggingface-config.json` (the pipeline tags are Shipped's three seeds; add `image-text-to-text` for multimodal
open weights). Sampled from the live Hub on 2026-10-25: it receives about 3,600 text-generation, 700 text-classification and
250 text-to-speech models a week, and of those a week or two old about 100, 24 and 17 a week have at least 5 likes or
5,000 downloads. Expect **about 145 a week from the thresholds, plus a few from the watchlist (150 to 170 in all)**, around
8,000 a year. `minLikes` 10 and `minDownloads` 10000 would give about 70 a week; 3 and 2000 about 250.

```json
{"sourceType": "huggingface-models", "sourceUrl": "https://huggingface.co/api/models",
 "pipelineTags": ["text-generation", "text-to-speech", "text-classification"],
 "authors": ["Qwen", "meta-llama", "google", "microsoft", "mistralai", "deepseek-ai", "nvidia", "openai", "allenai",
             "HuggingFaceTB", "ibm-granite", "moonshotai", "zai-org", "MiniMaxAI", "CohereLabs", "LiquidAI", "openbmb",
             "hexgrad", "ResembleAI", "canopylabs", "SparkAudio", "fishaudio", "kyutai", "nari-labs"],
 "search": ["decision"], "sort": "createdAt", "minLikes": 5, "minDownloads": 5000,
 "excludeTags": ["gguf", "mlx", "exl2", "exl3", "awq", "gptq", "bitsandbytes", "4-bit", "8-bit"],
 "excludeBaseRelations": ["quantized", "merge"],
 "excludeIdPatterns": ["gguf", "-(q|iq)[0-9]", "exl[23]", "mlx", "awq", "gptq", "abliterat", "uncensored", "bpw", "dflash", "comfyui"],
 "lookbackDays": 7, "pageSize": 500, "pagesPerQuery": 10, "intervalSeconds": 86400, "limit": 500}
```

Recommended `shipped-huggingface-router.json` (a watchlist name that does not exist on the Hub just returns nothing):

```json
{"mode": "dry-run", "decisions": "direct", "maxItemsPerRun": 25, "feedback": false,
 "rule": {"authors": ["Qwen", "meta-llama", "google", "microsoft", "mistralai", "deepseek-ai", "nvidia", "openai", "allenai",
                      "HuggingFaceTB", "ibm-granite", "moonshotai", "zai-org", "MiniMaxAI", "CohereLabs", "LiquidAI", "openbmb",
                      "hexgrad", "ResembleAI", "canopylabs", "SparkAudio", "fishaudio", "kyutai", "nari-labs"],
          "minLikes": 5, "minDownloads": 5000,
          "excludeTags": ["gguf", "mlx", "exl2", "exl3", "awq", "gptq", "bitsandbytes", "4-bit", "8-bit"],
          "excludeBaseRelations": ["quantized", "merge"],
          "excludeIdPatterns": ["gguf", "-(q|iq)[0-9]", "exl[23]", "mlx", "awq", "gptq", "abliterat", "uncensored", "bpw", "dflash", "comfyui"]},
 "publications": [{"publicationId": "shipped", "site": "shipped.anth.us",
                   "appsyncEndpoint": "https://6sw6454pozbgvdgm233gqkxsxu.appsync-api.us-east-1.amazonaws.com/graphql"}]}
```

The exclusions are the recommended block for Shipped: they remove quantisations, merges and wrappers but keep fine-tunes and adapters.
Check `read.skipped` on the first run; if a legitimate release is being dropped, narrow the pattern that matched it.
Read the result with the `RUN#` receipt (`read.requests`, `read.stoppedBy`, `read.skipped`, `new`) as in "Reading it", using `MONITOR#huggingface`.

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
- **Always pass `EditorUserPoolArns` explicitly.** Its template default is empty, so a deploy that omits it (or does
  not use `UsePreviousValue`) drops the email-sender membership recheck grant. The value for production is
  `arn:aws:cognito-idp:us-east-1:712236451410:userpool/us-east-1_1sQaEOwsH`.

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

### Outputs that are not ready (waiting for classifier)

A binding whose Cyclotron output has no runnable classifier yet (`pending_criteria`) answers `decide`
with HTTP 409 and the body `{"detail": "publication criteria are pending"}` (the machine API sends no typed code; the typed `criteria_pending` is accepted too). That is a per-binding outcome, not a stop condition: the router
skips that binding for the item (`route.notReady[pub]`, counter `skippedNotReady`), decides and
delivers the other bindings, and the sweep continues. It makes no Cyclotron call for the waiting
binding beyond one probe, so it uses no retries and no ceiling. If every binding is waiting, the item
is final `parked`. Any other 409 still stops the sweep.

Parking: one `PARK#<publicationId>` item per waiting publication holds `reason`, `since`, `nextProbeAt`,
`backoffSeconds` and the newest 25 skipped items. No call is made until `nextProbeAt`; then the next item
probes once, and a still-pending answer doubles the backoff (30 minutes up to 6 hours). When a probe
succeeds the park becomes `ready`, and each run first decides the parked items (up to `maxItemsPerRun`,
within the same per-run budget) and delivers positives, then removes the park. Items older than the
newest 25 are not backfilled. The run receipt carries `waitingForClassifier` (publication ids) and the
Monitoring page shows it on the router run.

## Router items

| `sk` | Meaning |
| --- | --- |
| `CONFIG#router` | Config (below) |
| `LOCK#router` | Lease (660 s, longer than the 600 s timeout), separate from the collector's `LOCK` |
| `ROUTE#<sourceId>#<rev6>` | `dryRun` (`count`, `validatedAt`, `requests.<pub>` = path, `requestId`, bytes, body; `contexts.<pub>` = `contextHash`/`reason`), `jobs.<pub>` (`requestId`, `jobId`, `checked`), `decision` (`decisionId`, `source` = id/revision/fingerprint, per-publication `output`, `label`, `fingerprint`, `version`, plus account, run, binding revision), `publications.<pub>` (`delivered`, `referenceId`, `attempts`, `lastError`), `final` |
| `DELIV#<pub>#<referenceId>` | A Reference this router delivered; feedback source. In `FEEDBACK#hn#pending` while feedback is outstanding |
| `TRIGGER#<pub>#<procedureKey>#<sourceId>` | A procedure trigger for this item: `status` (`starting`, `started`, `startFailed`, `notTriggered`, `skipped`, `deferred`, then the runner's `running`, `completed`, `failed` or `notRunnable`), the runner `request`, `runId`, a `reason` for `skipped` and `deferred`, the `automationId` when an automation governed the start, errors. Written only if absent, so each item starts each procedure once (`docs/procedure-runner.md`, `docs/automations.md`) |
| `MANUAL#<automationId>#<timestamp>` | A "Run now" of an automation, written by the CLI or the console (not by the router): who started it, the runner `request`, then the runner's `running`/`runId` and outcome, as on a `TRIGGER#` row (`docs/automations.md`) |
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

`decisions` is `cyclotron` (the default) or `direct`; a `direct` config takes no `cyclotron` block and may carry a
`rule` (`pipelineTags`, `authors`, `minLikes`, `minDownloads`) that limits what is delivered
([Hugging Face Hub monitor](#hugging-face-hub-monitor-huggingface-models)).

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

## Procedure triggers

A publication may list `procedureTriggers` and name its OpenAI key's SSM parameter
(`openaiKeyParameter`). After a delivery that created a new Reference, the router starts each named
procedure once for that item by invoking the procedure runner asynchronously, and never waits for it.
A Reference that already existed starts nothing. Before a start the router reads the site's `Automation`
record for the trigger (`listAutomations`, one read per publication per sweep): a disabled automation starts
nothing (`skipped`), one at its `maxConcurrent` is deferred and retried on later runs (`deferred`), and the record's timeout goes with the
request. With no record, or one the router cannot read (including a denied IAM call), it starts exactly as
before. See `docs/automations.md`, and `docs/procedure-runner.md` for the config, the input placeholders and
the runner.

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
| `appsync:GraphQL` per API per field, three APIs (parameters `AnthUsApiId`, `PapyrusApiId`, `ThreatIntelApiId`); the same fields on Data Parade (`DataParadeApiId`) sit in `RouterDataParadeIntakePolicy`, and its `relevance_decision_is` grants in `RouterDecisionRelationPolicy`; likewise Pilobolus (`PilobolusApiId`, `RouterPilobolusIntakePolicy`) and Shipped (`ShippedApiId`, `RouterShippedIntakePolicy`) | Query: `getKnowledgeImportRun`, `getMessage`, `getModelAttachment`, `getReference`, `getReferenceAttachment`, `getSemanticRelation`, `itemBySlug`, `listKnowledgeCorpuses`, `listKnowledgeCorporaByRoleAndName`, `listReferences`. Mutation: `completeModelAttachmentUpload`, `createKnowledgeImportRun`, `createMessage`, `createModelAttachmentUpload`, `createReference`, `createReferenceAttachment`, `createSemanticRelation`, `updateReferenceAttachment` |

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


# The Monitoring page (PPY-31ba52)

Editors and admins read this pipeline in the newsroom at **Administration, Monitoring**
(`/newsroom/administration/monitoring`). The page is read only. It shows the feeds watched, recent
collector and router runs, the collected queue with each item's routing state, what the shared
Cyclotron judged relevant to the viewing publication (with confidence, where the Cyclotron reports
one) and whether it reached that publication's References queue (with a link), the router mode
(live or dry run, feedback on or off) and observed decision counts.

The page covers only the monitors whose `CONFIG#router` `publications` include the viewing site's
publication (found by its AppSync endpoint). Other monitors are named in a collapsed "Not routed to
this site" note, with no items, runs or counts; an admin's `scope: all` combines every monitor. The
function cannot Scan, so the monitors it looks at are `MONITOR_IDS` in `monitoring_view.py`
(`hn`, `ttab`, `huggingface`), overridable with `PAPYRUS_MONITORING_MONITOR_IDS` (comma separated);
add a new monitor there. Reading them needs no new IAM: the same `GetItem` and `Query` on the one table.

## Access design

`monitoringOverview(scope)` is a GraphQL query in every site's own AppSync API, admitted to the
`editor` and `admin` groups only. It resolves to the `papyrus-monitoring-view` Lambda
(`amplify/functions/monitoring-view/`, logic in `src/papyrus_content/monitoring_view.py`).

- The function's role holds `dynamodb:GetItem` and `dynamodb:Query` on tables named
  `papyrus-monitoring-MonitoringTable-*` and their `routing` index (no Scan, no write, no other table),
  and `ssm:GetParameter` on `/papyrus/monitoring/table-name`.
- That parameter is written by the monitoring stack (`TableNameParameter`), so a site backend needs no
  deploy-time link to this stack. A site in an account without the parameter shows "not set up".
- The browser sends a query over the signed-in session. It never sees a table name, key or secret.
- The function checks the caller's groups again. The default scope is the viewing publication, found by
  matching the site's AppSync endpoint to the router config; items judged not relevant to it are counted,
  not listed. `scope: all` (every publication's judgements) is admin-only and enforced in the function.
- The response is projected field by field. Cyclotron endpoints, the invoker role ARN, the Cyclotron account
  and run ids, and AppSync endpoints are never returned.

Why not an endpoint on this stack: it would need an allow-list of site backend role ARNs (they change
per deploy) and the sites would still need their own group check. One resolver in the site's API keeps one
authorization point and one least-privilege grant.

## Data the page needs

- `confidence` per publication is kept in the router's decision receipt (`ROUTE#...`.`decision`.`publications`)
  when the Cyclotron reports it between 0 and 1.
- Old `ceilings` fields in `CONFIG#router` are ignored and are not returned to Monitoring.
- Usage counts the decisions this router recorded (UTC days); incomplete bounded history reads are labeled as lower bounds without implying sort order. It is the router's view, not a Cyclotron model-usage meter.
