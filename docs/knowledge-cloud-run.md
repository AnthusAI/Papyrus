# Knowledge cloud run

The weekly [knowledge run](knowledge-workstation-run.md) as an unattended job in AWS: BERTopic, a Jev entity step, an AI review, the snapshot and its archive, the wiki and the projection, on a schedule, with nobody's workstation involved. Status: Beta. Story PPY-dca7cd; Shipped (`https://shipped.anth.us`) is the first publication.

The workstation runbook stays the reference for what each step does and why. This page is about the machine that runs those steps.

## What runs

```text
EventBridge Scheduler (weekly)
  -> Step Functions Standard state machine
       corpus-sync -> topic-model -> typed-extraction -> publish-run -> ai-review
       -> publish-relations -> snapshot -> archive -> wiki-sync -> projection
       (each arrow is a Fargate task, with retries; any failure ends the run, never reaching projection)
```

Each stage is one ECS Fargate task (ARM64, CPU, 4 vCPU and 16 GB to start) from one image: Papyrus, Biblicus (pinned commit) and BERTopic on pinned versions, with the BERTopic embedder baked in (`HF_HUB_OFFLINE=1`, nothing is downloaded during a run). The entity step calls Jev over the network, so a task needs the TypeSafe key (see `typed-extraction` below). The task command is `papyrus knowledge cloud-run --stage <name>`.

| Stage | What it does (the runbook step) |
| --- | --- |
| `corpus-sync` | Checkout of the site repository at the commit of the Amplify app's latest successful deploy (see below), `corpus export`, `reindex`, extraction snapshot (steps 1-3) |
| `topic-model` | BERTopic, weekly trends, topic identity against the previous run kept in S3 (steps 4-6) |
| `typed-extraction` | Front-matter import, registry, `papyrus knowledge extract-entities` (Jev decides which candidate names are real, what kind they are and whether they deserve a page; steps 7-8) |
| `publish-run` | Import clusters, entities and relations; then record the run as next week's `previousRunId` (steps 9-10) |
| `ai-review` | GPT-6 Luna reviews the extractor's entities, new clusters and relations (step 11); see below |
| `publish-relations` | Import again, so relations between entities accepted by the review land |
| `snapshot` | `knowledge snapshot` to the site bucket, no `--reproject` (step 12) |
| `archive` | `knowledge archive` for the week, never `--replace` (step 13). A week that already has an entry keeps it (entries are immutable), so a second run in the same week skips this step |
| `wiki-sync` | A dry run (`wiki sync --vocabulary config/vocabulary.yml --retire --run-id ... --json`), which the [preview gate](#the-preview-gate-bulk-writes-wait-for-a-person) judges; if it proceeds, `wiki sync ... --apply`, then `wiki publish --all-drafts --actor ai --no-trigger` (step 14). Only the vocabulary's kinds get pages, and only concepts whose [page answer](knowledge-snapshot.md#page-answer) is not no; pages of other kinds, or of a concept whose answer turned no, are retired and listed in `runs/<week>/retired-wiki-items.json`, and the `projection` stage removes their pages first (`project --unpublished-items`, run with the image's papyrus) ([public wiki](public-wiki.md#public-kinds)) |
| `projection` | `ops content project --all` under the projection lease and the deletion guard, never `--allow-deletions` |

Two differences from the runbook order: the AI review comes after the import, because it reviews what the import created, and `wiki publish` is told not to project, because `projection` does that once, last.

### Trend ideas (optional, off by default)

After `projection` the state machine can run one more task, `trend-drafts`: `papyrus ideas trends --site <publication> --snapshot <published index.json> --store items --max 2` ([idea pipeline](idea-pipeline.md#trend-stories)). It files ideas as Items at the `idea` stage (the Idea column of the Stories board) and raises one soft review request; nothing is published. It is `infra/knowledge-run/trend_drafts.py`, baked into the image, and it is a gate in the state machine, not a stage of `papyrus knowledge cloud-run`.

- **Switch.** Three CloudFormation parameters on the stack, all inert by default: `TrendDraftsEnabled` (`false`), `TrendDraftsEndpoint` (the publication's AppSync GraphQL address) and `TrendDraftsSnapshotUrl` (the published `.../_data/knowledge/index.json`). While `TrendDraftsEnabled` is `false` the execution goes from `projection` to `Done` and no task starts.
- **Fresh snapshot only.** The step reads the published address, not a local file (a local snapshot has no item URLs or summaries). The knowledge snapshot is weekly: the `snapshot` stage stamps its `asOf` with the Monday of the run's ISO week, whatever day the run starts. The published snapshot counts as this execution's when its `asOf` is the execution's start date (UTC), or at most `TREND_DRAFTS_MAX_AGE_DAYS` (default 1) before it, or that Monday. So the scheduled run, a daily run and a run started by hand all draft, and a snapshot of an earlier week is skipped. The script checks the published `asOf` up to 3 times, 60 seconds apart (the CDN may lag the projection). If it is still not one of those dates, the step logs `trend-drafts: skipped: the published snapshot is stale: ...` and stops. Set the age with `trendSnapshotMaxAgeDays` (0 to 7) in the site's `knowledgeRun` block.
- **Trend window.** The command chooses it per entity from the weekly history (1, 2, 4, 8, 16, 32, ... weeks, as long as the entity's full history leaves four weeks of baseline; [idea-pipeline.md](idea-pipeline.md)), so there is nothing to set. `trendWindowDays` and `TREND_DRAFTS_WINDOW_DAYS` are retired: the step ignores them, and the stack accepts the settings if a site config still has them but sets no variable.
- **Never fails the run.** The script exits 0 on every problem and logs `trend-drafts: skipped: <reason>` or `trend-drafts: failed: <reason>`; the state also catches any task error into `Done`, with no retry. The alarms do not see it; read the task log (`trend-drafts` prefix) after the first runs.
- **Key and permissions.** The OpenAI key comes from the SSM SecureString named by `openAiKeyParameter` (`/papyrus/shipped/openai-api-key`), read by the task role at run time and given only to the command's environment. The task role needs nothing new: `ssm:GetParameter` on that parameter (the AI review reads it too) and `appsync:GraphQL` on the publication's API (`SignAppSyncRequests`) already cover what the command uses under IAM (listing stories, sections and review requests, filing Items, and the review-request mutation).
- **Repeat runs.** The command reads the site's earlier ideas as Items (and, until `papyrus ideas migrate-proposals` has run, its old story drafts through the read-only operator query `listStoryDrafts`; [reader-steering.md](reader-steering.md#operator-filing)), so a second execution does not file a near-duplicate or an idea with the same targets. On top of that an entity that already has an idea, in any state, anchors another only when its evidence is materially stronger than what that idea reported (no day count; `trendCooldownDays` and `TREND_DRAFTS_COOLDOWN_DAYS` are retired and ignored). The task role's `appsync:GraphQL` on `Query/fields/*` already covers the query. Deploy the backend that has `listStoryDrafts` before the image that uses it (it is still read for sites that have not migrated); until then the step logs `trend-drafts: failed: ...` and files nothing.

### Monitor stories (not a step of this run)

The knowledge run has no monitor-stories step. It had an optional one (a `monitorStories` block in `knowledgeRun`, a `MonitorStoriesEnabled` stack parameter, `infra/knowledge-run/monitor_stories.py`); it was retired on 2026-11-10 because the monitoring router now drafts monitor stories every day for every publication, with no stack and no per-site setting ([monitoring-cloud.md](monitoring-cloud.md#monitor-stories-daily)), planning once and drafting each candidate from a queue, and the step could only file the same ideas a second time. Its post-run step also failed on every run with `KeyError: 'run'`. A `monitorStories` block that a site file still carries is accepted and ignored. To write up monitored items by hand, run `papyrus ideas monitor-stories --site <publication> --store items` ([idea pipeline](idea-pipeline.md#monitor-stories)).

- **Excluded source hosts (trend-drafts).** `"excludedSourceHosts": ["ipwatchdog.com"]` in the `knowledgeRun` block (lowercase host names, no scheme or path; subdomains match) becomes `KNOWLEDGE_EXCLUDED_SOURCE_HOSTS` (comma-separated) in the task, and the trend-drafts step passes each host to its command as `--exclude-host`. Cited Trends never offers or cites such an item, though the host's items still count in the statistics ([idea pipeline](idea-pipeline.md#excluded-source-hosts)). Papyrus does not classify hosts by kind, so the site lists each host.
- **Key and permissions (trend drafts).** The OpenAI key from the SSM SecureString named by `openAiKeyParameter`, read at run time and given only to the command's environment; only `gpt-6-luna` is used. The task role needs nothing new.

### Monitor records (optional, off by default)

A monitor ([monitoring-cloud.md](monitoring-cloud.md)) can deliver models, say from the Hugging Face Hub, as pending References for a person to judge. They are signal before anyone has judged them, so a site can have the run **count them as data**: in entities and in the weekly trends, and never as pages or as members of topic-model clusters. The setting lives in the site's `knowledgeRun` block of `infra/site.json`, like `conceptKinds`:

```json
"knowledgeRun": {
  "monitorSources": ["huggingface"]
}
```

`monitorSources` (`huggingface`, `routed`, or both) turns it on; by default **every record counts, all history, however old and however many**. `monitorWeeks` (1 to 260) is an optional override that limits how far back a record counts; leave it out and the stack sets no `KNOWLEDGE_MONITOR_WEEKS` and `corpus export` gets no `--monitor-weeks`. Without `monitorSources` nothing below happens and the snapshot is byte for byte what it was. The stack sets `KNOWLEDGE_MONITOR_SOURCES` and `KNOWLEDGE_MONITOR_WEEKS` on the task; `cdk deploy` the stack after changing them.

| Stage | What changes |
| --- | --- |
| `corpus-sync` | `corpus export --monitor-sources huggingface --monitor-weeks N --corpus-key <publication> --as-of <Monday> --monitor-records-out <run>/monitor-records.json`. Every current Reference of the publication's corpus whose address is the Hub and whose curation state is not `rejected` (`pending` and `accepted` both count) and whose **source date** (the model's `createdAt`) is inside the window becomes a row of `monitor-records.json`, kept with the week's run state in S3. The record's Hub fields come from the Reference's own `discoveryDetails` (no further query). **It does not become a corpus document**: records are data for counts and relations, and the topic model reads only the site's own items (see `topic-model` below). There is no cap on the number of records: the export reads every Reference page by page, newest first, so the weekly counts cover the whole history (with `--monitor-weeks N` only the last N weeks). |
| `topic-model` | **Records are not documents.** The topic model reads only the site's own items. On 2026-10-26 the records were corpus documents and 5,000 Hub model lines split into 27 maker-named clusters ("NVIDIA AI Models", "LiquidAI LFM models") that drowned the four editorial ones (Decision models, Open-weights language models, Open text-to-speech models, Safety and guard models). `corpus export --records-in-topic-model` brings the old behaviour back for an experiment; the cloud run never passes it. |
| `typed-extraction` | The entity step reads only the site's items; entities of records are never AI-extracted. It asks Jev, so the task reads the TypeSafe key from the SSM SecureString named by `decisionKeyParameter` (`KNOWLEDGE_DECISION_KEY_PARAMETER`, default `/papyrus/shared/typesafe-api-key`) and gives it only to that command's environment as `TYPESAFE_API_KEY`; the task role gets `ssm:GetParameter` on exactly that parameter. The calls it paid for are in the stage's cost in the ledger (tokens per model; the dollar figure stays `null` until `model_prices.json` has a price for `jev-1.13.0`). |
| `publish-run`, `publish-relations` | `--monitor-records <file>` adds the **structured entities and relations**, deterministically, with no AI review (below). |
| `ai-review` | Record titles (model ids) count as member titles, so a cluster of Hub models can be named. Source facts are `confirmed` already, so no entity or relation of a record is reviewed. |
| `snapshot`, `archive` | `--monitor-records <file>`: records count in clusters, entities and weekly series (below). |
| `wiki-sync` | `--monitor-records <file>`: an entity that only records mention gets **no wiki page**, and no page lists it as related. |

**Structured entities.** Each record links (`mentions` from the Reference, marked `knowledge.record_mention`, always confirmed) to an entity per Hub field: the model (`model--org-name`, named by the model id), its maker (the Hub author, `maker--org`), its licence (`licence--apache-2-0`; the Hub's `other` and `unknown` are not licences) and its task (the pipeline tag, `task--text-to-speech`). An existing entity of the site is matched first by key, so the entities of the site's own items are reused; a new one is accepted by `ai` under the name `Hugging Face Hub import`. A rejected entity is never linked. The Hub's platform (`platform--hugging-face`) is deliberately not linked: it would swamp the platform's own weekly counts.

**Structured relations.** A base model the Hub names becomes a `built_on` relation from the model to its base, confirmed, with `subtype` (`finetune`, `quantized`, `adapter`, `merge` or `declared`), `evidence` (the Hub card) and `provenance` (`from the Hugging Face Hub`) in its metadata, shown on the entity file's neighbour row. Both ends must already be entities: a model with a record in the window, or an accepted entity named by that id. A base model that is neither stays in the record. Nothing is superseded or deleted on the way, except that a record whose Hub fields changed supersedes the links it no longer has.

**In the snapshot.** Records are dated items for the counts of **entities**, so `itemCount`, `series8` and the four-week change of an entity include them (a cluster counts only the site's own items, because the topic model does not read records, so a cluster row has no `recordCount` unless `--records-in-topic-model` is used), and, with no `monitorWeeks`, the weekly counts (`weeksOfHistory`) reach back to the oldest record. Beside that: an entity or cluster row has `recordCount` (how many of its items are records), the entity file lists the newest records apart from the site's items in `relatedRecords` (`title` = model id, `url` = the Hub card, `publishedAt`, `summary` from the structured fields, `source`, `provenance`), and `relatedItems` stays the site's own pages. An entity only records mention has `href: null`, and appears at all only when at least two records link it or it takes part in a confirmed relation, so a lone model does not clutter the map. Without records none of these fields exist.

**A run that adds nothing costs minutes.** The import used to look at every record on every pass (`typed-extraction`, `publish-run` and `publish-relations` each run it, and the first two run it twice, a dry run and the apply): two index queries per accepted entity to find the links that already existed, and a point read per planned row. With thousands of records that is tens of thousands of requests per pass, one after another. On Monday 2026-10-26 (3,709 records) the run took 3 h 40 min against the usual 45 minutes. Now:

- **Ledger.** `corpus/monitor-import-ledger.json` in the state bucket (next to `knowledge-run.json`, so it outlives the week's run directory) holds, per record, a hash of what the import reads of it (its identity and address, the model, maker, licence and task entities, its base models and their relation) and the base models it could not place on the map. The import (`--monitor-ledger FILE`, set by the stage) skips a record whose hash is unchanged, and re-imports one that is new, one whose hash changed, and one whose waiting base model has reached the map since (so a `built_on` relation appears when the base arrives). Likes, downloads and dates are not in the hash. The ledger is saved only after the import was applied, so a failed run changes nothing and the next one retries the same records; a record that left the window leaves the ledger. A file that is not a ledger stops the import; it is never overwritten.
- **Only what is needed is read.** The links of a changed or new record are read by its own subject-state index query (one per record, none for a skipped one) and the links of the published items by one query per item, not two queries per accepted entity. Rows read this way serve as the point reads of the planned links.
- **Parallel.** Independent reads and writes run over up to 8 clients (`--parallel N`, 1 to 32; one connection per worker thread). Entities are written before the links that point at them. The same applies to the stages that load every link of every accepted entity (`ai-review`, `snapshot`, `archive`, `wiki-sync`). There is no multi-record mutation in the API, so the write path is parallel single writes.
- **`KNOWLEDGE_MONITOR_FULL=true`** (the site's `knowledgeRun.environment`, or `--monitor-full` by hand) ignores the ledger and imports every record again, the old behaviour; use it after anything changed entities behind the ledger's back (a restore, a hand edit) or after `IMPORT_VERSION` in `monitor_ledger.py` was bumped for a change in what a record imports (the hash includes it, so a bump re-imports everything by itself).

Measured by counting requests on a fixture of the same size as Shipped's (3,709 records, 600 items; `pytest -s src/papyrus_content/knowledge_snapshot/monitor_import_scale_test.py`), one pass of the import:

| One pass | Before | After |
| --- | --- | --- |
| First import (nothing written yet): 4,766 entities, 17,376 links and relations | 22,142 reads + 22,142 writes, one at a time | the same requests, 8 at a time, plus 4,309 link queries |
| Nothing new | 11,458 requests (9,604 link queries, 1,800 point reads, 54 list pages), one at a time | 654 requests (600 link queries, 54 list pages), 8 at a time |
| 10 new records | the same 11,458 plus 52 writes | 768 requests (610 link queries, 54 list pages, 52 reads, 52 writes), 8 at a time |

Expected run time, assuming 60 ms for an AppSync round trip (about what the counts above need to reproduce Monday's run; **an estimate, not a measurement of the new code**, and 8 times faster only if AppSync keeps up): a run with no new records adds about 6 minutes to the 45 it takes without records (the five import passes about 40 seconds, the four stages that load every link about 1 minute each, the export about half a minute), against about 100 minutes before; 10 new records add seconds to that; a first import of 3,709 records adds about 12 minutes (the writes about 6, the rest as above), against about 2.4 hours computed the same way (Monday took 175 minutes beyond a normal run; the 60 ms is rounded to fit that loosely, not fitted exactly). Read `publish-run` in the task log: `recordsImported`, `recordsUnchanged`, and the `changes` lines.

**Verify on the next run.** In the `corpus-sync` task log: `knowledge corpus-export ... N monitor records`. In S3: `runs/<week>/monitor-records.json`. In the `publish-run` log: `recordsImported`, `recordsUnchanged`, `recordNodesCreated`, `recordLinks`, `recordRelations`, `recordBaseModelsOffMap`. On the site: `_data/knowledge/index.json` entities with `recordCount`, `entities/<key>.json` with `relatedRecords` and `built_on` neighbours with `subtype`, and no new `/wiki/` page for a Hub-only entity. A Reference delivered before `discoveryDetails` existed needs `papyrus references backfill-monitor-deliveries` once.

**Routed records (`monitorSources: ["routed"]`).** The shared relevance router delivers stories from any monitor (Hacker News today; RSS or arXiv later) to many sites. Each delivery is, in the site's own knowledge corpus (`knowledge-corpus-<publication>`), a **pending `Reference`** whose `sourceUri` is the story's address, `title` its title and `sourcePublishedAt` its date, whose `discoveredByMonitorId` names the monitor (`hn`, ...) and, for sources with structured fields, whose `discoveryDetails` holds them (no provenance Message is written). `routed` turns every such Reference (not `rejected`, dated inside `monitorWeeks`, and with a `discoveredByMonitorId` other than the Hub) into a monitor record whose `source` is that monitor id. The same rules as Hub records apply: records are data, not topic-model documents; they count in an entity's `itemCount`, `series8`, `recordCount` and `relatedRecords`; an entity only records mention gets no wiki page; a record's provenance reads `routed from the hn monitor`, which is what Cited Trends calls the source. A Reference no monitor delivered (imported by hand, say) is not a record. A story that links to a Hub card is a `huggingface` record when that source is also on, and is otherwise treated like any other routed story.

A routed story has no structured fields, so it is **linked by its text**: the title, plus a `summary` or `excerpt` when the monitor stored one in its `details` (HN stores neither today). The text is matched deterministically, locally and without a model, against the display names and aliases of the entities that are **already accepted** on the site's map: case-insensitive, on whole words (`GPT-4` is the words `gpt` and `4`), a one-word name needs at least three characters (so `Go` or `AI` never match by accident). A routed record **never creates an entity** and never links a generated or rejected one. Each match is a `mentions` relation marked `knowledge.record_mention`, confirmed, with the provenance above. No entity extraction is needed here: the map already holds the names an editor accepted, so finding those names is a lookup, and extraction would only propose names the rule forbids us to create. The matches are part of the import ledger's hash, so an entity that reaches the map later links the stories that name it on the next run, and an unchanged record costs nothing. A record is matched against the map as it stood at the start of the import, so an entity the same run creates (say from a Hub model) is picked up by the next run. The weekly promotion suggestion considers Hub records only.

**Promotion.** A person turns a record into a normal item with `papyrus references promote <reference id> --section <section>` ([monitoring-cloud.md](monitoring-cloud.md#promoting-a-record-to-an-item)): a **draft** article carrying the source link and the record's facts, for an editor to write and publish. The weekly run can also ask for a first look: set `monitorSuggestions` (0 to 20, default 0 = off) in `knowledgeRun` (it sets `KNOWLEDGE_MONITOR_SUGGESTIONS`) and the `ai-review` stage raises **one soft review request** per week (`rr-monitor-records-<publication>-<week>`, seven days, idempotent) that lists that many records. The first pass has no model: among the records of the last four weeks that no item carries yet, the Hub's own interest decides (likes, then downloads, then the model id). The request asks nobody to publish anything; the stage log `ai-review.json` has the same list under `monitorSuggestions` (`status` `requested`, `none` or `not_raised` with the error). A site that cannot take review requests, or a missing records file, never fails the run.

### Reference documents (optional, off by default)

A site can ask the run to treat its **References with extracted text** as corpus documents, so the topic model, the entity extractor, the Knowledge Map and the wiki work on the sources themselves and not only on the few articles it has published. This is a different, explicit source from the monitor records above: **records stay data and are never documents** (a Reference a monitor delivered is skipped here even when it has text, and a rejected Reference is skipped too); a Reference somebody added as a source is a document.

- **Opt in, per site.** In `knowledgeRun`: `"referenceDocuments": {"enabled": true, "mediaBucket": "<CMS media bucket>", "extractor": "markitdown"}` (`extractor` defaults to `markitdown`). The texts are read from `s3://<mediaBucket>/corpora/<corpus key>/extracted/<extractor>/raw/<reference id>/extracted_text_raw.md`; the corpus key is `corpusKey` or the `siteId`. Without the block, or with `"enabled": false`, nothing changes: no variable, no permission, the template is what it was. The task gets `KNOWLEDGE_REFERENCE_DOCUMENTS_BUCKET` and `KNOWLEDGE_REFERENCE_DOCUMENTS_EXTRACTOR`, and its role `s3:GetObject` on exactly that prefix and `s3:ListBucket` on the bucket limited (`s3:prefix`) to the same prefix. No write.
- **`corpus-sync`.** `corpus export --reference-documents-bucket B --reference-documents-extractor X --reference-documents-out <run>/reference-documents.json`. The export lists the prefix once, reads the Reference rows of the corpus, and writes `ref-<reference id>.md` for each current Reference that has a non-empty text. A Reference with no text, such as a citation-graph stub that is only a title, is not a document. Each file carries `biblicus.id` (a UUID derived from the Reference id), `papyrus_reference_id`, `kind: reference-document`, the Reference's `url` (its source address) and `title`, and `dates.published_at` from the Reference's source date (a Reference with none is undated and does not count in the weekly series; the import date is not used in its place). The summary line reports how many were downloaded, how many were unchanged and how many Reference had no text.
- **Incremental.** Each file records the S3 ETag of its text (`source_etag`). The corpus, `raw/papyrus` included, is kept in the state bucket between runs, so a text whose ETag is unchanged is read from the file already there and not downloaded again; a changed text is downloaded; a Reference that stops being a source (rejected, deleted) has its file removed.
- **`topic-model`** reads these files with the site's items (the Biblicus extraction of the corpus does not tell them apart). **`typed-extraction`** extracts entities from them. Jev's answers are cached by name, passages, vocabulary and model under `corpus/analysis/entity-decisions/cache.jsonl` in the state bucket, so a week with no new texts asks Jev nothing.
- **`publish-run`** (`--reference-documents FILE`) turns the Biblicus ids back into Reference ids (clusters and entities) and links each extracted entity from the **Reference**: a `mentions` relation with `subjectKind` `reference`, marked `knowledge.reference_mention`, `linkSource` `extractor`, unconfirmed. The AI review confirms those links with the entity it accepts (the same way as for items) and rejects them with a rejected entity.
- **`snapshot`, `archive`, `wiki-sync`** (`--reference-documents FILE`) count each document as a dated source of its entities that, unlike a record, bears a page: an entity mentioned by a Reference document has a wiki page, and its `relatedItems` lists the Reference with its title and its source address, so the page cites it. Without the flag a Reference counts for nothing.

**Accepted References as documents (an alternative selection).** A site whose `corpora/` files are gone, or whose sources arrive through monitors, can choose a different selection: every **accepted** current Reference of the corpus is a document, whichever monitor delivered it, and its text is the `curation-text` payload (the editor's corrected text when the curation card names one). Pending and rejected References are never documents in this mode. It is reachable as `papyrus knowledge corpus export --corpus-key K --reference-documents-accepted --reference-documents-out FILE`, and in the cloud run by setting `KNOWLEDGE_REFERENCE_DOCUMENTS_ACCEPTED=true` (a site sets it through `knowledgeRun.environment`; it needs no `mediaBucket` and no bucket permission, because the texts are read through the data API's download slots like any other attachment). It cannot be combined with `--reference-documents-bucket`.

- **Nothing is silent.** A Reference with no text is listed by id and reason: one `knowledge corpus-export reference-without-text <id> <reason>` line each in the task log, `referenceWithoutText` in `--json`, and `withoutText` in `reference-documents.json`. The reasons are no curation text attachment, an empty text, and a text that could not be read.
- **Zero documents is an error.** The export fails, writes nothing and removes nothing, so the stage fails before the state is pushed or pruned. An empty answer is not evidence that the sources are gone. A Reference that is still accepted keeps its earlier `ref-<id>.md` even when its text could not be read this time; the file of a Reference that stopped being accepted is removed.
- **Documents are not records.** In this mode an accepted Reference that a monitor delivered is a document and is left out of `monitor-records.json`; counted as both, the record would win and hide the wiki pages of the entities only it mentions. The other monitor-delivered References stay records.
- **Mentions.** `publish-run --reference-documents` links each entity extracted from such a Reference with a `knowledge.reference_mention` relation from the Reference, as above, so an accepted monitor-delivered Reference ends up with real Reference-to-concept mentions.

**Cost and time.** The first run reads every text once (about 70 MB for the 2,764 texts of the AI/ML research corpus) and extracts entities from each; the entity step asks Jev once per distinct candidate name, so its time and cost follow the number of new names, and it is not measured for this corpus yet. The site raises the per-stage timeouts in `stageTimeouts` (the example sets `typed-extraction` to 12 hours). The cache is uploaded with the corpus when the stage ends, also when it fails, but a stage that times out is killed before it can: raise the timeout rather than rely on a retry.

### The candidate filter (before the AI review)

`publish-run` filters the extractor's candidates before any node is made, so a plain word never becomes a concept for a person or the AI review to throw away. It is given the site's `config/stop-words.txt` and `config/vocabulary.yml` (`--stop-words`, `--vocabulary`; the run passes both) and applies three rules to a candidate that would be a **new** node: a name made only of stop words (the file the topic model reads, plus the English list it starts from); a one-word, letters-only name that the extraction mostly writes in lower case and that turns up in more documents than the upper fence of the document counts of all distinct names (third quartile plus one and a half times the inter-quartile range, recomputed from each run's own extraction, so there is no fixed number); and a kind the vocabulary does not declare. A name with capitals or digits (`GPT-4`) and a multi-word name (`dark patterns`) is never judged a common word. A node already on the map is never filtered or changed. The import prints one `dropped <kind> <name> <reason>` line per dropped candidate, counts them as `candidatesDropped.<reason>`, and lists them in `--json` under `dropped`. A one-word concept that is real but always written in lower case in a very common spot would be dropped too: read the `dropped` lines after a run, and add a name to the site's vocabulary or the map by hand if it was wrongly lost.

**Rejected names.** A name has one identity in the run, the one its concept key is made of (`GPT-4` and `GPT 4` are `gpt-4`); the node lookup used to fold only case and white space, so `GPT 4` missed a rejected `GPT-4` and a link was written to the rejected concept. Now every spelling of a rejected name (by a person, or by the AI review, on the node or any alias) is dropped before it can make a node or a link, is reported as `rejected earlier`, and changes nothing on the map. A rejection is specific to the kind. A spelling of an accepted name links to the accepted concept and makes no second one.

### The AI review

For each unreviewed entity (`generated`), each new cluster and each proposed relation between accepted entities, the stage gives GPT-6 Luna (the Responses API, a structured answer, `store: false`) short snippets of the site's own text and asks for `accept`, `reject` or `unsure`. The model never decides alone:

- An `accept` of an entity counts only if the evidence it quotes is a verbatim piece of a snippet it was given, names the thing, says more than the name, **and is about the thing**: the model answers `about`, true when the quote introduces, defines, describes or reports on the thing and false when the thing is only named in passing (a baseline in a comparison, one of a list, a citation). The snippets surround each mention, so a quote that only names the thing used to pass. A refused accept is recorded as `unsure` with the part of the gate that decided (`gate` in `ai-review.json`: quote not in the snippets or does not name the thing, named in passing, or quote names the thing and is about it). For a relation (`member_of` too) the quote must name both ends. A cluster is accepted only with a name and at least three quoted member titles.
- Anything else is treated as `unsure` and the row is left as the extractor left it. `reject` is for junk (sizes, file formats, generic nouns).
- Everything is recorded as accepted or rejected by the actor `ai` (shown as "AI" on the site) with the day. The decisions, quotes and reasons of each run are kept in `runs/<week>/ai-review.json` in the state bucket.
- The OpenAI key is read from the SSM SecureString `/papyrus/<publication>/openai-api-key` by the task role at run time. It is never in the image, the template or a log. `KNOWLEDGE_REVIEW_MAX_CALLS` (default 150) is the named setting that caps the calls of one run. **Budget rule:** each kind of work (entities in batches of 20, clusters in batches of 8, relations in batches of 20) is owed what it needs up to a max-min fair share of the cap (the kinds that need little are served in full, the others share what is left equally); entities run first and may use every call except what clusters and relations are owed, clusters may use every call except what relations are owed, and relations may use the rest, so a long list of entities cannot starve the later work and a call a later kind does not need goes back to the pool. The log records `budget`: the cap, the calls each kind `needed`, was `owed` and `used`.

`config/review-guidance.md` of the site's [committed settings](#committed-settings), if it has one, is appended to the instructions: the publication's editors' preferences, kept out of code.

## The preview gate: bulk writes wait for a person

`wiki-sync` is the stage that writes Items in bulk, so it plans first (PPY-84b0dd; `knowledge_cloud/preview_gate.py`). On 2026-11-02 a run published 1,366 wiki pages nobody had looked at; this is the check that would have stopped it.

- **A site's first run is a preview.** With no earlier run to compare with, nothing is written. A **hard-gate review request** goes to the [Notification Center](notification-center.md) (raised by `knowledge-run`, subject type `batch`, id `rr-wiki-sync-<publication>-<plan fingerprint>`): the headline says how many pages the run would write and that nothing has been written, and the text lists the counts by page kind and entity kind (`entity/maker:create 40`, the biggest first) and a sample of titles, within the request's 2,000 characters. It appears as an Accept / Reject card; `papyrus reviews list --raised-by knowledge-run` and `papyrus reviews show --id ID` read it from a terminal.
- **Approving needs no AWS login.** A person accepts the card in the console, or runs `papyrus reviews answer --id ID --decision approve` after `papyrus login`. Both go through the site's data API, where only editors and admins may answer. An answer by an agent (`by` starting `agent:`) does not count. Nothing starts a run on accept: the next scheduled run plans again, reads the answer, and goes through. An approved plan is part of the site's history from then on, and the same plan (same pages, same actions) always goes through.
- **A later run proceeds unless its output differs sharply from the site's own history.** For each series (pages to create, update, revise or retire, by kind, and the total) the earlier runs' counts predict this run's: their mean (Jeffreys, so a series never seen has a small nonzero rate) and spread (the sample variance once there are two runs, never below a Poisson, with an allowance of `1 + 1/n` for the uncertainty of the mean). The run is held when a series' tail probability (a negative binomial with that mean and variance) is below `1 / ((n + 1) * k)`: the chance that the newest of `n + 1` runs is the biggest of them, shared among the `k` series that wrote anything. There is no fixed cap or window: a site that swings from 5 to 80 pages a run is not held for 70, a site that writes 20 every time is, and the more runs a site has the rarer an event must be to hold it. A run that wrote nothing counts as zero in the history.
- **A held run writes nothing, and is resumable.** The stage prints the plan, writes `runs/<week>/wiki-sync-preview.json` (the decision and the whole plan) and returns `status: held` in the ledger; no `wiki sync --apply` or `wiki publish` runs, and `projection` skips the execution (so no snapshot with links to pages that do not exist goes live). The earlier stages' results stay in the run state, so the stage can be started again, and the next scheduled run starts over and goes through once a plan like it was accepted. A rejected plan stays held and asks nobody again; a different plan replaces an older open request (the older one is withdrawn). If the request cannot be raised, the stage fails, so the failure alarm reaches a person.
- **History** is `history/wiki-sync.json` in the run state: every evaluated run with its series and its fate (`written`, `held`, `approved`, `rejected`). Only written and accepted runs teach the comparison.

What it does not cover: `publish-run` writes semantic nodes, relations and cluster proposals, which are not Items and are not public; they are bounded by the vocabulary and the AI review and are undone with `knowledge entities` commands. `trend-drafts` and `monitor-stories` file a handful of ideas at the Idea stage (private, bounded by their own limits) and raise their own review requests.

## Which run wrote an Item, and undoing a run

Every Item a run writes records the run in `Item.metadata.machineWrite` (PPY-5b5a5d; `Item` has no `createdBy` or `source` column, and the field is JSON, so there is no schema change): `runId` (the latest run to write it), `createdByRunId` (the run that made it; absent for an Item a person made), `writer` and `at`. The run id of a cloud execution is `knowledge-<publication>-<execution name>`; the state machine's `KNOWLEDGE_PUBLICATION` and `KNOWLEDGE_EXECUTION_NAME` give every task, including `trend-drafts` and `monitor-stories`, the same id. The wiki sync takes it as `--run-id` (a sync without one that writes makes up `wiki-sync-<UTC time>` and prints it); the idea pipeline reads it from the environment. `versionCreatedBy` is not changed: the Idea column reads `AI` there to label a generated idea.

```bash
papyrus knowledge run undo --run-id knowledge-<publication>-<execution name>                # dry run: what it would retire, by type and section
papyrus knowledge run undo --run-id ... --apply --live-out live.json                       # retire and unpublish; never deletes
papyrus ops content project --unpublished-items live.json --static-dir ... --bucket ...    # then take the pages off the site (a human, under the lease)
papyrus knowledge run restore --run-id ... [--apply]                                       # put the Items back (a page that was live returns as a draft)
```

Undo selects the Items the run **created**, unpublishes the live ones and moves every one to the `retired` stage, recording what each was in `machineWrite.undone`. It is a dry run unless `--apply` is given, unlike most mutation commands. Items a later run only revised are retired too when this run created them, and the dry run marks them "rewritten by" the later run. The wiki sync and `wiki publish --all-drafts` leave a page at the `retired` stage alone, so the next run does not bring it back; moving the stage back (or `restore`) is the way to un-retire. The `retired` stage is not a Stories-board column.

## State, ledger and idempotency

State is per publication in the stack's S3 bucket (versioned, private), under `publications/<publication>/`:

| Prefix | Holds |
| --- | --- |
| `config/` | Not in the state. What a person maintains (`vocabulary.yml`, `stop-words.txt`, `review-guidance.md`) is committed with the site and read from the deploy: see [Committed settings](#committed-settings). `amplify_outputs.json` (endpoint only, no secrets) is generated: each stage writes it to its work directory from the endpoint AppSync reports for `appSyncApiId` |
| `corpus/` | The long-lived Biblicus corpus, including `knowledge-run.json` (the previous run's identity state) |
| `runs/<ISO week>/` | Scratch of a run: topics, trends, identity, registry, typed output, `ai-review.json`, `state.json` |

A stage downloads what it needs, runs, uploads what changed. A container keeps nothing between stages.

The run ledger is a DynamoDB table: partition key `publication`, sort key `runKey` = `<ISO week>#<execution name>#<stage>`, with `status` (`running`, `succeeded`, `failed`), `attempts`, timestamps, the error and a small details object. Query a week with `publication = shipped AND begins_with(runKey, '2026-W44')`. A stage row also carries `details.cost` (see [What a run costs](#what-a-run-costs)), and the last stage adds one run-level row, `<ISO week>#<execution>#run`.

Every stage is idempotent. Within one execution a stage that already succeeded is skipped when Step Functions starts it again; another execution of the same week (a manual run after the scheduled one) runs every stage again. The site checkout is a fresh shallow clone checked against the branch tip, so a stale checkout cannot be used. Step Functions retries each stage with backoff (two retries, 60 s, doubling).

## Failure behaviour

A stage that fails after its retries ends the execution in a `Failed-<stage>` state. `projection` is the last stage, so nothing is projected, no page is deleted and the site keeps serving the last good projection. Records the earlier stages wrote (accepted entities, clusters) stay in the backend. The deletion guard of the projection engine refuses a projection that would delete a large share of the site's pages; the cloud run never passes `--allow-deletions`.

**Site code.** Every stage that needs the site (`web/` templates and hooks, the beats config) checks out the commit of the CMS Amplify app's most recently finished successful deploy of the branch (`amplify:ListJobs`, the `SUCCEED` job with the latest `endTime`, whatever order the jobs are listed in), not whatever `main` is by then, so the pages a run renders are the pages the live site was built from. If the app has no successful deploy, the fetch fails or the checkout is another commit, the stage fails before it writes. The `projection` stage then installs the Papyrus release the site pins in its `requirements-publication.txt` (`pip install --no-deps --target`, first on `PYTHONPATH`), the release its Lambda runs. A site without that file is pinned to `papyrus-newsroom==<papyrusVersion>` from its `infra/site.json` (spelled the PyPI way: `1.0.0-next.41` is `1.0.0.dev41`), or to the release the image carries when that file does not say, and refuses to project if that release lacks the projection lease.

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

Nothing needs seeding for a new publication, and nothing under `config/` is ever read from or written to the state. To carry cluster identity from an earlier workstation run, upload the whole workstation corpus to `corpus/` (its `knowledge-run.json` names the previous run, and that run's analysis must be in the corpus).

### Committed settings

What a person maintains for a site's run lives in the repository, so it has history and review and deploys with the stack. Put any of these files in a directory beside the site file (`infra/amplify-app-shell/examples/knowledge-run-settings/<siteId>/` for the sites whose job stacks take their site file from there) and name it in `knowledgeRun.settingsDirectory`, relative to the site file:

| File | What it holds |
| --- | --- |
| `vocabulary.yml` | The publication's `description`, its `entity_kinds` (each with a `label` and optional `what` and `not_for`) and its `relation_types`. Without one the run uses the [generic vocabulary](#adding-a-knowledge-run-to-a-new-site). |
| `stop-words.txt` | Extra words the topic model and the candidate filter treat as stop words. |
| `review-guidance.md` | The editors' preferences, appended to the AI review's instructions. |

`cdk deploy` zips the directory into an asset, names it in `KNOWLEDGE_SETTINGS_ARCHIVE` and lets the task role read that one object. Every stage unpacks it into `config/` of its work directory, so a change takes effect when the stack is deployed, and the next run uses it. The stack refuses a directory that is missing, empty, outside the site file's directory or holds another file name.

**Which copy wins.** The committed settings, always. The run state is not consulted for them, so an old `config/` copy there cannot override what was deployed; if one is still there, the log says so and names it, and it can be deleted. A file the site did not commit is the generic vocabulary (for `vocabulary.yml`) or absent. Each stage's log starts with one line per file, `config/<name>: committed settings`, `generic default` or `none`, so a run shows what it used. A run that cannot find the asset fails the stage rather than falling back to the default.

Machines on Machines and Shipped commit theirs. Shipped has no `description` yet, so Jev is told only `the shipped publication`; write one in its vocabulary.

### Building and pushing the image

`infra/knowledge-run/build_image.sh` builds the arm64 image from `infra/knowledge-run/Dockerfile` (Papyrus and Biblicus from PyPI at `PAPYRUS_VERSION` (5.39.0 in the Dockerfile; `ideas trends` needs 5.39.0 or later) and `BIBLICUS_VERSION`, `awscrt`, the models baked in at pinned revisions) and pushes it with the tag you give in `IMAGE_TAG` (default the git sha). `PAPYRUS_SPEC='papyrus-newsroom[markus] @ git+https://github.com/AnthusAI/Papyrus@<sha>'` builds a commit that is not released yet. The first build takes about 15 minutes, later ones one layer. To move to a newer release, change `ARG PAPYRUS_VERSION` in the Dockerfile (or build with `PAPYRUS_VERSION=<x.y.z>`), commit, and run the script again: the tag is the commit, and ECR tags are immutable. If Docker Desktop's credential helper hangs, point `DOCKER_CONFIG` at an empty directory containing `{}` and set `DOCKER_HOST=unix://$HOME/.docker/run/docker.sock`. Deploy the tag with `cdk deploy ... -c imageTag=<tag>` (a new task-definition revision; the state machine picks up the latest revision at the start of each stage, so do not deploy during a run).

### Testing a failure

```bash
aws stepfunctions start-execution --state-machine-arn <arn> --name test-fail-$(date -u +%H%M%S) \
  --input '{"publication":"shipped","failStage":"ai-review"}'
```

The stage `ai-review` fails on entry, the machine stops, the failure alarm publishes to SNS and the site is unchanged. A scheduled execution never carries `failStage`, and a name that does not start with `test-` ignores it.

## Adding a knowledge run to a new site

The run began as Shipped's, and it no longer assumes anything Shipped has. A new site needs its published items (and, if it wants monitor records, the References its monitors route to it) and a `knowledgeRun` block that says where the site deploys. Everything else has a default.

The minimum block (`infra/site.json`, next to `aws.accountId` and `aws.region`; the IDs come from the site's CMS stack):

```json
"knowledgeRun": {
  "siteBucket": "<S3 bucket the site is projected to>",
  "edgeDistributionId": "<CloudFront distribution id of the site>",
  "redirectsKvsArn": "<ARN of the site's redirects KeyValueStore>",
  "appSyncApiId": "<AppSync API id of the CMS backend>",
  "amplifyAppId": "<CMS Amplify app id>",
  "contentActionsFunction": "<the content-actions Lambda's name>"
}
```

Add `"plugins": [...]` if the site enables any (the run refuses to project when its list differs from the Lambda's), `"corpusKey"` if the site's References are not in `knowledge-corpus-<siteId>`, `"monitorSources": ["routed"]` and `"monitorStories": {"limit": 3}` to count and write about what its monitors deliver, and `"schedule"` to stagger the hour. Deploy the stack (`cdk deploy`, [Operating it](#operating-it)); no state needs seeding. The SSM parameters `/papyrus/<siteId>/openai-api-key` (a SecureString) and `/papyrus/<siteId>/knowledge-run/alarm-email` (a String) must exist before the deploy, or `openAiKeyParameter` and `alarmEmailParameter` must name ones that do.

| What Shipped has | Setting | Default for a site that does not set it |
| --- | --- | --- |
| A corpus named like the site | `corpusKey` | The `siteId`. `corpusKey` is the `<key>` of `knowledge-corpus-<key>` and is used wherever the run names the corpus: `corpus export --corpus-key`, the monitor records, `publish-run --corpus-key`, and `papyrus ideas monitor-stories --corpus-key` (`KNOWLEDGE_CORPUS_KEY` in the task). The run's state prefix, ledger rows, alarm topic, SSM names and the actor name stay keyed by `siteId`. The Cited Trends step reads the published snapshot, which has no corpus, so it needs nothing. |
| A hand-written vocabulary | `vocabulary.yml` in the site's [committed settings](#committed-settings) | Generic kinds `organization`, `product`, `person`, `topic` and relation types `made_by`, `built_on`, `member_of`, used from the code; nothing is written to the state. |
| A Knowledge Map and `scoring.json` in the site repository | `beatsConfig` | None: the snapshot has no beats. A `beatsConfig` that names a file the checkout does not have is logged and left out; it does not fail the stage. |
| A list of concept kinds | `conceptKinds` | None: every kind is a candidate for the concept of the week. |
| A hand-placed `amplify_outputs.json` | `appSyncApiId` (required anyway) | Each stage asks AppSync for the API's GraphQL endpoint (`GetGraphqlApi`; the host is not the API id) and writes it as `{"data": {"url": ...}}` to its work directory (`KNOWLEDGE_APPSYNC_API_ID` in the task). |
| `stop-words.txt`, `review-guidance.md` | The same files in the committed settings | Not used. |
| Its own OpenAI key, Jev key and alarm mailbox | `openAiKeyParameter`, `decisionKeyParameter`, `alarmEmailParameter` | `/papyrus/<siteId>/openai-api-key`, `/papyrus/shared/typesafe-api-key` (the Jev key every site shares) and `/papyrus/<siteId>/knowledge-run/alarm-email`. |

**Sharing the key and the mailbox.** `openAiKeyParameter` and `alarmEmailParameter` name any existing SSM parameter in the site's account and region, and several sites may name the same one (`/papyrus/shared/openai-api-key`). The task role of each stack is allowed to read exactly the parameter its site names (no wildcard), and the alarm address is read when the stack is deployed. Each site still has its own stack and alarm topic, so each topic sends a subscription confirmation to the shared mailbox once, and the alarm says which publication failed. Create a shared parameter by infrastructure code, never by hand, and never commit the address.

**A site with nothing in it yet.** `corpus-sync` counts the exported items and the monitor records. With none of either, the run does not fail: the later stages each succeed with `{"status": "nothing to do"}` as their ledger details (and the usual `details.cost` for the seconds they took), nothing is modelled, imported, snapshotted or projected, and the run total is still recorded. With records but no items (a new site whose monitors have already delivered), `topic-model`, `typed-extraction` and `ai-review` have nothing to do, because records are data and never documents; `publish-run` and `publish-relations` import the records without clusters or extracted entities, and the snapshot, archive, wiki and projection run as usual. The next run that finds an item runs the whole pipeline. Topic modelling a corpus of only a few documents can still be too small for BERTopic to find clusters; the snapshot then simply has none.

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

## What a run costs

Every run records what it cost, from the run itself, so the bill is not a guess. These are estimates from list prices, never a bill.

**Per stage.** The ledger row of each stage has `details.cost`:

```json
{
  "computeSeconds": 412, "computeBasis": "task",
  "vCpu": 4, "memoryGiB": 16, "ephemeralStorageGiB": 40, "computeUsd": 0.021403,
  "llm": {
    "calls": 35, "inputTokens": 91000, "outputTokens": 12000, "cachedInputTokens": 0, "usd": 0.0151,
    "byModel": {"gpt-6-luna": {"calls": 35, "inputTokens": 91000, "outputTokens": 12000, "cachedInputTokens": 0, "usd": 0.0151}}
  },
  "totalUsd": 0.036503, "attempts": 1, "priceBasis": "AWS Fargate pricing, Linux/ARM, US East (N. Virginia) (2026-10-26); model_prices.json for models"
}
```

- **Compute.** `computeSeconds` is the time Fargate bills: from the task's first image pull (the ECS task metadata endpoint says when; `computeBasis` is `task`) to the end of the stage, or from the start of the stage when the platform does not say (`stage`), never less than 60 seconds. `vCpu`, `memoryGiB` and `ephemeralStorageGiB` are the task's own size from the same endpoint (`KNOWLEDGE_TASK_VCPU` and `KNOWLEDGE_TASK_MEMORY_MIB` fill in what it does not say), so a stage that gets its own size in the pipeline definition is priced at that size. `computeUsd` uses the Fargate ARM, US East (N. Virginia) rates in `FARGATE_ARM_US_EAST_1` in `src/papyrus_content/knowledge_cloud/cost.py` (vCPU-hour, GB-hour, and the storage over the free 20 GiB), with the date and source beside them. Change them there when AWS changes its prices.
- **Model.** The AI review reads the `usage` object of every Responses API reply (input, cached and output tokens) and prices it per model from `src/papyrus_content/data/model_prices.json`, the same table `automations cost` and `ideas synthesize` use. No extra call is made. A model's tokens are counted under the model name the API reported (a dated release such as `gpt-6-luna-2026-09-01` is priced at its listed prefix). The other stages call no model. A reply with no `usage` still counts as a call, with `llm.usd` null and a `reason`; a model with no price is listed the same way. `totalUsd` then adds only what is known and the record has `"partial": true`. A compute figure that cannot be known (no task size) is null with `computeReason` in the same way.
- **Retries.** A failed attempt writes its cost into the row (`details.cost`, with the error); the next attempt adds its own, so the final row is the cost of all `attempts`.
- **Never in the way.** If the accounting itself fails, the stage still succeeds and the row has no `cost`; the task log says `cost accounting skipped`.

**Per run.** When `projection` succeeds it adds up the stage rows of the execution into the run-level ledger row `<ISO week>#<execution>#run` (`details.cost`: `status`, `durationSeconds`, `computeSeconds`, `computeUsd`, `llm`, `totalUsd`, and each stage's seconds and dollars) and writes the same as the run's cost report, `runs/<ISO week>/cost-<execution>.json` in the state bucket. The task log ends with `run cost: ...`. A run that fails early has no run-level row; `papyrus knowledge runs` still adds its stages up. The optional `trend-drafts` and `monitor-stories` steps run after `projection`, are not stages and are not in this total (`monitor-stories` writes its own ledger row with its cost, which `papyrus knowledge runs` shows).

**Reading it.**

```bash
export AWS_PROFILE=papyrus-production
papyrus knowledge runs --site shipped --last 3      # per run: status, duration, total, compute and model; per stage: time and cost
papyrus knowledge runs --site shipped --json        # the same as JSON
```

It reads the ledger table named by the `LedgerTableName` output of the stack `KnowledgeRun-<site>` (`--table` names it directly, `--region` defaults to `us-east-1`). Runs from before this accounting show `-` for the figures they lack and are marked partial. The console has no knowledge-run status view, so there is no console panel for this yet.

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
