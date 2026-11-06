# Monitoring in the cloud (HN collector)

PPY-3212f1, step 1: the Hacker News collector runs on a schedule in AWS instead of
on an operator's machine. It is a dedicated stack, `papyrus-monitoring`, not part
of any site backend: the monitor is shared by several publications, no one site
owns it, and an Amplify backend deploy would tie HN collection to one site's
pipeline. Like the edge stacks (`infra/edge/README.md`) it is a hand-run
CloudFormation stack in account 712236451410, us-east-1, applied with a change set.
The same stack also hosts the operator alert listener (every CloudWatch alarm to a triage-ready email, plus two last-resort SNS alerts): see [operator alerts](operator-alerts.md).

## Monitors and source types

Each monitor is its own `MONITOR#<id>` partition with its own schedules. `CONFIG.sourceType` names what
it reads: `hn-rss` (the default, the Hacker News feed), `huggingface-models` (the Hugging Face Hub model list,
[below](#hugging-face-hub-monitor-huggingface-models)), `feed` (any RSS or Atom feed on an allowed host, such as arXiv's) and
`huggingface-papers` (the Hugging Face daily papers), both under [paper monitors](#paper-monitors-feeds-and-hugging-face-daily-papers),
or `ttab-decisions` (the USPTO TTAB Reading Room
decision search, `lookbackDays` 1 to 180, `finalDecisionsOnly` true by default, and `precedentialLookbackDays`:
when set, a second search over that longer window asks only for precedential decisions of any type, because the
Board can designate a decision precedential months after it issues). A TTAB item also lists the decision's other
addresses (the TTABVUE PDF, the Reading Room's double-slash path), and intake reuses a Reference stored under
any of them rather than creating a second one for the same decision. Each source type only
accepts a `sourceUrl` on its own host (a `feed` on any host in `FEED_HOSTS`). `CONFIG#router.decisions` is `cyclotron` (the default: ask the shared
Cyclotron per publication) or `direct` (deliver every collected item to every configured publication,
recorded as the monitor's own rule; no Cyclotron block, no feedback). Seed a TTAB monitor with
`seed_config.py --monitor-id ttab --source-type ttab-decisions --interval-seconds 86400` and
`seed_router_config.py --monitor-id ttab --file router.json` with `"decisions": "direct"`. A third value,
`hold`, is for a publication that has no Cyclotron yet: the router collects and enriches its items and never
decides; the config needs no `cyclotron` block (see [web search](#web-search-monitors-web-search)).

### Reading a source: no item, page or request limits

A monitor does not read "the latest N". Each pass pages its source, newest first, until it reaches items it already
collected (the high-water mark: a page that holds a collected item ends that feed) or the source has no more. The
first pass over a new monitor therefore reads the whole window; a steady pass usually reads one page. Nothing in the
config caps it: `limit`, `maxItems` and `pagesPerQuery` are retired, and a stored config that still has them loads,
ignores them and logs one `{"monitor": "ignored_retired_config", "fields": [...]}` line. They can be deleted from the
table; `seed_config.py` no longer writes them. `pageSize` (Hugging Face and TTAB) is the source API's page size, not a
total; a feed is committed 100 entries at a time for the same reason.

Only real constraints bound a pass:

- **Lambda time.** The collector Lambda times out at 120 s. A pass reads for at most 80 s (`READ_BUDGET_SECONDS`), then
  finishes the page it is on and writes its receipt; a page's items are committed before the next page is asked for, so
  a stop loses nothing. When it stops early the receipt says `read.stoppedBy: time_budget` and `STATE.resume` holds a
  cursor per feed; `nextDueAt` is then "now", so the monitor's next scheduled tick continues (15 minutes for `hn`, 6 hours
  for `ttab` and `huggingface`; for a large first load of history use the backfill command, which has no such pause). The next pass
  first re-reads the top of each feed (new items first, up to the high-water mark) and then continues at each cursor,
  so nothing between the two is skipped. Only when every feed is read to its end is `resume` cleared and the next pass
  due an `intervalSeconds` later, or, when the config has `runAt`, at the next occurrence of that wall-clock time.
- **A fixed time of day.** `runAt: {"time": "02:00", "timeZone": "America/New_York"}` (any IANA zone) makes a finished pass's
  `nextDueAt` the next occurrence of that time, computed from the local date, so daylight saving changes the UTC instant and never
  the clock time (on the spring-forward day a time inside the gap runs at the first moment after it; on the fall-back day the first
  occurrence is used). The five minute wake is unchanged: a pass stopped by its time budget is due at once and resumes on the next
  wake, and the resumed pass asks for no search already paid for in that pass (docs/search-monitors.md, "Paid searches"). The next
  time is the first one after the finish plus the 60 s due slack, so an early wake cannot run the same morning twice. `intervalSeconds`
  stays required (at least 60) and is the fallback when `runAt` is absent.
- **The source's rate limit.** A 429 is waited out for as long as `Retry-After` says (seconds or an HTTP date); with no
  header the wait starts at 5 s and doubles to at most 300 s while the limit lasts. If the wait would not fit in the
  pass's time, the pass stops there (`read.stoppedBy: rate_limited`) and resumes at the same page next pass.
- **DynamoDB's item size.** Nothing the monitor stores grows with the backlog (see parking below).

A feed that is not ordered by time (a Hugging Face query sorted by `likes`, `downloads` or `trendingScore`) has no
high-water mark. It is read until the metric falls under its minimum (`minLikes` / `minDownloads`, and at least 1, so
the long tail of models nobody has liked, downloaded or trended is not paged through), resuming from its cursor if time
runs out.

| Monitor | Source | Collect | Route | Decisions | Publications |
| --- | --- | --- | --- | --- | --- |
| `hn` | `hn-rss` | `papyrus-monitoring-hn-collect`, every 15 min | `papyrus-monitoring-hn-route`, :07/:22/:37/:52 | cyclotron | anth-us, p-apyr-us, threat-intelligence |
| `ttab` | `ttab-decisions` | `papyrus-monitoring-ttab-collect`, every 6 h (collects daily) | `papyrus-monitoring-ttab-route`, hourly at :41 | direct | distinctive |
| `huggingface` | `huggingface-models` | `papyrus-monitoring-huggingface-collect`, every 6 h (collects daily) | `papyrus-monitoring-huggingface-route`, hourly at :17 | direct, with a `rule` | shipped |
| `papers-arxiv-ai`, `papers-arxiv-security`, `papers-huggingface` | `feed`, `feed`, `huggingface-papers` | one collect schedule each, every 6 h (see [paper monitors](#paper-monitors-feeds-and-hugging-face-daily-papers); not yet seeded) | one route schedule each | cyclotron | per the router config |
| `web-<publication>` (seven) | `web-search` | `papyrus-monitoring-web-collect`, every 5 min (each monitor runs when due, hourly by default) | `papyrus-monitoring-web-<publication>-route`, hourly | cyclotron (Distinctive: hold), `holdDecisions` | that publication only |

A publication the router delivers to needs its AppSync grants in the router role. The inline policy holds
three sites; Distinctive Mark's are in the managed policy `RouterDistinctiveIntakePolicy`, and further
sites should follow that pattern (a role's inline policies are limited to 10,240 characters).

Shipped (`ShippedApiId`, default `6sw6454pozbgvdgm233gqkxsxu`) has its grants in place (`RouterShippedIntakePolicy`, and
its `relevance_decision_is` fields in `RouterDecisionRelationPolicy`), but no router config yet. The `hn` router config
adds a `shipped` publication only once Cyclotron r3 adds the publication `shipped` with output `shipped-relevance`.

Machines on Machines (`MachinesOnMachinesApiId`, default `lxyzo2l2pjftjdha7egy73wndu`) is the successor to the Papyrus product-site
backend. Its grants are added next to the old ones: `PapyrusApiId` keeps every grant until that backend is retired, so the router can deliver to
both while the `CONFIG#router` entries are swapped. `RouterRole` is at IAM's 20-managed-policy limit, so the new site adds no policy: its intake
fields are a second statement in `RouterDistinctiveIntakePolicy`, its monitor-stories fields sit in `RouterMonitorStoriesDistinctivePolicy`,
and its relation, auto-accept and enrichment read-back fields, its vector index (`MachinesOnMachinesVectorIndexArn`) and its storage bucket
(`MachinesOnMachinesStorageBucketName`) join the existing statements. `RouterIdeaPolicy` already names the AppSync API as a wildcard. The
sender-membership check needs the new Cognito pool added to the list parameter `EditorUserPoolArns` (a parameter value, not a template change).
`test_router_can_deliver_to_every_configured_publication_api` fails when a publication API parameter lacks any of these grants.

**Lab decisions in the References tab.** When the router delivers a Cyclotron lab decision it also writes a
`relevance_decision_is` relation for the Reference, in the same persist batch as the Reference, so the Suggestion row, Agree/Overrule and status read it like a sweep decision. `metadata.cyclotronId` and
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

## Web-search monitors (`web-search`)

Design: [search-monitors.md](search-monitors.md). One monitor per publication, `web-<publicationId>` (`anth-us`, `p-apyr-us`,
`threat-intelligence`, `data-parade`, `pilobol-us`, `shipped`, `distinctive`), reads [Tavily](https://tavily.com) for the queries
its editors approved and stores each result like any other discovery (title, canonical URL, `sourcePublishedAt`, and in `details`
the `query` and `queryId` that found it, Tavily's `snippet` and `tavilyScoreBp`; the snippet seeds the item's summary until
enrichment writes a better one). The source id is a hash of the canonical URL. Code: `monitoring_web.py` (source, query records),
`monitoring_candidates.py` (shared candidates), `monitoring_web_publications.py` (config builders).

**Config** (`MONITOR#web-<id>` / `CONFIG`): `sourceType: "web-search"`, `sourceUrl: "https://api.tavily.com/search"`,
`publicationId`, `topic` (`news`, the default, or `general`), `intervalSeconds` (default 3600), optional `runAt`, `candidateGroup` (`shared` for the six
shared-Cyclotron monitors), optional `startDate` (`YYYY-MM-DD`, for a query's very first pass). The Tavily key is read as the
router's is: `TAVILY_API_KEY`, or the SSM SecureString named in `PAPYRUS_TAVILY_KEY_PARAMETER`.
**Search providers and the fallback chain.** Tavily, then Perplexity, then OpenAI is the default chain, cheapest first (Tavily is free while it has credits; Perplexity is about $5 per 1,000 requests, OpenAI $10 plus tokens; Gemini's grounded search, $14, is opt-in), and the monitor reads its results through `papyrus_content.web_search`,
one interface over `tavily`, `openai` (Responses API `web_search`), `perplexity` (Search API), `gemini` (Google Search grounding) and
`bedrock` (Web Search on Amazon Bedrock). The chain is `WEB_SEARCH_PROVIDERS`, an ordered comma list such as `openai,tavily` (the older
`WEB_SEARCH_PROVIDER` names a chain of one; with neither set the chain is `tavily,perplexity,openai`; a deployment that has only a Tavily key must set `WebSearchProviders` to `tavily`). A monitor overrides it with `searchProviders` in its
own `CONFIG` (a list or a comma string); an unknown name is rejected when the config is stored. A provider's key is `<PROVIDER>_API_KEY`
(`TAVILY_API_KEY`, `OPENAI_API_KEY`, `PERPLEXITY_API_KEY`, `GEMINI_API_KEY`) or the SSM SecureString named by
`PAPYRUS_<PROVIDER>_KEY_PARAMETER`; the standard parameter names are `/papyrus/search/<provider>-api-key` (the Tavily parameter keeps its
deployed name `/papyrus/shared/tavily-api-key`). Bedrock has no key: it signs a token with the Lambda role. A provider without a key is
skipped as *unavailable*, which is not a failure. A provider that fails is skipped with a named kind, and the next one answers:
`plan exhausted` (HTTP 402, Tavily 432/433, or a 429 whose body says the quota is spent), `authentication failed` (401/403),
`rate limited` (429 that persisted through one retry, made after the `Retry-After` when that is ten seconds or less), `request rejected`
(other 4xx), `provider error` (5xx), `unreachable` and `unreadable answer`. The run error reads for example `tavily: plan exhausted (432);
openai: authentication failed (401)`; when every provider was only rate limited the pass waits as before. Each `QRUN#` record lists the
providers that answered (`providers`, request counts) and why others were passed over (`skipped`, for example `tavily: plan exhausted
(432)`). The run line and receipt of a web monitor also carry `searches` (paid searches by provider for the run and for the whole pass, and the failures each provider answered; docs/search-monitors.md, "Paid searches"), and a provider that refuses its key or reports its plan used up is skipped for the rest of that run. To drop a provider (for example OpenAI) set the `WebSearchProviders` stack parameter (`tavily,perplexity`) and deploy; no monitor config sets `searchProviders`, so the parameter alone decides. Only Tavily and Perplexity can bound a search by date: any other provider is asked once per query window and the window is never
split into days (it would only repeat the answer). `excludeDomains` / `includeDomains` (a query's, plus the monitor's `excludeDomains`) are
sent natively where the provider has them (Tavily, OpenAI, Perplexity include) and are always applied again to the answer. `topic` applies
to Tavily only. A written answer is not requested by monitors.

**Queries are records** (`MONITOR#web-<id>` / `QUERY#<id>`): `text`, `rationale`, `origin` (`drafted` or `editor`), `createdBy`,
`createdAt`, `approvedBy`/`approvedAt`, `status` (`active`, `paused`, `retired`), `highWater` and an append-only `history`. Only an
approved, active query is searched. `papyrus monitors web-queries` drafts them and `seed_web_monitors.py` stores them.

**Recency is each query's high-water mark.** `highWater` is the start time of the last pass that read that query to its end
without an error. A pass searches from the day before it to today, so Tavily's date bounds can never lose the boundary day (the
overlap costs nothing: collected URLs are skipped). A pass that stops early (time, rate limit) or meets an error moves no mark.
A query with no mark yet uses `startDate`, else Tavily's own default recency, in one request.

**All the results, with no limit of ours.** Tavily's search has no result offset and answers at most 20 per request. A window whose
answer fills the page is therefore split in two (`start_date` / `end_date`, whole days) and each half is asked again, down to a
single day. A single day that still fills a page is taken as Tavily gives it (its own limit). What bounds a pass is the collector
Lambda's time (the rest is stored as resume cursors in `STATE.resume`, and the next pass continues it) and Tavily's rate limit
(a 429 waits for its `Retry-After`).

**QueryRun** (`QRUN#<startedAt>#<runId>#<queryId>`): one per query per pass: `requests`, `resultsReturned`, `newCount`,
`duplicateCount`, `credits` (Tavily's `usage.credits` when it reports it, else 1 per basic request), the windows asked and
`stoppedBy`.

**Candidates and dedupe.** Every collector (and the email receiver) records a shared candidate per canonical URL
(`CAND#<hash>` / `CAND`): `collectedBy` (the monitors that made a discovery) and `provenance[]` (monitor, query, run, score,
published date, found-at; appended every time anything finds the URL again). A web monitor skips a URL it already has, one any
other source collected, and one a web monitor of the same `candidateGroup` collected; it still appends provenance. So a story
Hacker News found is not collected again as new, and the six shared web monitors find a story once. Candidates exist from this
release on; run `infra/monitoring/index_candidates.py` once for discoveries collected before (an operator step, below).

**Schedule.** `papyrus-monitoring-web-collect` (`rate(5 minutes)`) invokes the collector with
`{"sourceType":"web-search","monitorIds":[...the seven...]}`. It runs every listed web monitor whose next-due time has passed,
the longest overdue first, dividing the pass's read time between them; a monitor that stopped early is due again at once, so the
next invocation continues it. Disabled, unseeded and not-yet-due monitors are skipped. Routing has one hourly schedule per
monitor, `papyrus-monitoring-web-<id>-route`, at staggered minutes.

**Routing.** The six shared-Cyclotron monitors each list **all six** shared publications and reuse the `hn` router's `cyclotron`
block, so a find is decided for every publication in one combined `POST /machine/decisions`, as Hacker News items are.
Distinctive Mark has no Cyclotron yet, so its router config is `decisions: "hold"` with no `cyclotron` block (validation accepts
that): items are collected and enriched, never decided, and its candidates are its own group. When Cyclotron bootstraps
Distinctive's own run, re-seed its router config with `decisions: "cyclotron"` and the cyclotron block. Every web router config
sets `holdDecisions: true` and `mode: "live"`: enrichment runs, no decide request is posted, and the receipt says
`stoppedBy: decisions_held`. Release with `seed_router_config.py --monitor-id web-<id> --set holdDecisions=false` (all six
shared monitors). Cyclotron items from a web monitor carry `values.source: "web-search"`; the Cyclotron must accept that source.

**Queries (drafting).** One query per enabled newsroom section plus one for the site (see [search monitors](search-monitors.md#queries-per-section)).
`papyrus monitors web-queries --publication <id>` (or `--all`) reads each enabled section (mission, policy, guidance, kill criteria)
and the publication's mission and policy from its backend (IAM, read-only), drafts the missing queries with gpt-6-luna and prints,
per site, the old queries to retire and the new ones to add; `--out FILE` also saves JSON. Nothing is written without `--execute`;
`--execute --approved-by NAME` retires the old ones (status `retired`, history kept, never deleted), stores the new ones as `QUERY#`
records and approves them. `--retire-editor` also retires editor-written queries, which are otherwise kept.

**Operating.** Seed (plan only without `--apply`): `python3 infra/monitoring/seed_web_monitors.py --table TABLE
--queries-file web-queries.json --approved-by "NAME" [--enable] --apply` writes the 7 configs, 7 router configs and the query
records. Without `--enable` the monitors start disabled, so nothing is searched or spent until they are enabled.

## Hugging Face Hub monitor (`huggingface-models`)

Feeds Shipped's knowledge map. It reads the public model list (`https://huggingface.co/api/models`, no key). The
Hub cannot filter by date or by likes, so the monitor's `CONFIG` describes a few **queries** and the reader pages each
one (cursor from the `Link` header; `pageSize` is the Hub's page size, not a total) until it reaches models already collected,
passes the window, or the Hub has no more ([reading a source](#reading-a-source-no-item-page-or-request-limits)):

- one query per `authors` entry (a watchlist of organisations), newest first;
- one per `search` term, newest first;
- one per `pipelineTags` entry, in the configured `sort` (`createdAt` newest first, `trendingScore`, `likes` or `downloads`).

A model is **kept** when it was created inside the window (`lookbackDays`), matches `pipelineTags` (when given), and is
either from a watchlisted author, or has at least `minLikes` likes, or at least `minDownloads` downloads (30-day count).
With neither threshold set, every match is kept. Each day's run re-reads the whole window, so a model that reaches a
threshold within `lookbackDays` of its release is picked up then; one that gets there later is not. Only
`https://huggingface.co/api/models` is ever requested (the source URL, and every cursor, are checked), with a
descriptive `User-Agent` and a pause between requests. A 429 is waited out (`Retry-After`) or, if that does not fit in
the pass, ends it with `stoppedBy: rate_limited` to continue next pass; a query that fails does not stop the others.

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
| `lookbackDays` (7), `pageSize` (200, up to 1000) | the window, and the Hub's page size (not a total) |
| `intervalSeconds` | as for every monitor |

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
and base models, and the Reference holds the whole `details` map in `discoveryDetails`.

### Feeding the Knowledge Map

Delivered models are References, so they stay out of the evidence sets until a person accepts them, and they never become pages. A site that wants them in its weekly Knowledge Map **as data** sets `monitorSources: ["huggingface"]` in the `knowledgeRun` block of its `infra/site.json` ([knowledge-cloud-run.md](knowledge-cloud-run.md#monitor-records-optional-off-by-default)). The next knowledge run then counts every delivered model that is not rejected, dated by its `createdAt`, in entities (the model, its maker, licence and task) and weekly trends (not in topic-model clusters), and imports `baseModels` as `built_on` relations with the Hub card as evidence. Messages come only from people, so a delivery writes no provenance Message and no `ingestion_rationale` relation. The router records the delivering monitor in the Reference's `discoveredByMonitorId` (indexed: `listReferencesByMonitorAndCreatedAt`), the model's structured `details` in `discoveryDetails`, and, for a rule monitor, `{"system": "direct", "rule": ...}` in `discoveryRule`. A Reference that several monitors find keeps the first monitor; a new revision of the same source item refreshes the details. A model delivered before this change is counted with its title, date and author only until `papyrus references backfill-monitor-deliveries` copies the old relation's facts onto the Reference (`--dry-run` prints the counts and writes nothing). Backfill the year you want counted before the first run; a record's weekly history is its release week, not its delivery week.

### Promoting a record to an item

A delivered model counts in the Knowledge Map as data and is never a page. To write about one, a person promotes it:

```bash
papyrus references promote <reference-id> --section <section>        # --dry-run shows what it would save
```

It saves a **draft** article `item-<section>-<org>-<name>` (type `article`, status draft) whose front matter has the title (the model id), the deck (the record's structured line), `entities` (the model, maker, licence and task), `sources` (the Hub card and "from the Hugging Face Hub") and `monitorRecord` (reference id, release date, licence, pipeline tag, likes, downloads, base models). There is no `date`: publishing stamps it. The body is a stub with the card link and a note that an editor writes the story. Nothing is published, the Reference's curation state is not changed, and promoting twice leaves the draft, and whatever the editor wrote in it, alone. The reference may be given by id, lineage id or external item id (as the first argument or `--reference`); `--actor-label` names who promoted it (default `papyrus-cli`). Only Hub models can be promoted.

### Drafting stories about delivered items

Promotion is a person's choice. For any monitor's items (not only Hub models) `papyrus ideas monitor-stories --site <site>` (and, every day, the router's [monitor stories task](#monitor-stories-daily)) picks the items most worth a story, ranked by the relevance Cyclotron's `relevance_decision_is` verdict on each Reference, and files one cited idea (an Item at the `idea` stage, in the Idea column of the Stories board) for each, naming the monitor in its provenance. A Reference that was drafted or promoted is never drafted again. The weekly cloud run can run it with one `knowledgeRun.monitorStories` setting. See [idea pipeline: monitor stories](idea-pipeline.md#monitor-stories) and [cloud run: monitor stories](knowledge-cloud-run.md#monitor-stories-optional-off-by-default).

### Backfill: loading history

`papyrus monitors backfill --monitor huggingface --since 2025-10-25T00:00:00Z` loads the models created since then that
the monitor's `CONFIG` would accept, through the same `ITEM#` dedupe as the live collector (so it is idempotent and can
run beside the schedule). It is a **dry run** (reads the Hub, counts what it would add, writes nothing) unless `--apply`.
Because the Hub cannot filter by date, it pages each author and search query newest first until `--since`, and each
`pipelineTags` query in `likes` order (and again in `downloads` order when `minDownloads` is set) until the metric falls
under the threshold, keeping only models created inside the window. It has no page or request budget: it reads the whole
window. Option: `--until`. The Hub allows 500 requests per 5 minutes, so on a 429 it waits for `Retry-After` (else 5 s,
doubling to 300 s), printing `rate limited: waiting Ns`, and carries on; it prints a progress line after every chunk of
pages. After every chunk it saves a `BACKFILL#<since>#<scope>` checkpoint (each query's cursor), so Ctrl-C is safe (it
reports `interrupted` and exits 130) and running the same command again resumes there; a finished backfill reads nothing. Backfilled discoveries are `collected` like any other, so the router
delivers them on its next runs, oldest collection first.

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
 "lookbackDays": 7, "pageSize": 500, "intervalSeconds": 86400}
```

Recommended `shipped-huggingface-router.json` (a watchlist name that does not exist on the Hub just returns nothing):

```json
{"mode": "dry-run", "decisions": "direct",
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

## Paper monitors: feeds and Hugging Face daily papers

Research papers come from two source types. Neither needs a Cyclotron of its own: a paper monitor delivers through the shared
Cyclotron per publication like `hn` does (`decisions: cyclotron`), so each site decides for itself, and which publications a
monitor fans out to is the router config (`CONFIG#router`), unchanged. Both name a paper by its arXiv address
(`https://arxiv.org/abs/<id>`, no version), so the same paper read from arXiv and from Hugging Face is one canonical URL and, at
intake, one Reference. The source id is the same function of the id for both (`2611.00159` is `2611_00159`, `cs/0112017` is
`cs--0112017`: a table key allows no dot or slash).

### General feeds (`feed`)

`sourceType: feed` reads an RSS 2.0 or Atom document from the `sourceUrl` in the monitor's config, so a new feed is a new monitor
config and no code. Safety is that of the Hacker News reader, with one larger limit:

- **https only**, no credentials in the address, and the host must be in `FEED_HOSTS` in `src/papyrus_content/monitoring_feed.py`
  (today `rss.arxiv.org` and `export.arxiv.org`). Adding a host is one line there, and the deploy ships it; a `sourceUrl` on any other
  host is refused when the config loads. A feed address may carry a query (the arXiv API's Atom feeds do), unlike the other types.
- **Size.** 8 MB, not the 2 MB of the Hacker News feed: arXiv's combined daily feed for `cs.AI+cs.LG+cs.CL+cs.MA+stat.ML` was
  3.59 MB (1,661 entries) on 2026-11-03.
- **A document that declares a DOCTYPE or an ENTITY is refused**, whatever its size, and so is anything that is not an RSS 2.0
  channel or an Atom feed (an HTML error page, a cut-off document). The pass fails with a `fetch` error and the next pass reads it
  again. A feed with no entries is a complete pass.

Each entry is an item. Its source id is the entry's stable id (the arXiv rule below; otherwise the `guid` or Atom `id`, falling
back to the link, made key-safe and hashed when it had to change), its canonical URL is the entry's link (an Atom entry's
`rel="alternate"` link), and `details` carries what the feed says: `title`, `publishedAt`, `abstract` (the description or summary,
as is, at most 20,000 characters), `authors` (at most 50), `categories`. An entry with no title or link is left out, and an
unreadable date is a missing date, so one odd entry cannot stop a feed of a thousand.

**Reading.** The feed is downloaded once per pass and committed 100 entries at a time. The resume cursor is the source id of the
last committed entry, not a number, so a feed that was rebuilt between two passes is continued at the right place (an entry that left
the feed starts the pass over at the top; collected entries are `unchanged`). Like every monitor it reads everything it has not
collected, with no item cap, bound by the Lambda's time.

**arXiv rule** (per host, `HOST_RULES`; it is not a separate type). arXiv's feed lists `arxiv:announce_type` `new`, `cross`,
`replace` and `replace-cross`. A revision of an old paper is not news, so `replace` and `replace-cross` are skipped; a feed with no
announce type (the API's Atom feed) keeps every entry. On 2026-11-03 the five-category feed held 754 `new`, 336 `cross`, 383
`replace` and 188 `replace-cross`, so 1,090 entries were kept. The paper id is the bare id from the link
(`arxiv_paper_id` in `monitoring_web.py`), or from a `oai:arXiv.org:2611.00159v1` guid when the link is not an arXiv address.
The abstract loses the leading `arXiv:2611.00159v1 Announce Type: new` line and the `Abstract:` label and is otherwise stored as is
(LaTeX included). `details` adds `arxivId` and `announceType`.

**Fingerprint.** Title, canonical URL and publication date: a paper is one discovery, and a later pass finds it `unchanged`.

### Hugging Face daily papers (`huggingface-papers`)

Reads `https://huggingface.co/api/daily_papers` (no key): the papers the community picks each day, newest pick first. Verified live
on 2026-11-03: `limit` is at most 100 (500 answers 400), each response names the next page in its `Link: <...&p=1>; rel="next"`
header, a page past the end is an empty list (the last page of a `date=` query too), and `date=YYYY-MM-DD` limits the list to one
day's picks. The monitor does not use `date`: it pages from the newest row until a page holds a paper it has already collected
(the high-water mark), the oldest paper on a page was picked before the window, or a page is empty, with the same pacing, rate limit
handling and time budget as the model source. The window is `lookbackDays` (default 7, up to 366), the one bound the first pass needs:
the list reaches back years, and a new monitor should not load all of it. A longer history is `lookbackDays` raised for one pass.

| `CONFIG` field | Meaning |
| --- | --- |
| `sourceUrl` | exactly `https://huggingface.co/api/daily_papers` |
| `lookbackDays` (7) | the window, counted from the day a paper was picked |
| `pageSize` (100, up to 100) | the API's page size (`limit`), not a total |
| `intervalSeconds` | as for every monitor |

Each row is an item for `paper.id`: title (the paper's own), canonical URL `https://arxiv.org/abs/<id>`, published date (the
paper's `publishedAt`). `details`: `arxivId`, `title`, `publishedAt`, `submittedOnDailyAt`, `abstract` (`paper.summary`), `authors`
(names), `upvotes`, `comments` (`numComments`), `submittedBy`, `organization`. A row whose id is not an arXiv id is skipped. The
fingerprint ignores votes and comments, which move all day, so a paper is decided once; the counts in `details` are as of the first
time the monitor saw it.

### Three monitors

Config items (`MONITOR#<id>` / `CONFIG`). The arXiv feed is built once per weekday (its `skipDays` are Saturday and Sunday), so six
hours is frequent enough to catch the build.

```json
{"pk": "MONITOR#papers-arxiv-ai", "sk": "CONFIG", "sourceType": "feed", "enabled": true, "intervalSeconds": 21600,
 "sourceUrl": "https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL+cs.MA+stat.ML"}

{"pk": "MONITOR#papers-arxiv-security", "sk": "CONFIG", "sourceType": "feed", "enabled": true, "intervalSeconds": 21600,
 "sourceUrl": "https://rss.arxiv.org/rss/cs.CR"}

{"pk": "MONITOR#papers-huggingface", "sk": "CONFIG", "sourceType": "huggingface-papers", "enabled": true, "intervalSeconds": 21600,
 "sourceUrl": "https://huggingface.co/api/daily_papers", "lookbackDays": 7, "pageSize": 100}
```

**Seeding one** (needs an operator with the production profile, as in "Starting Shipped"; `seed_config.py` validates the item with the
collector's own validator before it writes, so a config the Lambda would refuse is never stored):

```bash
TABLE=$(aws ssm get-parameter --name /papyrus/monitoring/table-name --query Parameter.Value --output text)
python3 infra/monitoring/seed_config.py --table "$TABLE" --monitor-id papers-arxiv-ai --source-type feed \
    --source-url "https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL+cs.MA+stat.ML" --interval-seconds 21600
python3 infra/monitoring/seed_config.py --table "$TABLE" --monitor-id papers-arxiv-security --source-type feed \
    --source-url https://rss.arxiv.org/rss/cs.CR --interval-seconds 21600
python3 infra/monitoring/seed_config.py --table "$TABLE" --monitor-id papers-huggingface --source-type huggingface-papers \
    --interval-seconds 21600            # add --file with lookbackDays / pageSize to change the defaults
```

A monitor also needs what any monitor needs: its collect and route schedules, which `papyrus-monitoring.yaml` has for these three
(routing at minutes 6, 23 and 51), and `seed_router_config.py --monitor-id <id> --file router.json` for its publications
(`decisions: cyclotron` with the shared `cyclotron` block, or `hold` while a site has no Cyclotron). The ids are already in the
Monitoring page's `MONITOR_IDS` (`monitoring_view.py`), so the page lists them as soon as they have items.

**What the decision sees.** `values.source` is `feed` or `huggingface-papers`, and the abstract is the decision's summary until
enrichment has a summary of its own: `text` is the title, the address and the abstract, with no fetch of the paper. See "Enrich
before decide" for why enrichment still runs for these items today and how it behaves for an arXiv address.

**Gherkin.** `monitoring-paper-feeds`. Recorded responses are in `procedures/newsroom/tests/fixtures/feeds`.

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
| Alarm `papyrus-monitoring-collector-errors` | Lambda `Errors` >= 1 in 15 minutes |
| Alarm `papyrus-monitoring-search-provider-failing` | the collector logged `{"monitor": "search_provider_failing", "provider", "kind": "auth" or "plan_exhausted"}` (a web-search provider refusing its key or out of plan, such as Tavily 432 or Perplexity 401) at least once in a day; metric `Papyrus/Monitoring` `SearchProviderFailing` from a metric filter on the collector log group |
| Alarm `papyrus-monitoring-decisions-stopped` | no Cyclotron decision for two hours in a row while items are waiting. Every alarm in this stack emails through the topic `papyrus-monitoring-alarms`, to the address in the SSM parameter the `AlarmEmailParameter` stack parameter names (the address is never in the repository; a new subscription must be confirmed from the email AWS sends). Metric filters on the router log group make `Papyrus/Monitoring` `RouterDecided` (the pass's `counts.decided`) and `RouterAwaiting` (its `counts.awaiting`); the alarm is the metric-math `IF(decided == 0 AND awaiting > 0, 1, 0)` over hourly Sum and Maximum, 2 of 2 hours, summed across all monitors. Missing data is not breaching. See [Decisions stopped](#decisions-stopped-alarm) |
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
| `CONFIG` | Config as data: `sourceUrl` (an https news.ycombinator.com feed), `intervalSeconds` (>= 60), `enabled` (no item limit: the collector pages until it meets items it already has). Seeded by `infra/monitoring/seed_config.py`, edited in the table, never in Lambda environment |
| `STATE` | Checkpoint: `nextDueAt` (epoch seconds), `lastRunId`, `lastStatus`, and `resume` (cursors per feed, only while a pass stopped early on time or a rate limit) |
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
failed feedback pass never fails routing, and `{"task":"route"}`, `{"task":"collect"}` or `{"task":"feedback"}`
limits an operator-invoked run. [Automatic acceptance](#automatic-acceptance) is not part of a routing run: it has its own hourly schedules
and runs once per publication. A second schedule runs `{"task":"collect"}` every 2 minutes to deliver jobs that
were still running when the route run ended ([post first, then collect](#post-first-then-collect)).

## Dry-run and live

`mode: dry-run` makes **no** Cyclotron call and writes nothing to any publication.
For each collected discovery (oldest first) it builds the exact
`decide` body for every configured publication, validates it structurally (contract
version, operation, `requestId` 8 to 128 characters, payload shape, item values,
32 KiB bound), reads each publication's editorial context hash through the existing
`editorial_context` code (read-only; `contextHash: null` plus the reason when the
publication stores no policy, never a failure) and records a receipt.

`mode: live` decides each item with **one combined machine request**, polls only, records the
decision receipt and delivers (see below). The dry-run receipt also records that request under
`dryRun.combined`.

### The decision contract

The router speaks Cyclotron's decision contract, `cyclotron-decision/v1`, in which Cyclotron names bindings,
callers and reviewers rather than publications and editors. A publication's binding is still configured here by its
`publicationId`; that id is the binding id Cyclotron sees. A story for one publication goes to
`POST /machine/bindings/{publicationId}/operations` and is polled at `GET /machine/bindings/{publicationId}/commands/{jobId}`;
a story for several goes to `POST /machine/decisions`. Answers name the binding as `bindingId`, and a combined
receipt maps each binding to its answer under `decisions`.

A combined job posted before the router switched still answers in `cyclotron-publication/v1` (Cyclotron answers a
combined job in the contract it was posted in), and so does its decision-ready event. The router reads those answers
in the decision contract's names (`publicationId` as `bindingId`, `publications` as `decisions`, or as `bindings` in an
event), so an older job is collected like any other and never posted again.

### One request per story

For each story the router sends `POST /machine/decisions` (SigV4, same principals, `X-Cyclotron-Account`)
with `{"contractVersion", "requestId", "payload": {"bindings": {"<publication>": "<bindingRevision>", ...}, "item"}}`.
The bindings are every active publication that has no decision yet and is not parked (a publication
waiting for a classifier is left out, as the per-publication logic always did). It then checks
`GET /machine/decisions/{jobId}` (202 while running; see [post first, then collect](#post-first-then-collect)). The 200 body's `decisions` maps each binding to
exactly what `GET /machine/bindings/{pub}/commands/{job}` returns, and each is checked and stored as
`ROUTE.jobs[pub].checked` by the same code as before, so the `decide_binding` receipts, `route.decision`
and delivery keep their shape. A story takes one Cyclotron job instead of one per publication.

- `requestId` is `sha256("decisions" \n contractVersion \n accountId \n runId \n sorted pub@binding list \n itemId \n revision \n fingerprint [\n attempt-N])`,
  so a retry of the same story with the same binding set reuses it (Cyclotron's idempotency). The contract is part
  of the id because Cyclotron holds a combined request id to the contract it was first sent in. The job is
  stored on the route as `combinedJob` before the POST is sent; an accepted job is resumed by polling only
  and a POST is never repeated.
- **404** on the POST means this Cyclotron has no combined endpoint yet: the router decides that story, and
  every later one in the run, with one `decide` per publication as before (so either side can deploy first).
- **409 "publication binding changed"** stops the run with `stoppedBy: binding_changed`; the story stays
  `collected`, and the next run reads the current `CONFIG#router` and asks again.
- **409 "publication criteria are pending"** (a pending output somewhere in the set; the answer does not say
  which) makes the router decide that story one publication at a time, which parks the waiting binding.
  A pending or refusal entry inside a completed receipt is handled per publication: pending parks it, the others
  are decided; `source_refused` refuses the story; stop codes the lab sends (`run_busy`, `request_ceiling_reached`, key, capacity) are still handled and stop the run; the router has none of its own.
  Other publications' receipts in the same answer are kept on the route.
- `run_busy` and 503 defer exactly as for a single decide (non-consuming refusals bump `attempt`, giving a new request id).
- A single remaining binding, and backfill of parked items, use the per-publication `decide`.

The per-publication `requestId` is `sha256(accountId \n runId \n publicationId@bindingRevision \n itemId \n fingerprint)`.
Both it and the combined id are identical in dry-run and live, so flipping to live cannot duplicate a decision.

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
first, every one of them (paging through the whole partition). The router has no limit of its own on how much it does in
a run: the only bound is the Lambda's time, and whatever is not posted before then is posted by the next run. Stop conditions (`provider_key_unavailable`,
`request_ceiling_reached`, `standing_capacity_reached`, `run_busy`, any 401/403/404/429/503/507/409)
end the sweep cleanly: the run receipt says
`status: stopped` with `stoppedBy`, items stay where they were, and nothing is retried
until the next schedule. A refused POST leaves no job marker, so it may be sent later; an
accepted job keeps its `jobId` under `ROUTE#...`.`jobs` and is only polled.

### Jobs left over from an earlier Cyclotron run

A stored job (`combinedJob`, `jobs.<pub>`) also records the `runId` and `bindingRevision` it was posted under.
After a Cyclotron run cutover the lab no longer answers for the old run's jobs (`GET /machine/decisions/{jobId}`
returns 404). Before polling, the router compares the stored markers with `CONFIG#router`.`cyclotron`; a job
with different markers (or, for a job stored before the markers existed, a `requestId` that does not match the
request the current config would build) is discarded and the story is posted again under the current binding,
as a new idempotent request. A 404 on a stored job is handled the same way, once: the job is discarded and
re-posted in the same run. If the re-post's poll also answers 404 that one story ends as `error` and the sweep
carries on; a single story's 404 never stops the run. Every other refusal behaves as before.

A job the lab ended as failed, or reconciled as failed, gives no reason, and the usual one is the lab's own storage.
It is re-posted once in the same run. If the re-post fails too, the story is not ended: it stays `collected` and backs
off like any other non-permanent refusal (15 minutes doubling up to a day, `nextAttemptAt`, `lastRefusal`), then is
posted under a new request id. A job with a refusal code keeps that code's meaning, so `source_refused` still ends the
story as `refused`.

### Post first, then collect

A cold lab job takes about 100 seconds, so a live sweep never waits on one story while others sit idle:

1. **Post.** For each candidate (every one; the Lambda's time is the only bound) the router sends
   or resumes the story's job and checks it with a single GET. A job that is still running is not a stop
   condition: it stays recorded on the story (`combinedJob`, or `jobs.<pub>.jobId`) and the router goes on to
   the next story. A finished job goes straight to the unchanged fan-out and delivery. The per-publication
   path posts all of a story's bindings before it waits for any of them.
2. **Collect.** The router then polls every outstanding job of this run round-robin with a backoff (2 s, growing
   to 8 s) for at most `cyclotron.pollSeconds`, and never into the last `MIN_REMAINING_SECONDS` (120 s) of the
   invocation, delivering each story the moment its job completes.
3. **End.** Jobs still running leave the run with `status: awaiting`, `stoppedBy: awaiting` and
   `counts.awaiting` set. That is normal, not a failure. A real stop condition from Cyclotron still ends the run
   as `stopped`.

The collector is the same function invoked with `{"monitorId":"hn","task":"collect"}`. It looks at the stories in
`collected` that already hold a recorded job, polls them (one pass, then the same bounded collect window) and
delivers the finished ones. It never posts a story that has no job and does not run feedback. It takes the
per-monitor router lock exactly as a route run does, so the two cannot overlap: whichever comes second returns
`status: locked` without calling Cyclotron. The schedule `RouterCollectSchedule` runs it `rate(2 minutes)`; it
follows the same `ScheduleState` switch as the other schedules. Request ids stay deterministic and the job is
recorded before the POST, so no job is ever sent twice. The specs are in
`features_backend/monitoring-post-then-collect.feature`.

A stored job is polled until the lab completes it, reports it failed, or answers 404; its age never ends it. A story
an earlier age limit finalized with the reason `job pending longer than the allowed time; reconcile manually` is
put back by the one-off task `{"monitorId":"hn","task":"reopen-stale-finals"}`: it removes `final` (only while that
reason still matches), keeps the stored jobs, returns the discovery to the `collected` partition and reports
`reopened`. The specs are in `features_backend/monitoring-no-pending-timeout.feature`.

### Outputs that are not ready (waiting for classifier)

A binding whose Cyclotron output has no runnable classifier yet (`pending_criteria`) answers `decide`
with HTTP 409 and the body `{"detail": "publication criteria are pending"}` (the machine API sends no typed code; the typed `criteria_pending` is accepted too). That is a per-binding outcome, not a stop condition: the router
skips that binding for the item (`route.notReady[pub]`, counter `skippedNotReady`), decides and
delivers the other bindings, and the sweep continues. It makes no Cyclotron call for the waiting
binding beyond one probe, so it uses no retries and no ceiling. If every binding is waiting, the item
is final `parked`. Any other 409 still stops the sweep.

Parking: one `PARK#<publicationId>` header item per waiting publication holds `reason`, `since`, `nextProbeAt` and
`backoffSeconds`; each skipped item is a row of its own, `PARK#<publicationId>#<sourceId>#<revision>`, so nothing is
dropped and no row grows with the backlog. No call is made until `nextProbeAt`; then the next item
probes once, and a still-pending answer doubles the backoff (30 minutes up to 6 hours). When a probe
succeeds the park becomes `ready`, and each run first decides the parked items (all of them, paging through the
partition, bounded only by the Lambda's time) and delivers positives, then removes the park. A header written by an
earlier version, which carried the newest 25 items in a list, is split into rows the first time it is read, keeping
every item it had. The run receipt carries `waitingForClassifier` (publication ids) and the
Monitoring page shows it on the router run.

## Router items

| `sk` | Meaning |
| --- | --- |
| `CONFIG#router` | Config (below) |
| `LOCK#router` | Lease (660 s, longer than the 600 s timeout), separate from the collector's `LOCK` |
| `ROUTE#<sourceId>#<rev6>` | `dryRun` (`count`, `validatedAt`, `requests.<pub>` = path, `requestId`, bytes, body; `contexts.<pub>` = `contextHash`/`reason`), `jobs.<pub>` (`requestId`, `jobId`, `checked`), `decision` (`decisionId`, `source` = id/revision/fingerprint, per-publication `output`, `label`, `fingerprint`, `version`, plus account, run, binding revision), `publications.<pub>` (`delivered`, `referenceId`, `attempts`, `lastError`), `final` |
| `ENRICH#<sourceId>#<rev6>` | The item's enrichment before its decision ([Enrich before decide](#enrich-before-decide-item-enrichment)): `status`, `final`, `attempts`, `curation`, S3 keys |
| `CRIT#<pub>` | The latest `criteriaFingerprint` Cyclotron reported for the publication's output (feedback compares against it) |
| `DELIV#<pub>#<referenceId>` | A Reference this router delivered; the item, output and decision a later vote on it is sent under. Feedback looks it up by the voted Reference's id. Rows written before 2026-11-02 also sit in the old `FEEDBACK#<monitor>#pending` index, which nothing reads any more |
| `TRIGGER#<pub>#<procedureKey>#<sourceId>` | A procedure trigger for this item: `status` (`starting`, `started`, `startFailed`, `notTriggered`, `skipped`, `deferred`, then the runner's `running`, `completed`, `failed` or `notRunnable`), the runner `request`, `runId`, a `reason` for `skipped` and `deferred`, the `automationId` when an automation governed the start, errors. Written only if absent, so each item starts each procedure once (`docs/procedure-runner.md`, `docs/automations.md`) |
| `MANUAL#<automationId>#<timestamp>` | A "Run now" of an automation, written by the CLI or the console (not by the router): who started it, the runner `request`, then the runner's `running`/`runId` and outcome, as on a `TRIGGER#` row (`docs/automations.md`) |
| `FB#<requestId>` | Feedback receipt for one vote: outcome (`sent`, `stale`, `refused`, `invalid`), label, curation status, publication, and `explained` (whether the vote carried the editor's explanation; the text stays on the Reference). A final receipt is what stops a vote being sent twice |
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
{"mode": "dry-run|live", "enabled": true,
 "publications": [{"publicationId": "...", "site": "...", "appsyncEndpoint": "https://<id>.appsync-api.<region>.amazonaws.com/graphql",
                   "corpusId": "knowledge-corpus-<publicationId> (default)",
                   "autoAccept": {"enabled": true, "precision": 0.9, "latencyQuantile": 0.9},
                   "monitorStories": {"enabled": true, "store": "items", "singleItem": true,
                                      "contextPacks": {"enabled": true, "signals": ["conversation", "acceptance"]}}}],
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

`holdDecisions` (boolean, default `false`): when `true`, route and collect runs make no `POST /machine/decisions` and no
per-publication `decide` POST. Enrichment still runs so items are ready, stored jobs are still polled, and the feedback pass
(editor votes) still runs, including `{"task":"feedback"}`. The receipt records `stoppedBy: "decisions_held"`. `enabled: false`
still means do nothing at all.

Editor feedback is sent under the publication's *current* `cyclotron.bindingRevision`, never the revision stored
when the item was decided (the lab refuses a stale one with 409 "publication binding changed"; the router logs the
body and asks again next run). Feedback is tied to the criteria the editor judged. Cyclotron puts a
`criteriaFingerprint` on each `outputs[]` entry of a decision envelope (the router derives sha256 hex of the UTF-8 `question`
when only the question is present). The router stores it on each `DELIV#` row and keeps the latest per publication in
`CRIT#<pub>`; a vote is sent under the current binding only when the two fingerprints are equal, otherwise it is recorded
as outcome `stale`. `criteriaSince` is now only the fallback, used when either fingerprint is unknown (votes stored before
fingerprints existed, or no decision seen yet). Each publication entry takes an
optional `criteriaSince`: the earliest binding revision whose criteria match the current ones (default: the current
revision, the safe choice). A vote stored under revision R is sent with the current revision when R >= `criteriaSince`
(integers compare numerically); otherwise it is recorded as outcome `stale` ("criteria changed since this vote"),
dropped, and not retried.

## Enrich before decide (item enrichment)

The lab decides on what an editor will later rate, so the router curates each item **once, before the first decision is
posted** (`monitoring_enrichment.py`). Order: collect (title, URL) -> **enrich** -> decide -> deliver (copying the item's curation
onto each delivered Reference) -> the post-delivery `papyrus.reference.curate` procedure, which now only fills per-site gaps.

- **When.** Inside `live()`, right before the first `POST` of an item that has at least one binding to decide (parked items and
  items every binding refuses are never enriched). The collector task (`post_allowed = false`) never starts an enrichment. An item
  already posted before enrichment existed keeps the text the lab decided on. A `direct` monitor enriches too (after its rule
  accepts the item), for delivery.
- **Stages** (the curation pipeline's own code, `docs/reference-curation-pipeline.md`): capture the whole article or PDF, completeness
  signals, a `gpt-6-luna` summary, GROBID for research papers only when `BIBLICUS_GROBID_URL` is set (else the typed skip
  `grobid_not_configured`). The OpenAI key is read from the SSM SecureString named by the stack parameter
  `EnrichmentOpenAiKeyParameter` (environment variable `ENRICHMENT_OPENAI_KEY_PARAMETER`); without it the summary is the typed skip
  `openai_not_configured` and the item is `degraded`. The router Lambda has no `pypdf`, so a PDF source ends `capture_failed`
  (`unreadable`) until it is bundled; HTML sources and everything else work.
- **Where it is stored.** `ENRICH#<sourceId>#<rev6>` in the monitoring table: `status` (`ready`, `degraded`, `capture_failed`,
  or `pending` while a retry waits), `final`, `attempts`, `nextAttemptAt`, and `curation` in the shape of a reference curation
  card (capture with typed `reason`, `signals`, `paper`, `page`, `summary`, `grobid`). The big text (captured article, GROBID
  fields and TEI) goes to the stack's private `EnrichmentBucket` under `enrichment/<monitor>/<sourceId>/<rev6>/` (DynamoDB items
  stop at 400 KB); the row holds only the keys.
- **Retries, never forever.** A transient failure (timeout, connection, 5xx, DNS; a busy model or GROBID) schedules another attempt
  on a later run (5 minutes, then 10), at most three attempts in all. After that the row is final with whatever exists and the
  decision proceeds. Any other outcome is final at once. An unexpected bug is recorded on the row (`errors`) and also proceeds.
  Lambda time is the only other bound: with less than `MIN_REMAINING_SECONDS` left, enrichment continues next run (nothing is
  posted for that item meanwhile). Finished stages are never repeated.
- **Paper items.** Enrichment has no per-source switch: with an enricher configured, every item of a live router is enriched, and a
  `feed` or `huggingface-papers` item is no exception. For an arXiv address the capture goes straight to `https://arxiv.org/pdf/<id>`
  (not the abstract page); without `pypdf` in the router Lambda that ends `capture_failed` (`unreadable`), the summary is skipped
  (`no_text`) and nothing of the paper reaches the decision. So that the decision still has something to read, `build_item` uses the
  item's `details.abstract` as the summary when enrichment gave none (as web search does with its snippet), and an enrichment summary,
  when there is one, replaces it. Once the PDF can be read, enrichment would send the full text and a model summary instead, and
  fetch one PDF per item from arXiv. Skipping enrichment for items that already carry an abstract needs a router change (a per-source
  or per-config switch in `enrichment_for`); today's config has none.
- **The decide payload.** `item.values` = `{title, url, source, sourceItemUrl, summary, text}` where
  `text = title + "\n" + url + "\n\n" + summary + "\n\n" + <full captured text>`. The captured text travels only inside `text`
  (Cyclotron reads only `text`; a separate `body` value would send the article twice and is refused). A part that does not exist (no summary,
  no capture) is left out, and `text` falls back to `title\nurl`, the previous shape. The router sets no length limit of its own;
  Cyclotron applies its own input policy.
- **Delivery copy.** After a Reference is delivered, `copy_curation` writes the item's curation onto it in the shape #797 uses: a
  `curation` `ReferenceAttachment` card (`origin.kind = "item-enrichment"`) and `ModelAttachment` bodies `curation-text`
  (and `curation-grobid`, `curation-grobid-tei` for papers), plus `summary` in the Reference's `metadata.json`. The text is the
  full capture, so the panel can show more than the lab was sent when the body was cut. A Reference that already has a card keeps
  it. A failed copy never fails the delivery (`publications.<pub>.curationCopy` says `copied`, `kept` or `failed: ...`); the
  procedure then fills the gap. Counts: `enriched`, `enrichmentWaiting`, `curationCopied`, `curationCopyFailed`.
- **Editor corrections** (`correctReferenceCapture`) stay a per-Reference new version of the card. Feeding a correction back as a
  new item revision, so the lab decides again on the corrected text, is deliberate future work and is not implemented.

### What the stack needs

`EnrichmentBucket` (private, SSE-S3, retained), `EnrichmentOpenAiKeyParameter` (SSM SecureString name; the role may `ssm:GetParameter`
only that name) and optional `EnrichmentGrobidUrl`; environment `ENRICHMENT_BUCKET`, `ENRICHMENT_OPENAI_KEY_PARAMETER`,
`BIBLICUS_GROBID_URL`. Link exploration during enrichment searches with Tavily: stack parameter `TavilyKeyParameter` (default
`/papyrus/shared/tavily-api-key`; empty disables) sets `PAPYRUS_TAVILY_KEY_PARAMETER`, and `RouterTavilyKeyPolicy` (and `CollectorTavilyKeyPolicy` for the collector function, which also gets `PAPYRUS_TAVILY_KEY_PARAMETER` for `web-search` sources) grants `ssm:GetParameter` on
exactly that parameter plus `kms:Decrypt` through SSM only (`kms:ViaService`). `RouterEnrichmentStoragePolicy` grants `s3:GetObject`/`PutObject` on `enrichment/*` of that bucket and
`createModelAttachmentDownload` on the seven site APIs (to read back a Reference's `metadata.json` before adding the summary). The
router zip now also carries the capture and curation modules (about 245 KB; `build.py` follows absolute `papyrus_content`
imports and subpackages). With `ENRICHMENT_BUCKET` unset the router behaves exactly as before.

## Delivery

For each positive publication the router runs the existing `ReferenceIntake` over IAM-signed
AppSync: a `pending` Reference (never an upsert, so human curation is never reset), plus the
`discoveredByMonitorId` (and `discoveryDetails`, `discoveryRule` where the source has them) on the Reference. No provenance Message is written (Messages come only from people); the Cyclotron decision lives in the `relevance_decision_is` relation. The
Reference's rationale line ends with the decision so editors see it in the queue. Delivered
flags, attempts and errors are kept per publication per item; one failing backend never loses
the others, and a rerun skips what is already delivered. The publication needs exactly one
canonical `KnowledgeCorpus`.

Intake matches an existing Reference by canonical URL whatever its status and reuses it, with one exception: a Reference
the machine archived as an unreviewed citation stub (`papyrus references retire-citation-stubs`, see
[citation stubs](reference-curation-pipeline.md#citation-stubs-archived-and-brought-back-by-a-monitor)) goes back to
`pending` with its feed keys, and the receipt says `referenceRestored`. The router then records the Cyclotron's prediction on it as it does for
any delivery. A rejected Reference, or one archived by a person, is reused exactly as it is.

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

Always, when `mode` is `live` and the monitor's decisions come from Cyclotron (there is no feedback switch; a `feedback` field left in a stored config is ignored and logged as retired; `direct` and `hold` monitors have nothing to correct).

**The pass starts from the votes.** For each publication the router lists the current References an editor has accepted or rejected (`referencesByCurationStatusKey`, two indexed queries; a person's vote is the only thing sent, so
the pending References, thousands of them, are never read), looks up the `DELIV#<pub>#<referenceId>` row of each, and sends the votes of the References this monitor delivered. A vote on a Reference another monitor delivered is that
monitor's to send. Until 2026-11-02 the pass walked every delivery, read each Reference one by one and rotated the rows to the back of a queue, so it took hours to reach a new vote, used the Lambda's time up (it stopped on the time budget in about one run in ten) and
never saw a vote again once it had been sent. The cost now follows the number of votes, not the number of deliveries, and it is bounded only by the run's remaining time.

`accepted` maps to `include` and `rejected` to `exclude` for that publication's output. The editor comes from
`curationStatusUpdatedBy`. A human curator is any of `user:<x>` (CLI), the editor's sign-in email (what the
newsroom UI records), a Cognito username (`google_<digits>`) or a Cognito sub (UUID). A missing actor, the
worker's own actor and every other machine actor (`ai`, `system:*`, `worker:*`, `papyrus*`, `*-import`, the
"Papyrus newsroom" fallback, `auto:cyclotron`, `auto:rule`) are not votes and are never candidates. The feedback is sent in the
decision contract: `caller` is the publication's configured `site` and `reviewer` names who voted. Cyclotron stores
the reviewer as free text, and it must never be an email address, so the reviewer sent is:
`user:<x>` as is (when `<x>` is not an email); `cognito:<sub>` for a bare Cognito sub; otherwise
`editor:` + the first 32 hex characters of `sha256(publicationId + ":" + lowercased actor)`.

**The explanation travels with the vote.** The editor's written reason (the Reference's `curationStatusReason`, trimmed) is sent as the feedback's `comment`, which the Cyclotron stores with the label (any text, no length limit; it is
free text for a person to read, not a code). An absent or blank explanation sends no `comment` at all. The rejection reason *code* (`other`, and so on) is not part of the feedback contract and is not sent.

**Request ids and changed votes.** `requestId = sha256(referenceId \n curationStatus \n curationStatusUpdatedAt [\n explanation])`, the explanation line only when there is one. A retry of the same vote is the same request, and the Cyclotron
answers an identical request with the label it already has. A vote that changes (another status, a new time, or only a new explanation) hashes to a new request and is recorded as a new label for that item; the Cyclotron appends
labels (its `item_feedback` table is keyed by request id and refuses the same id with different content, 409), so an editor who accepts and later un-accepts, or who adds an explanation afterwards, sends a correction, and a vote
that was sent before this was possible is sent once more with its explanation. A vote with no explanation keeps the id it always had, so nothing already sent is sent again. A vote with a final receipt (`FB#<requestId>`: `sent`, `stale`, `refused` or `invalid`)
is counted as `unchanged` and costs one read; `uncertain` answers and `publication binding changed` leave no receipt and are asked again next run.

The result counts `sent`, `unchanged`, `skipped` (a vote that cannot be sent: criteria changed, or the decision receipt has no item revision), `pending` (an uncertain answer, retried next run) and `failed`.
The item revision and output come from the stored decision receipt.

## Automatic acceptance

A pending Reference that nobody voted on is accepted by the router itself, per publication. It runs as **its own task**, `{"task":"auto-accept"}`: every hour the schedules `papyrus-monitoring-hn-auto-accept` (minute 41) and
`papyrus-monitoring-web-distinctive-auto-accept` (minute 11, because the hn router does not list Distinctive Mark) start the task, which only fans out one invocation per publication whose `autoAccept` is not off
(`{"task":"auto-accept","monitorId":"hn","publicationId":"anth-us"}`), the same way [monitor stories](#monitor-stories-daily) do. Each invocation has the Lambda's whole time budget and its own lock (`LOCK#auto-accept#<publicationId>`), so a
routing run never holds it up or is held up by it. It used to follow the sweep and the feedback pass in every routing run and was skipped (`"reason": "time budget"`) whenever they had left less than 120 seconds: in about one run in
four in the last 48 hours of receipts (105 of 379 passes for Anth.us) and one in nine since 28 October (640 of 5,447 across the publications). The two schedules are new template resources, so they exist only after a change set for `papyrus-monitoring` is
executed; until then nothing runs the pass (the receipts, which go back 30 days, show it has not accepted anything: every pass either hit the time budget or found no confidence that reaches the target precision). It is **on for every publication** and runs only in `live` mode for monitors whose decisions come from Cyclotron. The publication's router entry
may carry

```json
"autoAccept": {"enabled": true, "precision": 0.9, "latencyQuantile": 0.9}
```

All three keys are optional; with no block, or with `{}`, it runs with those defaults, and `{"enabled": false}` turns it off. `precision` and `latencyQuantile` are numbers above 0 and below 1, unknown keys are refused
(`validate_router_publications`). Code: `src/papyrus_content/auto_accept.py`; spec: `features_backend/reference-automatic-acceptance.feature`.

* **Threshold, learned per publication.** Each human vote on a Reference (accepted or rejected, actor a person) whose Cyclotron verdict is the positive label pairs the verdict's
  `confidence` (stored on the `relevance_decision_is` relation; its `score` when a decision has no confidence) with accepted or rejected. The threshold `t` is the smallest
  confidence such that, among those votes with confidence at or above `t`, the Wilson 95% lower bound of the accept rate is at least `precision`. If no `t` qualifies (too few votes, or votes that
  disagree) nothing is accepted and the reason is logged. Automatic acceptances are not votes and never teach the threshold.
* **Delay, learned per publication.** The nearest-rank `latencyQuantile` of the time from a Reference's `createdAt` to a human vote, over all the publication's human votes. Without any vote, nothing is accepted.
* **Write.** `curationStatus=accepted`, `curationStatusKey`, `reviewedFeedKey`, `curationStatusUpdatedAt`, `curationStatusUpdatedBy="auto:cyclotron"` and a `curationStatusReason` naming the confidence, the
  threshold, the estimated accept rate, its lower bound, the number of votes and the delay; plus the vote's details on the Reference itself (`curationActorKind` is `cyclotron`, never a human label; no Message is written). A Reference an editor
  touched (any person as the last actor) is left alone.
* **Feedback.** `auto:cyclotron` is not a person, so [Feedback](#feedback) skips it. An editor who later Rejects or re-Accepts the Reference replaces the actor, and that vote is sent like any other, with the editor's explanation.
* **Undoing it.** An automatic acceptance is a pending Reference with a different actor, so it is reversible by the ordinary Reject. The newsroom marks it "Accepted automatically" on the card, the list row and the detail (and the reason says why), and a Reject
  there stores the editor as the actor with the editor's reason, which then trains the threshold and reaches the Cyclotron. What an acceptance sets going and what undoing it leaves behind: the Reference joins the accepted evidence at once, so the next
  [monitor stories](#monitor-stories-daily) run may file an idea from it (a filed idea stays in the Idea column, where a person decides; nothing in the router withdraws it when the Reference is rejected later), the next vector sync re-marks its vectors (a rejected Reference
  is excluded again), and the weekly Knowledge Map and wiki runs count accepted References only, so they drop it at the next run. Nothing is published by an acceptance alone. The console's per-status counts (the incremental NewsroomSummary) are moved by the editor's own Accept and Reject,
  and now by this pass too: after the pass it sends one `updateNewsroomSummary` delta per publication (pending down and accepted up by the number accepted, overall and for the corpus), and a rule acceptance sends its own delta, as does the backfill
  (once for the whole pass). A failure to send it never undoes an acceptance: it is logged as `{"autoAccept": "summary-failed", ...}` and the next summary rebuild repairs the counts. **Not yet working from the router:** `updateNewsroomSummary` is authorised for the
  `editor` and `admin` groups only and `RouterAutoAcceptPolicy` does not grant it, so a router pass logs `summary-failed` until that mutation also allows the router's IAM identity and the policy lists `Mutation/fields/updateNewsroomSummary` for each API. The CLI (`papyrus references auto-accept`), which signs in as an editor, updates the counts today.
* **Monitors that deliver by a fixed rule** (`decisions: "direct"`, such as TTAB for Distinctive) have no confidence: the rule match is the acceptance. A newly delivered Reference is set to accepted on delivery with
  `curationStatusUpdatedBy="auto:rule"` and a reason naming the monitor and the rule. Same switch (`autoAccept.enabled`), same Reference fields (`curationActorKind` `rule`), never sent to Cyclotron, an editor can still Reject it.
  `papyrus references auto-accept --site KEY [--dry-run]` applies it to deliveries that already exist (the dry run lists them), and also runs the confidence pass; the monitors it treats as rule monitors are those whose `discoveryRule` says `system = "direct"`
  or whose deliveries in the corpus carry no Cyclotron verdict at all.
* **The newsroom** shows "Accepted automatically" (and "(by rule)") with a Lucide icon on the feed card, the list row and the detail, apart from an editor's accept.
* <a id="reviewing-what-was-accepted-automatically"></a>**Reviewing what was accepted automatically.** The References page has an **Accepted automatically** filter in the list view, opened by the address `/newsroom/references?status=auto-accepted`.
  It lists every current Reference whose actor is `auto:cyclotron` or `auto:rule` (the two are told apart by a "Accepted by the Cyclotron" or "Accepted by a monitor's rule" line under each card, which also gives the recorded reason, the time, and for the Cyclotron how sure it was),
  newest acceptance first, as the feed's cards with the same Accept and Reject buttons. A Reject asks for a written reason in the same box as elsewhere, is saved as the editor's vote (so it trains the threshold and reaches the Cyclotron like any other), and takes the card out of the list; so does any later vote of an editor.
  **Accept confirms it**: it records the editor's own vote (the actor becomes the editor, so `isAutoAccepted` is false, the threshold learner counts it as a human vote, and the router's feedback pass sends it to the Cyclotron with a new request id, because the vote's time changed) and takes the card out. The same reason box is offered first and the explanation is optional (it travels as the feedback `comment` when given; a blank one sends none); nothing is sent until the editor taps Record, or until they tap Accept with words already typed. The feed card and the detail pane treat an automatically accepted Reference the same way: neither shows Accept as already chosen. The empty state says that nothing has been accepted automatically yet. There is no count on the filter: the Newsroom summary counts by status, not by who accepted, so a number could not be kept right.
  **How it reads, with no new index:** a page is one filtered query of `listReferencesByCurationStatusAndUpdatedAt` for `accepted` (newest `curationStatusUpdatedAt` first, 200 rows looked at per database read),
  where the database applies `versionState = current`, the References feed key and `curationStatusUpdatedBy = auto:cyclotron OR auto:rule`; the list keeps reading forward only until a page of 24 is full, and the next page continues from the cursor (`lib/auto-accepted-references.ts`, `loadAutoAcceptedReferencePage`). Only matching rows cross the wire, and nothing reads the whole table.
  The cost of a page is the number of accepted References between the newest and the 24th automatic one, so it is cheap while automatic acceptances are a large share of recent acceptances, and grows (never beyond a walk of the accepted partition, 200 rows per read) when they are rare.
  If that ever matters, the fix is a sparse index on a key written only for automatic acceptances (`autoAcceptedKey`, sort `curationStatusUpdatedAt`); a new index on these tables is its own deploy followed by a backfill (see the held PR 1035), so it is deliberately not part of this feature.
  Try it with `npm run dev:preview` and open `/newsroom/references?status=auto-accepted`; the seeded data has both kinds. Tests: `npm run test:auto-accepted-list` and `features_backend/reference-automatic-acceptance.feature`.
* **Log.** One JSON line per publication per run: `{"autoAccept": "ran|skipped|failed|dry-run", "publicationId", "targetPrecision", "latencyQuantile", "threshold", "estimatedPrecision", "precisionLowerBound", "votes", "delaySeconds", "latencySamples", "candidates", "accepted", "reason"}`;
  the same under `autoAccept` in the run result and receipt (plus `summaryUpdated`, whether the Newsroom summary delta was sent). A rule acceptance logs `{"autoAccept": "rule", "publicationId", "monitorId", "referenceId", "accepted"}`.
* **Cost.** Reading the votes is one indexed query per voted Reference, and per waiting Reference for candidates, bounded by the run's remaining time (it stops with a logged reason, never fails the run).
* **IAM.** It needs `listReferencesByCurationStatusKeyAndUpdatedAt` and `updateReference` on each publication's API (`RouterAutoAcceptPolicy`); without them the pass logs `failed` and the run goes on.

## Cyclotron status for the newsroom home page

The newsroom home page (`/newsroom`) shows the Cyclotron classifier behind this site's predictions: when it last changed or was retrained, its latest
evaluation number and what that number was measured on, and counts such as the reviewed labels. The router keeps what that page reads.

* **The task.** `{"task":"cyclotron-status","monitorId":"hn"}` (also for `web-distinctive`) calls the Cyclotron's read-only `status` operation for each
  publication the monitor lists, on the machine lane (`POST /machine/bindings/<publicationId>/operations`, body `{"contractVersion", "operation":"status", "payload":{}}`).
  It runs hourly (`papyrus-monitoring-hn-cyclotron-status` at minute 26, `papyrus-monitoring-web-distinctive-cyclotron-status` at minute 56), without retries.
  It is its own task: its own lock (`LOCK#cyclotron-status`), no Router, no decision, no feedback, no receipt. A sweep and a status read never wait for each other.
* **A 503 is not a pause.** The Cyclotron answers 503 "no verified publication status snapshot yet" while a binding has no completed decision. The status task
  treats that as that publication's "no snapshot yet" and never records a lab backoff, so it cannot stop a sweep. It does honour a pause the lab already asked for.
* **Where it is kept.** One row per publication in the monitor's partition, `CYCLOTRONSTATUS#<publicationId>`: the whole `cyclotron-status/v1` snapshot, its own `asOf`,
  the publication's `output` and `checkedAt`. A publication the Cyclotron has no snapshot for has no row; an older row stays until a newer snapshot replaces it, with its own `asOf`.
  Nothing is written to any site's backend, so this needs no IAM grant and no data-model change.
* **Who sees what.** The Monitoring view serves it as `monitoringPage(list: "cyclotronStatus")` (publication scope only). A monitor contributes only the row of the publication
  whose `appsyncEndpoint` is the signed-in site's own, so a shared Cyclotron run never shows another site's classifier. The CLI reads it with
  `papyrus monitors page --list cyclotronStatus` on the signed-in lane.
* **Freshness.** A snapshot is only as fresh as the binding's last completed decision, so votes made after it are not in it; the page shows the snapshot's `asOf` and says so.
  Votes do not train hosted runs today, so expect zero refits and possibly zero labels, which the page says plainly.
* **The report.** The same task also calls the Cyclotron's read-only `report` operation (body `{"contractVersion", "operation":"report", "payload":{}}`, never a `requestId`; the lab
  answers 400 to one) for each publication, right after its `status` call and honouring the same time budget, and keeps this publication's own output (`outputs[<output>]` of the
  `cyclotron-classifier-report/v1` answer, with the answer's `schema` and `generatedAt` added) in the same row under `report`, with `reportCheckedAt`. No new schedule, table or page read.
  It holds the classifier (revision, question, rubric, classes), `learning` (state, reason, version, refits, last change), `agreementWithEditors` (votes, compared, agreed, by classifier
  revision and by day), `heldOut`, `counts` (labels by name, reviewed decisions, primed examples, decisions without a label in the engine) and `model` (features, weights, reason).
  The report answers 200 before a first decision, when `status` answers 503, so a row may hold a report and no status. A report for another output is never stored.
* **The two reads are independent.** The row is merged, not overwritten: a failed `status` keeps the last good status, a failed `report` (including a 503, which is an ordinary failed read
  and never a lab pause) keeps the last good report and its `reportCheckedAt`. The run's print line has `cyclotronReport` per publication and `reportReasons`; the task result has `reports`.
* **Row size.** DynamoDB refuses an item over 400 KB. A report that would take the row past 300,000 bytes is cut down before it is stored: the model's features and weights first
  (`model.reason` then says so), then the oldest days of agreement; the stored report lists what was cut in `trimmed`, and the home page says some of it was left out. The run's print line
  has `trimmedReports`. Votes grow the report only by one entry per day and per classifier revision, so this is a guard for a large fitted model, not an expected case.
* **What it costs.** The report read takes 0.2 to 6.4 seconds and grows with the number of votes; it runs once an hour per publication and never on a page view.
* **On the home page.** The panel shows learning and its reason, the most recent cycle, agreement with reviewers as "agreed of compared" ("Not compared yet" when none was compared, never 0%,
  and never called accuracy), agreement by day and by classifier revision, the held-out evaluation (a percentage, or the report's reason), and counts of labels, reviewed decisions and primed examples;
  the expanded details add the question, classes, rubric and the supporting questions and weights (or the report's reason when there are none). Votes are compared only for decisions the Cyclotron
  filed by item, which it does from its release with the report on, so earlier votes count but show as not compared. A site on an older Papyrus version, and any row before the router's first
  run with the report, has no report and shows the status-only panel. `lib/hosted-cyclotron-status.ts` parses it (`parseHostedReport` drops an unknown schema or a section out of shape).

Specs: `features_backend/monitoring-cyclotron-status.feature` and `features/newsroom-home-cyclotron.feature`.

## Monitor stories (daily)

Once a day the router files a short, cited story idea for every item the monitors found that an editor (or the [automatic acceptance](#automatic-acceptance)) accepted and that has no idea or story yet.
It is the router task `{"task": "monitor-stories", "monitorId": "hn"}`, run by the EventBridge Scheduler schedule `papyrus-monitoring-hn-monitor-stories` (`MonitorStoriesSchedule`; it names no site) at **07:30 UTC** every day (03:30 US
Eastern, so the ideas wait for the morning's review). It does not depend on the weekly knowledge-run stack, which also re-projects the public site: that is why it lives here, and why
every publication the `hn` monitor lists gets it, whether or not it has the stack. Code: `src/papyrus_content/monitoring_stories.py` (the task) running the library behind
`papyrus ideas monitor-stories` ([idea pipeline](idea-pipeline.md#monitor-stories)) in process; spec: `features_backend/monitoring-daily-stories.feature`.

* **A plan and a queue (2026-11-06).** The daily run used to read the publication and then draft for as long as the Lambda's 600 seconds lasted (`RouterFunction` `Timeout`), keeping 120 of them in reserve (`MIN_REMAINING_SECONDS`), and stop on that time whether or not it had drafted anything useful. On 2026-11-04, -05 and -06 Machines on Machines stopped on `time` after 9, 9 and 8 attempts: the vector pass took 121, 107 and 119 seconds, the signals 112, 103 and 160, and drafting got what was left, 214, 267 and 199 seconds at about 25 seconds an attempt. Nothing it had filed was lost; what was thrown away was the next day's start, because the whole read was done again. With the story queue the task (`plan_publication`, `ideas/story_plan.py`) only PLANS: it runs the vector pass as before (it already reads only what changed since its saved place; the 119 seconds of 2026-11-06 were its one-time first run on the site, `bootstrapped: true`, 2,269 Reference summaries), reads the publication once (signals, packs, candidates), stores each step of the ordered queue as a row in the router's table (`STORYPLAN#<publication>#<plan>#E#<n>`: the pack, or the item with its connections) with the context and the existing ideas in a head row, and sends one message per step to the FIFO story queue (`StoryQueue`, the publication as message group, so its steps run in order and one at a time). `StoryWorkerFunction` (300 seconds, its own role) takes one step per invocation and drafts it with the same code, the retry memory, the point check, the dedupe and the Humanus gate as before; it files the idea at once, writes a `STORYDONE#...` row, and adds the ideas to the plan's ONE soft review request (`rr-batch-<plan id>`, extended as steps file ideas). A step that fails for a reason that says nothing about the Reference (a model error, a filing error) is delivered again by the queue, up to three receives, then waits in `StoryDeadLetterQueue` (alarm `papyrus-monitoring-story-dead-letters`); its last try leaves a DONE row marked failed, so the plan still finishes. The step that completes the plan writes the plan's one log line (`{"monitorStories": "finished", ...}`) and settles the curation flag, once. There is no time stop and no cost stop on a plan: it is bounded by its number of steps, and one step by `MAXIMUM_STEP_COST_USD` (0.50) against one oversized request. There is no per-site proposal rate and no daily count, and there never was; the only learned limits are the duplicate cut (learned once per plan from the editors' decisions and stored in the plan's head) and the point check. Nothing is drafted twice: a filed idea links its Reference `based_on` (so the next plan does not offer it), a rejected one waits in the retry memory until something new is known about it, an unfinished plan is not planned over (the task logs `waiting` and still runs the vector pass), and a redelivered message finds its DONE row and does nothing. A Reference with nothing to add (`nothing_to_add`) is still looked at again by the next plan, as before: it costs a page read and no model call, and a summary or a link may have arrived. A router with no `STORY_QUEUE_URL` (the tests, a hand run) still drafts in process as described below, bounded by the Lambda's remaining time. Operator notes: a stuck plan (its pointer row `STATE#storyPlan#<publication>` not finalized and no message left) is cleared by deleting that row; the queue's dead-letter messages are redriven in SQS once the cause is fixed. Spec: `features_backend/monitoring-stories-queue.feature`.
* **One publication per invocation (fan-out).** The scheduled run has no `publicationId`: it reads the monitor's config, invokes the router function itself asynchronously (`InvocationType: Event`, its own ARN from the Lambda context, granted by `lambda:InvokeFunction` on `RouterFunction.Arn` in `RouterIdeaPolicy`) once per publication whose `monitorStories` is on, returns `{"status": "fanned-out", "publications": [...]}`, and takes no lock and drafts nothing. Each invocation `{"task": "monitor-stories", "monitorId": "hn", "publicationId": "<id>"}` runs only that publication with the whole Lambda budget (a single run used to split 600 seconds among six publications, and most stopped on time before drafting). Adding a publication to the monitor's config adds it to the fan-out; the template names no site. A publicationId the config does not list returns `{"status": "error", "reason": ...}` and runs nothing. A per-publication run takes the lock `LOCK#monitor-stories#<publicationId>` instead of `LOCK#router`, so the runs, and the hourly route pass, do not make each other return `locked`; a second run of the same publication does. **Retries:** `RouterInvokeConfig` sets zero async retries, so a failed publication run is not repeated (it goes to the dead-letter queue; the next day's fan-out or a hand run covers it); even if retried, filing is idempotent by id, so nothing would be filed twice.
* **On by default, per publication.** The publication's router entry may carry `"monitorStories": {"enabled": false}`; no block, or `{}`, means on. `store` is `items` (the default; a legacy value `proposals` is read as `items`) or `json`; any other key is refused (`validate_router_publications`).
* **The standard (no setting).** An idea is filed only when it says more than a summary of its Reference. It rests on something the newsroom already knows beyond its source (an editor's accept reason, a comment, a related Reference), and a second model call, the point check, must find a claim in it that its sources do not make; the check fails closed, and a pack idea is checked against the References it cites. A Reference with nothing to add is skipped as `nothing_to_add` before the model is asked. A Reference or pack whose draft was rejected is skipped as `already_rejected` until a new connection appears for it (a comment, an accept reason, a related Reference, a confirmed link, an explanation on a link); the router keeps that memory in its own table (rows `IDEA_REJECTED#<publication>#<digest>`, the table and role the vector pass's watermark already uses), with no count and no day window. A run that files nothing for any of these reasons raises one curation flag in the Notification Center. The router log line gains `nothingToAdd`, `alreadyRejected`, `retriedWithNewConnections`, `connectionsUsed` and `curationFlag` ([idea context packs, section 9](idea-context-packs.md#9-the-standard-an-idea-is-more-than-a-summary-of-its-reference)). The flag needs `listReviewRequests` and `updateReviewRequest` in `RouterIdeaPolicy` (both are there) and `createReviewRequest`, which the per-API review policies grant. The old `minimumStandard` key is retired: a stored config that still has it loads, and the key is ignored (the log shows `ignored_retired_config`).
* **Single items and context packs (`singleItem`, `contextPacks`).** Two more keys, both on by default and neither numeric. `singleItem` (true or false) keeps or drops the single-item ideas. `contextPacks` is `{"enabled": true|false, "signals": [...]}`: `signals` names the pack signals to use from the closed set `conversation`, `acceptance`, `hub`, `cluster`, `resurfaced`, and leaving it out means every signal that has data (today `conversation` and `acceptance` build packs; the others are accepted by the validator and build nothing until they exist). With `contextPacks.enabled` false the task is exactly the single-item task described below, ranked by the relevance Cyclotron; with it on, the run is the queue below. Any other key is refused. Example: `"monitorStories": {"singleItem": false, "contextPacks": {"signals": ["acceptance"]}}` drafts only theme ideas from accept bursts.
* **One queue of packs and single items (context packs on).** `run_publication` reads the publication once (`ideas/signal_inputs.py`: Messages, human votes, concept links, pending verdicts, published Items and ideas), loads the lookups the packs need (`ideas/signal_queue.py`: accepted SemanticNodes for concept names and hashtags, the Reference summary Messages of the References a pack shows, the mission, policy and sections), builds the packs (`ideas/context_packs.py`), keeps the signals the publication asked for, holds back every pack whose anchor already has an idea unless it has new evidence (`packsSkippedNoNewEvidence`), scores the single-item candidates from the same inputs (`ideas/item_signals.py`; a Reference the signals say nothing about is not a candidate) and walks ONE ordered queue in which the signals take turns by surprise. A pack goes to `ideas/pack_stories.py` (one model call, up to three ideas that each cite at least two accepted References, each through the same editorial gate), a single item to the single-item path. Both draw on one cost meter and share the stops below; pack ideas are in the same one review request as the single items. A Reference summary is the `reference_summary_<N>_tokens` Message linked to it (the highest budget, the newest); the router has no storage grant, so a Reference without one has an empty summary in a pack. Spec: `features_backend/idea-context-packs.feature`; the command is `papyrus ideas monitor-stories [--packs-only | --single-only]` ([idea pipeline](idea-pipeline.md#monitor-stories)).
* **What an idea is.** A content `Item` at the `idea` stage, marked "Generated", that cites its source (every sentence carries the source handle and passes the citation check), filed through the same code as the CLI, with
  **one soft review request per publication and pass** ("N new monitor stories to review", raised by `idea-pipeline`, linking the ideas). Nothing is published; an editor accepts an idea by moving it forward on the Stories board and declines it by moving it to `spiked` with a reason. The router does not run the Humanus gate (it has no editorial grants), so its ideas are filed ungated. A Reference is never drafted twice (the Item's `based_on` link to it records it, spiked ideas included), so the task can run every day and a re-run is harmless.
* **Which items.** Only `curationStatus == accepted` (by an editor, `auto:cyclotron` or `auto:rule`). Pending ones are counted as `notAccepted` and not read. Items judged not relevant, already drafted, already promoted to an
  item, from an excluded host, or handled by an Automation (a story is already `based_on` it, or a monitor-triggered Automation has a procedure run for it that is completed, deferred or in flight; read from the router's own trigger rows, counted as `handledByAutomation`) are left out. An Automation merely configured for the monitor handles nothing. Best first: the Cyclotron's score times a freshness weight learned from the site's own editors.
* **No fixed number.** The old `limit: 3` is not used. The task drafts every candidate, and only a real constraint stops a publication; `stoppedBy` says which:
  * `time`: the Lambda's remaining time. The publications still to run share what is left equally, so a big backlog cannot starve another publication; what one publication does not use passes on, and a publication
    the time stopped gets another pass while at least 240 s remain. The rest is picked up by the next day's run, which starts again from the same ranking and skips what is drafted. Each idea is filed as soon as it is kept, so a stop loses nothing paid for. Reads of a publication's References run eight at a time (a site with thousands of accepted References needs two queries each).
  * `cost`: the model spend of one publication's run reached `MAXIMUM_COST_USD` ($0.50). At `gpt-6-luna` prices (about $0.0007 an idea) the time budget stops a run far below that; it is a backstop against a runaway loop, not a quota.
  * `file_error`: an idea could not be filed, usually a missing grant. The publication stops after the first failure rather than pay for ideas that cannot be kept; the line carries `fileError`.
* **Model and key.** `gpt-6-luna` only. The key is the SSM SecureString that `ENRICHMENT_OPENAI_KEY_PARAMETER` names (the one item enrichment uses; `RouterEnrichmentKeyPolicy` already allows reading it), read only for this task. Without it every publication logs
  `skipped` with `reason: "openai_not_configured"`.
* **A stopped run raises no curation flag.** The empty-run curation flag ("No ideas today", the Notification Center) is raised only by a run that got through its candidates. A run that `stoppedBy` `time` or `cost` says nothing about curation, and neither does one whose References still wait for their suggested links (`suggestionsWaiting`, from the vector pass's backlog): `settle_curation_flag` returns `not_needed` with a note. A run that finished and filed nothing still raises it.
* **Live mode only.** A router in `dry-run` mode writes to no publication, so the task does nothing.
* **Log.** One JSON line per publication, after its last pass: `{"monitorStories": "complete|stopped|skipped|disabled|failed", "monitorId", "publicationId", "drafted", "candidates", "notAccepted", "skipped", "stoppedBy", "notMonitored", "attempted", "failedTheCheck", "duplicates", "handledByAutomation", "costUsd", "packs", "ideasFromPacks", "packsSkippedNoNewEvidence", "packDetails", "review"}`
  (`candidates` and `notAccepted` are what the run found when it started; `skipped` counts items with no text to write from). `drafted` counts every idea filed, pack ideas included. `packs` is the number of packs offered after repeats were held back, `ideasFromPacks` the ideas they produced, `packsSkippedNoNewEvidence` the packs held back because an idea already covers their anchor and nothing new arrived, and `packDetails` lists, for each pack the run reached, `{signal, anchor, correctedPValue, ideas}`. With context packs on, `candidates` counts only the single items the signals single out. The same object per publication is under `monitorStories` in the run result and receipt.
* **Distinctive Mark has its own schedule.** It appears only in the `ttab` and `web-distinctive` monitor configs, not in `hn`, so `papyrus-monitoring-web-distinctive-monitor-stories` runs `{"task": "monitor-stories", "monitorId": "web-distinctive"}` at the same hour, granted by `RouterMonitorStoriesDistinctivePolicy`. Its TTAB References are drafted here too, except those its Automation has already made or is making a story for (`handledByAutomation`).
  To give another publication the task, schedule it for a monitor whose router config lists it (and add that publication's API to the two `RouterMonitorStories…Policy` grants).
* **IAM.** `RouterMonitorStoriesPolicy` and `RouterMonitorStoriesSharedSitesPolicy` (two because one managed policy holds at most 6,144 characters) list, for the six publications of the `hn` monitor, exactly these fields: `listStoryDrafts`
  (read-only: old story drafts filed as Proposals, for the dedupe until a site has migrated), `createReviewRequest`, `getReviewRequest`, `listReferencesByCurationStatusKeyAndUpdatedAt`, `listSemanticRelationsByObjectState` (provenance), `listSemanticRelationsBySubjectState` (the verdict), `listItems`, `itemBySlug`,
  `listNewsroomSections` and `listAutomations`. A test (`test_monitoring_stories.py`) records the fields a full run asks for and fails if the grant is not exactly that, on every API.
* **Idea policy (`RouterIdeaPolicy`).** Filing ideas as Items, and the editorial gate that checks each one first, need one further managed policy, `RouterIdeaPolicy`, in `infra/monitoring/papyrus-monitoring.yaml`: `Query/getItem`, `Query/getPublishedItem`, `Query/listReferencesByLineageAndVersion`, `Mutation/createItem` and `Mutation/updateItem`. **Context packs** add their reads and writes to this same policy (still one policy: `RouterRole` has 18 of 20): `Query/listMessageThreads` and `listMessagesByThreadAndCreatedAt` (the publication's conversations), `listReferencesByCurationStatusKeyAndUpdatedAt`, `listSemanticRelationsBySubjectState` and `listSemanticRelationsByObjectState` (votes, concept links, verdicts, summary links), `listItems` (stories and existing ideas), `listItemsByLineageAndVersion`, `getReference`, `listReferenceAttachmentsByReferenceLineageAndSortKey`, `getSemanticRelation` and `Mutation/createSemanticRelation` (an idea's `based_on` and concept links), `listSemanticNodes` (concept names and hashtags) and `getMessage` (Reference summaries). `test_monitoring_packs.py` records every field the pack path asks for and fails if one is not granted. The router already had `listItems`, `getReference`, `getSemanticRelation`, `createSemanticRelation`, `updateSemanticRelation`, the `listSemanticRelationsBy*State` queries, `getReviewRequest` and `createReviewRequest`. **The editorial gate.** Every idea the router files passes the same Humanus gate as `papyrus ideas monitor-stories --store items`, through the publication's own API: the composed pack of the site's editorial policies. An error-severity violation refuses the filing and is counted on the publication's log line (`refusedByEditorialCheck`, and `failedTheCheck`); warnings and notes are kept on the Item (`generated.check`) and stored as its `EditorialCheckRun`. The judgment lane needs the TypeSafe key: one shared SSM SecureString (parameter `EditorialJudgmentKeyParameter`, default `/papyrus/shared/typesafe-api-key`, passed to the function as `EDITORIAL_JUDGMENT_KEY_PARAMETER`, never an environment literal or a repository file). With no key (parameter empty, missing or unreadable) the Item records `judgment: {ran: false, reason}` and the rules lane still runs. The gate's grants are in the same policy: `Query/getEditorialCheckSettings`, `getEditorialContext`, `getEditorialCheckRun`, `listEditorialFeedbacks`, `listEditorialPolicies`, `listItemsByVersionStateAndUpdatedAt` and `Mutation/createEditorialCheckRun`, `updateEditorialCheckRun`, plus `ssm:GetParameter` on that one parameter and `kms:Decrypt` through SSM. Each field is named exactly and the API is a wildcard (`apis/*`), which in this account is the seven routed publication APIs: one ARN per field per API would need four policies, and `RouterRole` already holds 17 of the 20 managed policies an account can allow per role once the web-search providers are on. A new AppSync API in the account would be covered too. **Deploy steps (no change set has been run yet):** create a change set for `papyrus-monitoring` (reads first; every other parameter `UsePreviousValue`, never omit `EditorUserPoolArns`; `EditorialJudgmentKeyParameter` is new, leave its default unless the key lives elsewhere, and create the SecureString first or accept that the judgment lane is recorded as not run), read it (it should show `RouterIdeaPolicy` attached to `RouterRole`, the new environment variable and the router code update, nothing else), then execute it. Until the change set is applied and a Papyrus release carries the new code, the deployed router keeps running the old code. **Tenant publications:** a publication whose router entry names a `tenantId` is read and written by a tenant client, which asks for `Query/itemByTenantSlug` where the untenanted one asks for `itemBySlug` (the doctrine lookup, slugs prefixed `<tenant>#`); the policy grants it. `test_router_tenant_grants.py` records every field the idea path asks for on the real client with a tenant, packs on and off, and fails if one is not granted on the publication's API. `getEditorialContext` is resolved by the backend's own Lambda with the tenant from its environment (`PAPYRUS_TENANT_ID`), not by the router.
* **The router is single-file.** The task holds the `hn` router lock and the function has reserved concurrency 1, so while it runs (up to the 600 s timeout) the other router runs wait; that is once a day, at a quiet hour. A run that finds the lock held returns `locked` and does nothing; the next day's run catches up (no cap means nothing is lost).

### Vector index and suggestions

Before packs and single items, the monitor-stories task brings each publication's S3 Vectors index up to date with what changed since its last pass (`src/papyrus_content/monitoring_vectors.py`, called first by `run_publication`). Indexing is no longer a manual CLI step, and it is no longer a walk of the site. Spec: `features_backend/monitoring-vector-pass.feature`; design: [idea context packs, sections 3 and 7](idea-context-packs.md). The related-items check that follows a stored vector is described under [Suggest once](#suggest-once).

* **What the pass reads: only what changed.** Ryan's rule (2026-11-04): the cost of the daily pass scales with what changed since last time, not with the size of the site. The pass asks two existing indexes for the rows changed since its saved place, oldest first, a page of 1,000 at a time: `listReferencesByVersionStateAndUpdatedAt` (`versionState = current`, `updatedAt >= place - 10 minutes`) and `listSemanticNodesByVersionStateAndUpdatedAt`. A site with nothing new makes **two AppSync requests** (one per feed) and nothing else: no Reference list, no listing of the vector index, no attachment or text read, no embedding, no write. It does not list concepts, links or message threads either. `test_the_calls_grow_with_what_changed_and_not_with_the_size_of_the_site` and `test_a_site_with_nothing_new_makes_one_read_per_change_feed_and_nothing_else` count the requests over a fixture of 200, 2,000 and 5,000 indexed References.
* **What it does with a changed row** (`vector_index.index_changes`). One `GetVectors` (metadata only, 100 keys a call) asks the index what it holds for the changed References' summary vectors. A Reference that is no longer accepted or pending loses its vectors, found by a `QueryVectors` filtered to that Reference with its own summary vector as the query (not by listing); one whose stored status differs (pending accepted, accepted sent back to pending) has the status rewritten from the stored vector data without an embedding call and, going back to pending, loses its passages; one with no vector, or with a changed `contentHash`, is prepared (attachments and extracted text read for that row only) and embedded. A vote, a star, a prediction or a retitle also change `updatedAt`: the row is read once, its vector is found as it is, and nothing is written. Cards are written for the changed concepts whose card hash differs. A site of 5,000 References where 3 rows were voted on costs 2 feed reads, 3 attachment reads and the same few vector lookups as a site of 200.
* **The saved place** is in the router's table at `STATE#vectorSync#<publicationId>`: `{"v": 3, "since", "seen", "nodesSince", "nodesSeen"}`: the newest `updatedAt` indexed, and the ids (with their `updatedAt`) of the rows within ten minutes of it. The ten minutes cover a writer whose clock is behind (a row written late with an earlier `updatedAt` is read once); the ids stop a row already done from being read again. A page moves the place as soon as it is indexed; a run the time or the cost stops inside a page leaves the place where the last finished page ended and the next run resumes there (what was stored is skipped). A quiet day writes nothing.
* **First run on a site (or an older saved place).** A place written by the earlier pass (a bare time or a `{"v": 2}` object) is not trusted. The site is indexed once by the full sync (`index_reference_passages`, skipping what is indexed, the same code the command line runs), which does list the Reference table and the index; the place is then set to the newest change read **before** the sync began, and only if the sync finished. That one run is proportional to the site. After it every run is incremental.
* **What catches a missed change, without a recurring walk.** A Reference is read again whenever it is touched (any edit bumps `updatedAt`). A change that never bumps `updatedAt` (an attachment replaced without a write to the Reference row, a row written by a client that sets `updatedAt` far in the past) is not seen by the daily pass; `papyrus knowledge-vector-index --action audit` (by hand; it lists the site once) reports References with no vector, and `--action sync` repairs them. Nothing schedules either.
* **Link explanations** (an editor's note on a link) are not part of the daily pass. They have no changed-since index (the `SemanticRelation` table has no `updatedAt` index), so keeping them current would mean listing every link and every Reference at each run. They are indexed by the command-line sync until Ryan chooses between indexing a note when it is saved and adding an `updatedAt` index on links.
* **The router's pass indexes References and concept cards only** (`include_notes=False`, `include_link_explanations=False`); the full command-line sync still indexes notes and explanations.
* **Bounds.** Only the run's time and its cost meter, checked between pages and between References. Embedding cost (`text-embedding-3-small`, USD 0.02 per million tokens, the characters embedded at four per token) is added to the publication's `costUsd` and counts against `MAXIMUM_COST_USD` before the drafting starts. The embeddings need the OpenAI key (`openai_not_configured` skips the pass and says so).
* **Log line.** Each publication's `monitorStories` line carries `indexed`, `conceptCardsWritten`, `suggestionsQueued`, `changedReferences`, `changedConcepts`, `changeReads` (AppSync requests made to find the work), `bootstrapped` on a first run, `suggestionsNotQueued` and `suggestionsQueueError` if the queue refused a message, and `vectorTimings`.
* **IAM.** `RouterIdeaPolicy` gains `Query/listReferencesByVersionStateAndUpdatedAt` and `Query/listSemanticNodesByVersionStateAndUpdatedAt`. It keeps `s3vectors:GetVectors`, `QueryVectors`, `PutVectors` on the sites' indexes, and `s3vectors:ListVectors`, `Query/listReferences` and `Query/listSemanticNodes`, which only the one-time first run uses (they can be dropped when every site has run once and new sites are indexed by hand). Nothing else became unused: `Query/listSemanticRelationsByNewsroomFeedAndCreatedAt` (the calibration read) and `listMessageThreads` (drafting) are still read, the first now by the suggestion worker. `RouterRole` gains only `sqs:SendMessage` on the suggestion queue.
* **A publication's time is shared so the drafting always gets its part.** The router splits the publication's share of the Lambda time (`Router.monitor_stories`): the vector pass the first quarter (`vector_out_of_time`), reading the signals for the idea packs the next sixth (`signal_out_of_time`), and drafting the rest, more than half. What the vector pass does not finish is saved and continues after the drafting if time is left. Before this, a site with a large backlog (Machines on Machines: 1,408 accepted and 6,484 pending References) spent its first run in the index walk and its second reading pending relations for the packs, reported `candidates: 0` and drafted nothing. The log line carries `timings` (`vectorsSeconds`, `signalsSeconds`, `draftingSeconds`, `collectSeconds`, `afterCollectSeconds`, `vectorsAfterSeconds`) so the next run says where the time went.
* **A backend with tenant-stamped editorial records.** A router publication may carry `"tenantId": "<tenant>"` (validated; a mistyped one refuses the configuration). The router then builds that publication's client as the tenant (`make_appsync_client(endpoint, tenant_id)`), so reads and writes of Item and NewsroomSection rows are the tenant's and the editorial check, which refuses a record whose tenant differs from the client's, accepts the stamped sections. Only the tenant models are filtered (Item, PublishedItem, MediaAsset, PublishedMediaAsset, NewsroomSection); Reference, Message, SemanticNode and the rest are never scoped, so reads of References are unchanged. Machines on Machines was copied from the Papyrus site with `--stamp-tenant`: its 23 sections and 20 stories carry `p-apyr-us`, its two doctrine Items carry none, and Reference, Assignment and the policies carry none. A publication with no `tenantId` is unchanged.
* **One filing error does not stop the run.** A filing that fails is recorded (`fileErrors` in the log line, `fileError` the last message) and the run goes on with the next candidate. The same error twice in a row with nothing filed between is systemic: the run stops (`stoppedBy: file_error`) and `fileErrorReason` says why.
* **Candidates are read people first.** `collect_monitored_items` reads the accepted References in the order of attention: a human vote, stars, a conversation, a human concept tag first, then the rest newest first (it was by id). If the time stops the reading, the References an editor worked on are the candidates. The pending backlog is no longer listed before drafting only to count it: `notAccepted` is counted last, if time remains.
* **Only real concepts.** Concept cards and suggested concepts leave out the nodes that are not subjects, using what the public wiki already uses (commit 82670d24, `knowledge_wiki/kinds.py`): authors (`personAuthor`), comment concepts, quality ratings, relevance decisions, coverage questions, editorial forms, plus the bulk-extracted `entity` and `identifier` kinds (`papyrus_knowledge_query/concept_kinds.py`, kept equal to the wiki's list by a test; it has no dependencies so the router zip carries it). The check is by kind and, for a node with no kind, by the key's prefix. It applies in the sync (no new cards) and in `suggest_for` (so the router and the on-demand `suggestReferenceLinks` share it), because cards already in the index cannot be deleted by the router. An allowlist of kinds can be passed instead. The score has no floor: the cut keeps every neighbour at or above a threshold learned from the site's own decided suggestions (labelled "likely" or "possible") and always at least the knee's count, so the best match is offered however low its score; nothing is configured, and no fixed cutoff was added. `papyrus references retire-junk-suggestions [--execute]` lists (default) or marks rejected (by `auto:cleanup`, reason `not_a_concept`; nothing deleted) the open `auto:vector` suggestions to such nodes.
* **Config.** `monitorStories.vectorIndexArn` and `monitorStories.storageBucketName` are copied from each site's `amplify_outputs.json` (`custom.knowledgeQuery.s3VectorIndexArn`, `storage.bucket_name`) by `seed_router_config.py --file router.json --amplify-outputs <publicationId>=<path>` (repeat per site), never typed. `monitorStories.suggestions.enabled` (default true) turns suggestions off while the index is still kept current. Without `vectorIndexArn` the sync and the suggestions are skipped, packs and single items run as before, and the log line says why.
* **Change set.** The template has fourteen new parameters (sixteen with Machines on Machines' `MachinesOnMachinesVectorIndexArn` and `MachinesOnMachinesStorageBucketName`), `AnthUsVectorIndexArn`, `PapyrusVectorIndexArn`, `ThreatIntelVectorIndexArn`, `DataParadeVectorIndexArn`, `PilobolusVectorIndexArn`, `ShippedVectorIndexArn`, `DistinctiveVectorIndexArn` (each the site's `custom.knowledgeQuery.s3VectorIndexArn`) and `AnthUsStorageBucketName`, `PapyrusStorageBucketName`, `ThreatIntelStorageBucketName`, `DataParadeStorageBucketName`, `PilobolusStorageBucketName`, `ShippedStorageBucketName`, `DistinctiveStorageBucketName` (each the site's `storage.bucket_name`). A parameter left at its default names no index or bucket, so it grants nothing. Fill them from the sites' `amplify_outputs.json`, keep every other parameter at `UsePreviousValue` (never omit `EditorUserPoolArns`), read the change set (it should show `RouterIdeaPolicy` modified, the router code update and the new parameters, nothing else) and execute it. The router config rows are data and need no deploy.
* **Package.** The router zip now also holds `src/papyrus_knowledge_query/` (standard library only; its command line and Lambda handler are left out) and the three modules it imports from `papyrus_content` (`knowledge_snapshot/keys`, `knowledge_wiki/pages`, `corpus_storage_paths`), a few hundred kilobytes of source. The function's `boto3` must have the `s3vectors` client (boto3 added it in 1.39); the pass checks this before it starts and skips with `the runtime's boto3 has no usable s3vectors client` when the managed Python 3.13 runtime is older. Check the runtime's version with `aws lambda get-runtime-management-config` / a test invoke before relying on it; the zip does not vendor `boto3`.

### Suggest once

A Reference gets **one** related-items check, started by the event that makes it possible, and the check is never redone on a schedule (Ryan, 2026-11-04). The hourly `suggest-backlog` task, its two schedules (`SuggestBacklogSchedule`, `DistinctiveSuggestBacklogSchedule`), the `suggest-backlog` fan-out, its lock, the plan that read every Reference to order the work, the watermark of suggestions and the owed/parked memory (`STATE#vectorOwed#...` rows, which nothing reads now and which may be deleted) are removed. Spec: `features_backend/suggest-once.feature`; code: `src/papyrus_content/reference_suggest_once.py`.

* **The trigger.** A check needs the Reference's own `reference_summary` vector, so it starts when that vector is **stored**: new, or stored again because the text it was made from changed (the vector's `contentHash`; for a vector made from extracted text, which has no hash, the hash of the text embedded). `vector_index` calls `VectorIndexOptions.on_summary_written` for each stored batch; the vector pass puts one message `{monitorId, publicationId, referenceLineageId, contentHash}` on the suggestion queue for each summary vector. Creating a Reference does not start it (there is nothing to compare yet); a vote, a star, a retitle, an accept and a reject do not (they store no summary vector). A Reference's check happens within minutes of the daily pass that indexes it, so a Reference created after 07:30 gets its suggestions the next morning. The pass could run more often now that it costs two requests when nothing changed; that is a follow-up, not done here.
* **The check.** `SuggestWorkerFunction` (its own function and role, because the router has reserved concurrency 1 and a consumer would be throttled for the whole daily run, burning its receive count) takes messages off `SuggestQueue` (batches of 10, at most 2 at once) and calls `reference_suggestions.suggest_for` for that Reference: the `GetVectors` of its vector, two `QueryVectors`, four relation-state reads and one write per kept neighbour. The site's calibration (`load_calibration`, which reads the link feed) is read only when a check is about to run and kept six hours per warm container.
* **Where "checked" is recorded.** One row per Reference in the router's own table: `pk = MONITOR#<id>`, `sk = STATE#suggested#<publicationId>#<lineageId>`, holding `contentHash`, `checkedAt` and `written`. A message whose hash equals the record's is dropped before any search. No index on the Reference table, and no GSI, is needed (the Reference table's pending GSI is not touched).
* **Retries and visibility.** A failing check raises; the queue redelivers the message (partial batch response, so only failures return) up to `maxReceiveCount` 3, then it waits in `SuggestDeadLetterQueue` for 14 days, and `SuggestDeadLetterAlarm` (`ApproximateNumberOfMessagesVisible >= 1`) notifies the alarm topic. Every outcome is a log line, `{"suggestOnce": "checked" | "already" | "failed" | "noVector", ...}`. A message the queue refuses at send time shows as `suggestionsNotQueued` and `suggestionsQueueError` in the daily line.
* **Status changes.** Accepting or rejecting a **suggestion** (a `SemanticRelation` in state `suggested`) only changes that relation; no vector search runs. Accepting or rejecting a **Reference** does not run one either: its stored vector status is rewritten by the next pass if needed, and the suggestions already written for it stay as relation rows. A pending Reference was checked against accepted neighbours when its vector was first stored; it is not checked again when accepted. The card suggestion readers (`card-suggestions.tsx`, `related-section.tsx`) read the stored relation rows only.
* **References that never got a check** (for example vectors stored before this change, or a failure that outlived the retries): by hand, once, `{"task": "suggest-unchecked", "monitorId": "hn", "publicationId": "<id>"}` to the router. Without `"write": true` it only reports. It **scans**: it lists the publication's accepted and pending References (the status index, 100 a page) and the check records (one prefix query), and lists those with no record. With `"write": true` it queues one audit message each; a Reference with no summary vector yet is answered `noVector`, left unrecorded, and found again by a later run. Nothing schedules it.
* **Infrastructure.** `SuggestQueue` (visibility 1,800 s), `SuggestDeadLetterQueue`, `SuggestEventSourceMapping` (`ReportBatchItemFailures`, `MaximumConcurrency` 2), `SuggestWorkerFunction` / `SuggestWorkerRole` / `SuggestWorkerLogGroup`, `SuggestDeadLetterAlarm`, and `SUGGEST_QUEUE_URL` on the router. The worker may read the router's table (`GetItem`, `PutItem`), consume the queue, call the nine GraphQL fields `suggest_for` and `link_references` use, and `GetVectors` / `QueryVectors` on the sites' indexes; it cannot write or delete vectors. **Deploy note:** the two hand-disabled schedules in AWS are deleted by the next stack update; the stack update also creates the queue and function, so it needs a deploy approval.

### Research assignments

An editor's research assignment on a Story ([assigning research](story-reporting.md#assigning-research-in-the-newsroom)) is run by the router's `research-assignments` task, with nobody at a terminal (`src/papyrus_content/research_assignments_worker.py`; spec `features_backend/monitoring-research-assignments.feature`).

* **Turned on per publication.** The publication's router entry has `researchAssignments: {"enabled": true}`; absent means off, because the backend must grant the worker the fields below. The router config validator refuses any other key.
* **Its own function and role.** `ResearchWorkerFunction` (`papyrus-monitoring-research-worker`) runs the router's code zip under `ResearchWorkerRole`. `RouterRole` already has 20 managed policies, the most a role may have, so its grants cannot grow; the worker's role holds the table, its logs, the dead-letter queue, `lambda:InvokeFunction` on itself for the fan-out, its own copies of the search and model key policies (`ResearchWorkerOpenAiSearchKeyPolicy`, `ResearchWorkerPerplexitySearchKeyPolicy`, `ResearchWorkerGeminiSearchKeyPolicy`, `ResearchWorkerTavilyKeyPolicy`, `ResearchWorkerBedrockWebSearchPolicy`, each with the condition and the one parameter of the router's policy; the router's own policies are unchanged, because each key policy names exactly one role) and one `appsync:GraphQL` statement of exactly the fields a run asks for, on any publication API. Timeout 900 seconds: real runs took about five minutes for search and synthesis, and the fact check adds about 55 model calls. The task's lock lease and a claim's lease are 960 seconds (`TASK_LEASE_SECONDS`, `CLAIM_LEASE_SECONDS`), longer than the Lambda, so one publication's runs never overlap.
* **Schedule.** `papyrus-monitoring-hn-research-assignments` (`ResearchAssignmentsSchedule`) every 5 minutes with `{"task": "research-assignments", "monitorId": "hn"}`. It names no publication, so the worker invokes itself once per publication that turned the task on (the lock `LOCK#research-assignments#<publicationId>` per publication; the fan-out takes none). Distinctive Mark's monitor (`web-distinctive`) needs its own schedule with `"monitorId": "web-distinctive"` when it turns the task on. No retry.
* **What a run does.** For the publication, the research assignments of type `research.multi` that name a Story, oldest first. A claimed assignment whose lease (11 minutes) has ended is failed with the reason that its time ran out, so nothing hangs. Each open one with the `reporter` profile is marked `claimed` (assignee `papyrus-research-worker`, with an `AssignmentEvent`), `research_multi` runs on it with the publication's corpus key, and it is marked `completed` or `failed` with the reason in its event. The run sets `PAPYRUS_GRAPHQL_ENDPOINT` to the publication's endpoint while it works, because the context pack asks for it and the Lambda has no `amplify_outputs.json`. A failed assignment is never retried by the task, because a run spends search and model calls; an editor can reopen it. A run is not started with less than 420 seconds left (`START_RESERVE_SECONDS`), and the fact check's judge stops asking with less than 240 left (`JUDGE_RESERVE_SECONDS`): claims not yet judged end `unchecked` with the reason that the run ran short of time, the packet is still written, and the rest wait open for the next run. No fixed cap and no budget gate: a person asked for each run, and the existing spend alarm applies.
* **An idle tick.** The fan-out invocation reads nothing. Each publication's invocation does one DynamoDB `GetItem` (router config), a conditional `PutItem` and a `DeleteItem` for its lock, and one AppSync query, `listAssignmentsByTypeStatusAndCreatedAt`; it writes no receipt when nothing ran. At every 5 minutes that is 288 ticks a day per publication: 288 AppSync list queries and 288 config reads, plus 576 lock writes, and 288 short Lambda invocations of the fan-out.
* **Needs.** The search and model keys (the `PAPYRUS_*_KEY_PARAMETER` variables the function carries; SSM reads need no extra statement beyond the key policies), no S3 permission (attachments go through the presigned URL AppSync returns), and no `corpora/` directory: the intake takes the backend's own canonical corpus.
* **Log line.** One `{"researchAssignments": ...}` line per publication: `status`, `ran`, `failed`, `expired`, `leftOpen`, `stoppedBy`.
* **Grants.** `test_research_assignments_worker.py` runs one assignment on the real GraphQL client with its transport replaced and checks that every field it asked for is granted to `ResearchWorkerRole`, and that `RouterRole` gained no policy. The template change is a hand-run change set that needs Ryan's yes; nothing is deployed from the pull request.

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
existing URL re-points the shared source attachment. There are no deletes, and the only Reference updates are the automatic acceptance in `RouterAutoAcceptPolicy` and, when a delivery finds a Reference no monitor delivered yet, the three discovery fields (`listReferencesByCurationStatusKeyAndUpdatedAt`, `updateReference` per API), the daily [monitor stories](#monitor-stories-daily) read and file through `RouterMonitorStoriesPolicy`, `RouterMonitorStoriesSharedSitesPolicy` and `RouterMonitorStoriesDistinctivePolicy` (eleven fields on each of seven APIs, listed there), no wildcard resources, no admin. The provenance upload uses the
presigned URL AppSync returns, so the role needs no S3 permission.

Limits: Python 3.13 arm64, 512 MB, 600 s timeout, retry 0 on async invocation, dead-letter queue,
logs kept 30 days, reserved concurrency parameter `RouterReservedConcurrency` (0 where the
account quota cannot reserve any; the table lease serializes runs anyway). Alarms:
`papyrus-monitoring-router-errors` and `papyrus-monitoring-router-dead-letters`.

## Packaging

`python3 infra/monitoring/build.py --router [--upload BUCKET]` builds a separate deterministic zip
(`papyrus-monitoring/router-<sha256>.zip`, about 4.9 MB with item enrichment, the monitor-stories drafting and the editorial gate's wheels): the in-package import closure of the
router (relative imports are resolved against the importing module's own package, `from ..x` included, and a subpackage module brings the `__init__` of each package above it), the two YAML data files the shared Reference factories read, and pure-Python PyYAML (the
runtime has boto3/botocore only). `PAPYRUS_ROOT=/var/task` lets the factories find `corpora/`. A test
imports the built zip with an isolated interpreter, including the drafting modules and the gate.

The editorial gate imports Humanus, and its judgment lane imports the Jev client (`typesafe-sdk`), so the router zip also holds their dependency closure
(pydantic and pydantic-core, rpds-py, httpx2, anyio and the rest) as binary wheels for the function (manylinux aarch64, CPython 3.13), at the versions
`poetry.lock` pins: `build.py --router` computes the closure from the lock, downloads each wheel with `pip download --only-binary`, refuses any whose
sha256 is not in the lock, and unpacks them in sorted order, so the same lock gives the same `CodeKey`. `--router --host` unpacks this machine's installed
copies instead, for tests (compiled modules load from the unpacked directory the Lambda uses, not from inside a zip). The collector zip is the import closure of `monitoring_cloud`, so `monitoring_feed` and `monitoring_hf_papers` are in it, and in the router zip, without being listed (a test checks both); the wheels change nothing in the collector zip, and the email-receiver zip grows with the same closure fix.

## Decision-ready events

When a `/machine/decisions` job finishes, the Cyclotron lab can ring a doorbell so the router collects
the answer in seconds instead of waiting for the 2-minute collector. The event is **only a doorbell**:
it never carries a decision and nothing in it is delivered. The router still fetches each answer with
its signed GET.

- **Bus**: `papyrus-cyclotron-decisions` (output `CyclotronDecisionsBusArn`). Its resource policy allows
  `events:PutEvents` only for the role in parameter `CyclotronWorkerRoleArn` (default
  `arn:aws:iam::682849160744:role/cyclotron-console-worker-runtime`) and only when `events:source` is
  `cyclotron.lab`.
- **Event**: source `cyclotron.lab`, detail-type `Decision Ready`, detail `{contractVersion:
  "cyclotron-decision/v1", accountId, runId, jobId, requestId, itemId, bindings, status:
  "complete"|"failed"}`. A job posted under `cyclotron-publication/v1` rings in that contract, with
  `publications` for `bindings`; the router accepts both. Delivery is at least once; resends are harmless.
- **Rule** `papyrus-monitoring-decision-ready` (state follows `ScheduleState`) invokes the router
  Lambda with the event unchanged, with a small retry policy and the router dead-letter queue.
- **Handler**: a strictly validated event is accepted; anything malformed is dropped with a log line
  (it never raises, so EventBridge never retries it). Monitors are not derived from `itemId`. The
  handler looks at every monitor that can hold a router config (`DOORBELL_MONITORS`: `hn`,
  `huggingface`, `ttab`; add a new monitor there), skips any whose `CONFIG#router` `cyclotron.accountId`
  or `cyclotron.runId` differs from the event's (counted in the log), and runs `collect` for the rest.
  Each collect takes that monitor's own router lock; a locked monitor is skipped and its job is picked up
  by the 2-minute collector or the next route run. A collect that finds nothing new changes nothing, so a
  duplicate event is harmless.
- Scheduled events (`{"monitorId", "task"}`) are unchanged.

## Decisions stopped (alarm)

On 2026-11-03 one stuck job blocked the shared Cyclotron run from 14:34 UTC. Decisions kept arriving until 16:28, then none came
back for about twelve hours while about 4,900 jobs queued, and Lambda error counts stayed at zero because every pass finished
cleanly. `papyrus-monitoring-decisions-stopped` watches for that.

- **Signal.** Every router pass logs one JSON summary with `counts.decided` (decisions recorded this pass) and `counts.awaiting`
  (jobs still running at the lab). Two metric filters turn them into `Papyrus/Monitoring` `RouterDecided` and `RouterAwaiting`.
  The alarm breaches in an hour when `RouterDecided` (Sum) is 0 and `RouterAwaiting` (Maximum) is above 0, and fires when that is
  true for 2 of 2 hours.
- **Quiet is not stuck.** An hour with nothing awaiting (nothing to decide) does not breach. A `hold` monitor or a `dry-run` one
  posts nothing, so it logs no awaiting. If the router stops logging altogether, both metrics are missing and missing data is
  not breaching: this alarm does not cover a router that never runs; `papyrus-monitoring-router-errors` and the schedule dead
  letters cover a crashing one.
- **The window.** The last four days of router logs (2026-10-31 to 2026-11-04) show decisions in almost every hour, and the
  hours with none were either quiet (nothing awaiting) or one isolated hour (2026-11-02 11:00 UTC, 10 jobs waiting, decisions
  back the next hour). Two hourly datapoints cannot be tripped by one hourly pass, a 15-minute slow patch or that one-hour gap,
  and in the replay of those four days the only firings were the real stoppage. The alarm covers all monitors together, so it
  catches a shared stoppage like the one above; one monitor stopping alone while the others decide is not caught.
- **Not counted.** A decision collected by a Decision Ready doorbell invocation (`hn`, `huggingface`, `ttab`) is not in a
  router summary line; the 2-minute `hn` collect and the hourly web passes are what the alarm counts.
- **Notification.** It emails through the topic `papyrus-monitoring-alarms`, like every alarm in this stack.
- **When it fires.** Do not retry or reconcile by hand. Check the Cyclotron run's status (the run bound in the monitor's router
  config, `cyclotron.accountId` and `cyclotron.runId`) and read the latest router receipts for `stoppedBy`, `labBackoffUntil` and
  `errors` (Administration, Monitoring, recent runs); the router log summaries show `counts.awaiting` growing. Then hand to the
  Cyclotron session with the hour decisions stopped and the awaiting count. The documented operator reconcile
  ([Operating the router](#operating-the-router)) changes shared state and needs Ryan's approval.

## Operating the router

- Seed: `seed_router_config.py --table TABLE --file router.json` (starts as `dry-run`).
- **Flip to live** (data change, no deploy): `seed_router_config.py --table TABLE --set mode=live`.
  Dry-run receipts are harmless; `dry-run-validated` items are processed as live items.
- **Monitor stories** need no setting either; to run them now, invoke the router with `{"task":"monitor-stories","monitorId":"hn"}`. The same task first keeps the vector index current and writes suggestions ([vector index and suggestions](#vector-index-and-suggestions)). Turn a publication off with `seed_router_config.py` setting its `monitorStories` to `{"enabled": false}`; stop the schedule with `ScheduleState=DISABLED`. Shape it with `singleItem` and `contextPacks` in the same block ([monitor stories](#monitor-stories-daily)).
- **Feedback** needs no setting: editors' Accept/Reject is always sent for Cyclotron-decided monitors in live mode.
  Back to dry-run with `mode=dry-run` (feedback stops with it); stop entirely with `enabled=false`
  or `ScheduleState=DISABLED`.
- Reconcile an `uncertain` item: check Cyclotron for its `requestId` (in `ROUTE#...`.`jobs`, or `combinedJob` for a combined request), then
  delete that `jobs` entry or `combinedJob` or set the discovery back to `routing=collected` with
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
(live or dry run) and whether editor feedback is sent and observed decision counts.

The page covers only the monitors whose `CONFIG#router` `publications` include the viewing site's
publication (found by its AppSync endpoint). Other monitors are named in a collapsed "Not routed to
this site" note, with no items, runs or counts; an admin's `scope: all` combines every monitor. The
function cannot Scan, so the monitors it looks at are `MONITOR_IDS` in `monitoring_view.py`
(`hn`, `ttab`, `huggingface`, `p-apyr-us-email`), overridable with `PAPYRUS_MONITORING_MONITOR_IDS` (comma separated);
add a new monitor there. Reading them needs no new IAM: the same `GetItem` and `Query` on the one table.

## Access design

`monitoringOverview(scope)` is a GraphQL query in every site's own AppSync API, admitted to the
`editor` and `admin` groups only. It resolves to the `papyrus-monitoring-view` Lambda
(`amplify/functions/monitoring-view/`, logic in `src/papyrus_content/monitoring_view.py`).

- The function's role holds `dynamodb:GetItem` and `dynamodb:Query` on tables named
  `papyrus-monitoring-MonitoringTable-*` and their `routing` index (no Scan or other table). Its only
  table write is a `PutItem` for an explicitly resolved Beehiiv article destination, limited by
  `dynamodb:LeadingKeys` to `MONITOR#hn`; the handler verifies the editor, routed publication,
  receipt and candidate before storing the destination with the receipt's expiry.
  and `ssm:GetParameter` on `/papyrus/monitoring/table-name`.
- That parameter is written by the monitoring stack (`TableNameParameter`), so a site backend needs no
  deploy-time link to this stack. A site in an account without the parameter shows "not set up".
- The browser uses the signed-in editor session. It never sees a table name or role ARN; article
  resolution results are retained privately so Reference intake can verify the exact receipt candidate.
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
- Old `limit`, `maxItems` and `pagesPerQuery` fields in a collector `CONFIG` are ignored the same way (the collector logs one `ignored_retired_config` line).
- Old `ceilings` and `maxItemsPerRun` fields in `CONFIG#router` are ignored (the router logs one `ignored_retired_config` line naming them) and are not returned to Monitoring. They can be deleted from the stored config; `infra/monitoring/seed_router_config.py --set` drops them on its next write.
- Usage counts the decisions this router recorded (UTC days); incomplete bounded history reads are labeled as lower bounds without implying sort order. It is the router's view, not a Cyclotron model-usage meter.

### Paged lists: nothing scrolls out of reach

The page never truncates a list. `monitoringOverview` returns the newest page of each list (email submissions 20,
collector runs 15, router runs 10, collected items 60 per monitor) and, per list, an opaque `cursor` that is null once the list
ends. Those numbers are page sizes, not totals. The `monitoringPage(list, cursor, filter, scope)` query returns the next page of
one list (`runs`, `routerRuns`, `items` or `emailSubmissions`) and the cursor after it; the page's "Load more" button calls it.

- The cursor is the DynamoDB key of the last row shown, per monitor (the view reads one extra row, so there is no empty last page).
  It is validated on the way back: it must be this monitor's own partition and the list's own key range, or the request is
  `bad_request`. The same editor/admin gate and scope rules as the overview apply, and a monitor not routed to the site contributes nothing.
- `filter: "held"` (email submissions only) restarts the list at the newest message that is still held for review (including one
  whose decision could not be applied) and reads back as far as it takes to fill a page, so an old held message is always
  findable without paging through everything. It pages the same way.
- The 60 second refresh re-reads only the newest page; the rows an editor loaded stay, and a row that moved between pages is shown once.
- Queue items read their routing by key (`ROUTE#<sourceId>#<revision>`), not from a fixed window of recent routes.
- Usage still reads a bounded history (`MAX_DECISION_PAGES`) and labels the count as a lower bound when it stops early.

### Open one email receipt

Editors can open `/newsroom/administration/monitoring?receipt=EMAIL%23<receipt-hash>`
to inspect one known email. Encode the receipt with `encodeURIComponent` when
constructing the link: an unescaped `#` becomes a URL fragment. This mode calls
only the authenticated single-receipt query and never mounts or refreshes the
monitoring overview. Empty, unavailable, and refused receipts do not fall back
to listing submissions. Existing editor/admin authorization, redirect consent,
and pending Reference intake apply unchanged.

This UI change requires an engine release and a site pin update before the link
is supported on a deployed site. It does not establish live email acceptance.


### Held email submissions: Accept or Reject

Mail that fails sender authentication, and the receipts the earlier authentication gate refused, are
held privately until an editor or admin presses Accept (release) or Reject (discard) on the receipt
page. The decision is recorded as an `EMAILACTION#` row in the email partition and applied by the
receiver on its one-minute schedule; nothing is routed, resolved or imported while a message is
held. See [email reference intake](email-reference-intake.md#quarantine-accept-or-reject).

### Predictions for editor-selected newsletter References

Importing a receipt's selected candidates now registers normal pending References and then
queues each successful Reference through `monitoringQueueEmailReference`. It requires the
site's existing Cognito editor/admin identity, verifies the exact receipt and candidate
(including a saved article redirect resolution), and writes a stable URL/corpus job identity.
Retries reuse the Reference and prediction job; no human curation or vote is created.

The existing router handles `task: "email-references"` using a separate routing partition.
It checks the exact imported Reference before calling Cyclotron, attaches both positive and
negative decisions, and starts no publishing procedures or feedback sweep. The optional
`EmailReferenceMonitorId` stack parameter activates a five-minute schedule using the existing
router scheduler role and dead-letter queue, with no additional IAM grants. For bounded
acceptance, the same task accepts `sourceIds` (1–20 exact queued IDs) and reads those jobs only.
A failed handoff leaves the import visible with an explicit retry notice. Receipt pages link
to the exact References for normal prediction review.

### Predictions for References created without one

A pending Reference with no prediction is shown nowhere (the References page and the public pages need the Cyclotron's number; an unpredicted Reference is not a fifty percent
one). Only the router's delivery and the by-hand `decide-relevance` sweep used to record one, so a Reference an editor pasted, an import created, chat created, a research
packet registered or an inbound email registered stayed hidden. Spec: `features_backend/reference-prediction-on-create.feature`; code:
`src/papyrus_content/reference_prediction_queue.py` and `monitoring_router.record_reference_prediction`.

**Where the Cyclotron can be reached.** Only the router (it signs with its role; each site or group of sites has its own binding: Distinctive Mark's is its own, the rest share
one). The code that creates a Reference runs elsewhere, so it does not decide: it **asks the router, once, by the event that creates the Reference**, through the lane the
editor-selected email imports use. One row per Reference (`DISC#<sha256 of endpoint, corpus and Reference id>#000001`, `sourceType: "reference"`, `predictFor`) in the site's
`emailMonitorId` partition, on the existing sparse `routing` index under the new partition value `ROUTING#<monitor>#reference-predictions`. A conditional put makes it
idempotent. No table, no index, no schedule is new. The existing `email-references` task (`EmailReferenceSchedule`, every five minutes, on only when the stack's
`EmailReferenceMonitorId` is set) now drains both lanes. Nothing scans a corpus to find References that need a prediction.

| Route | Runs in | Status |
| --- | --- | --- |
| Monitor delivery (`deliver_reference`) | Router Lambda | Already decides |
| Inbound email submission (router `email` discovery) | Router Lambda | Already decides |
| Editor-selected newsletter candidate (`monitoringQueueEmailReference`) | Browser, then monitoring-view Lambda | Already queues, same lane family |
| Console paste, and the CLI's signed-in `references create-from-catalog` (`intakePendingReferences`) | `content-actions` Lambda | **Changed**: queues straight into the table; the answer carries `prediction` |
| `papyrus references create-from-catalog` / `-split` (operator, `cursor:` imports) | Laptop with AWS credentials | **Changed**: writes the request rows itself, prints a `prediction` line |
| Chat `Reference.create` | Chat Lambda or console | **Changed**: asks as its lane allows; the result carries `prediction` |
| `papyrus assignments process-proposals` (research packets) | Research worker Lambda or laptop | **Changed** the same way |
| Inbound email direct citations (`email_submissions.py`) | Operator or chat | **Changed** the same way |
| GROBID citation stubs (`reference_url_text.py`) | Extraction run | **Left**: machine placeholders that the stub retirement archives; predicting them would spend the Cyclotron on records nobody asked about. `references queue-predictions` covers them if an editor wants them |
| Corpus move (`moveReferenceCorpus`, TypeScript) | `category-action` Lambda | **Left**: the new corpus has a different classifier and the Lambda cannot reach the table; follow-up |
| Accession replacement / next version | Extraction | Carries the existing prediction (`{**reference}` / `KEPT_FEED_FIELDS`) |

**What the router does.** `Router.selected_references` takes each request whose retry time has come. If the Reference is gone, archived, not current, or in another corpus
or address, the request is **refused** (final, counted, logged as `{"referencePrediction": "refused"}`). If the row has `predictionDecidedAt` it is dropped without a call. If it
has a current `relevance_decision_is` but no number on the row, the number is **copied from that decision** (no Cyclotron call). Otherwise it decides as it does for a monitor's
item (one `decide` per binding, polling, the existing backoff and park) on the Reference's **title and address only**: no page fetch and no summary model run, so no model
other than the Cyclotron is involved. The Cyclotron item says `source: "email"`, the lab's one value for a source a person chose. It then records with the builders
`deliver_reference` uses: `lab_decision_records` (the relation) and `record_original_prediction` (`predictedAcceptProbability`, `predictionDecidedAt`, `predictionSortKey`, feed
keys). It creates nothing, changes no vote or status, attaches nothing, starts no procedure and **sends nothing back**. Votes on these References later reach the Cyclotron
through the existing feedback pass (the request records a `DELIV#` row), exactly as for a delivered one.

**Failure.** The Reference exists whatever happens and stays hidden until it has a number. A caller that cannot queue says so in its answer (`prediction.ok: false` and the
reason; the CLI prints `NOT-REQUESTED` and the command `papyrus references queue-predictions`). A request the router cannot finish yet (the binding's criteria pending, the lab
busy, AppSync down) keeps its place and is retried with the existing backoff (up to six hours) with no limit on tries; a recording that fails half way finishes the rest next
time (the relation is skipped when its decision id is current). A monitor switched to `direct`, `hold` or `dry-run` leaves its requests waiting (`predictionsWaiting`).
Counts `predicted`, `predictionSkipped`, `predictionFailed`, `predictionsWaiting` are in the router's receipt.

**A bulk import.** The request is one conditional write per Reference and no decision, so a catalog of thousands costs the importer thousands of small writes (the CLI sends
them in groups of 100 per AppSync call when signed in; the 100 is a transport size, not a limit) and the router decides them in its own time, as many as fit in each run, the
rest staying queued for the next. Nothing is decided inside the importing request.

**Deploy.** The router code (`RouterCodeKey`) must ship before any site queues, or requests wait unread (harmless). The site backends need a deploy for the new
`content-actions` grant (`dynamodb:PutItem` on the table, only the site's own `MONITOR#<emailMonitorId>` partition, `wireEmailReferenceIntake`) and the `monitoringQueueReferencePredictions`
field (`monitoring-view/schema.ts`). Until a site deploys, its console paste still creates the Reference and the answer carries `prediction.ok: false`. The router's AppSync role
needs nothing new: it already reads and writes the fields delivery uses on each site.

**The References that predate this.** By hand, once per site: `papyrus references queue-predictions --site KEY --dry-run`, then without `--dry-run`. It lists the corpus's
pending References once (a scan, said so) and queues those with no prediction. It is idempotent and nothing schedules it. (`papyrus references decide-relevance` is the older
embedded sweep with its own store and model; it is not the router's Cyclotron. See its section before using it on a site that has no `relevanceCyclotron` block.)

A maintenance deployment must preserve newer shared-router behavior: apply only this change's
router/intake diff to the verified currently deployed router artifact, test that artifact,
and update `RouterCodeKey` through a reviewed changeset. Do not replace the shared router with
an older site maintenance baseline. Preserve all existing stack parameters and resources.

### Web-search provider stack parameters (opt-in)

`papyrus-monitoring` takes four optional parameters that give the collector and the router the provider chain and key parameters. With
their defaults (empty, and `off`) the stack is unchanged: Tavily alone, from `TavilyKeyParameter`.

| Parameter | Default | Effect |
| --- | --- | --- |
| `WebSearchProviders` | empty | Sets `WEB_SEARCH_PROVIDERS` (for example `openai,tavily`). |
| `OpenAiSearchKeyParameter` | empty | Sets `PAPYRUS_OPENAI_KEY_PARAMETER`; standard name `/papyrus/search/openai-api-key`. |
| `PerplexityKeyParameter` | empty | Sets `PAPYRUS_PERPLEXITY_KEY_PARAMETER`; standard name `/papyrus/search/perplexity-api-key`. |
| `GeminiKeyParameter` | empty | Sets `PAPYRUS_GEMINI_KEY_PARAMETER`; standard name `/papyrus/search/gemini-api-key`. |
| `BedrockSearchModel` | empty | Sets `BEDROCK_SEARCH_MODEL`, the Bedrock model id (an `openai.` Luna model); there is no default in code, and with it empty `bedrock` is skipped as unavailable. |
| `BedrockWebSearch` | `off` | `on` attaches `AmazonBedrockMantleInferenceAccess` and `bedrock:CallWithBearerToken`, `bedrock-websearch:InvokeSearch`, `bedrock-websearch:InvokeFetch` to the roles. |

`Collector<Provider>SearchKeyPolicy` and `Router<Provider>SearchKeyPolicy` (each only when its key parameter is set) let each role read exactly the named
parameter and decrypt through SSM. Create each key as a SecureString under the standard name (`aws ssm put-parameter --type SecureString`)
outside the repository, then update the stack. The OpenAI search model is `OPENAI_SEARCH_MODEL` (default: the repo's `DEFAULT_LLM_MODEL`),
the Gemini model `GEMINI_SEARCH_MODEL`.
