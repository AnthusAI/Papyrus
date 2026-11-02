# Search monitors: design

Status: design, approved by Ryan 2026-10-27. The first backend slice is `feat/web-search-monitors` (PR #814 and its follow-up);
the optimizer and the UI are separate PRs. Operating details of what already exists are in [monitoring-cloud.md](monitoring-cloud.md#web-search-monitors-web-search).

## Principles

- **No caps anywhere.** Not per page, per query, per run, per day, nor per list. Work is bounded only by real constraints: the
  Lambda's time (an unfinished pass stores resume cursors and the next pass continues), the search provider's own limits and its
  `Retry-After`, and a storage row's physical size (so lists become rows of their own).
- **Config is data.** Monitors, queries and their history are records in the monitoring table, not code or templates.
- **Nothing changes silently.** Every change to a query, whether an editor's edit or the optimizer's proposal, is recorded with
  who and when; proposals are Accept/Reject cards for an editor.
- **Hold is routing, not a state.** A monitor routes to a Cyclotron target or holds. Holding still collects and enriches.

## Monitor

`web-<publicationId>` (`MONITOR#web-<id>` / `CONFIG`): `sourceType: web-search`, `publicationId`, `intervalSeconds` (the schedule),
`topic`, `enabled`, `candidateGroup`, and routing: `CONFIG#router` names a Cyclotron target (run, binding, invoker role) or
`decisions: "hold"` / `holdDecisions: true`. One monitor per publication. Queries are no longer a list inside the config; they are records.

**Routing is shared across the six shared-Cyclotron publications.** A candidate a web monitor finds is decided for **all six**
shared publications in one combined `POST /machine/decisions`, exactly as Hacker News items are, so a `web-anth-us` find can land
in Shipped, Threat Intelligence and the others. Their six router configs therefore list all six publications (the `hn` router's
entries and cyclotron block) and share `candidateGroup: shared`, so a story found by two of these monitors is one candidate and
is decided once. Only `web-distinctive` routes on its own: it has its own Cyclotron (not bootstrapped yet), keeps
`decisions: "hold"`, and stays hold-only; its candidates are its own group. Every router config sets `holdDecisions` until released.

## Query records

`MONITOR#web-<id>` / `QUERY#<queryId>`:

| Field | Meaning |
| --- | --- |
| `id` | stable id (ULID-like), never reused |
| `text` | the search text |
| `rationale` | why the query exists (the drafter's reason, or the editor's) |
| `origin` | `drafted` (model) or `editor` |
| `scope`, `sectionId`, `sectionTitle`, `flags` | drafted queries only: `scope` is `section` or `site`; a section query holds the `NewsroomSection` id (and its title when drafted, for reading), the site query has none. `flags` says when a section was drafted from little (`no-section-mission`, `title-only`) |
| `createdBy`, `createdAt` | who made it (model name or editor subject) |
| `approvedBy`, `approvedAt` | who accepted it; a query is searched only once approved. The first queries carry `approvedBy: "Ryan (review delegated to Claude, 2026-10-28)"`; editors can retire or edit any query later, and every change stays an Accept/Reject card |
| `status` | `active`, `paused` or `retired`; only `active` is searched; `retired` keeps its history |
| `highWater` | the last date the query was searched through (its own high-water mark; replaces the monitor-wide mark) |
| `history[]` | append-only edit history: `{at, by, change, before, after, reason}` (a row of its own per entry once long) |

## Queries per section

A monitor searches **one query per enabled `NewsroomSection` plus one for the whole site**, so the number of queries is the number of
enabled sections plus one (Ryan, 2026-11-02; it replaced eight to fifteen topic queries drafted from the whole site). There is no
minimum or maximum. A section's query is drafted by gpt-6-luna from that section's own `editorialMission`, `editorialPolicy`,
`assignmentGuidance` and `killCriteria`; the site's from the publication's mission and policy. A section with no mission is still
drafted (from its policy and guidance, or from its title alone) and flagged, so the count stays exact and an editor can check it.
A site with no mission and no policy cannot get a site query: the command refuses it.

`papyrus monitors web-queries --publication <id> | --all` is a dry run: per site it prints the old queries to retire and the new ones
to add, the queries kept, and the paid searches a day that result (one per active query). `--execute` writes: retired queries get
`status: retired` and a history entry and keep every field including `highWater` (nothing is deleted); new queries are written
without an approver, so they are **not searched until approved**: pass `--approved-by NAME` with `--execute` to approve the new
ones (and any kept drafted ones still awaiting approval) in the same step. Without an approver a site is not searched at all until
someone approves its queries. Run it outside the collector's window: the collector writes a query record back at the end of a pass.

The queries are drafted once; no schedule regenerates them. A later run keeps every drafted query whose scope is still needed and
asks the model only about what is missing, so a section added since gets its query and nothing else changes. A renamed section
keeps its query (the record holds the section id). A drafted query whose section is no longer enabled is retired. Editor-written
queries (`origin: editor`) are never touched unless `--retire-editor` is given. Machines on Machines stores its sections with
tenant-scoped ids; the `p-apyr-us` monitor (which finds for that backend) reads its sections for that tenant and records the bare
section id (`config/web-monitors.json`, `routerPublication`).

**First search of a new query.** A new query has no `highWater`, so its first pass is one request with Tavily's own default recency
(or the config's `startDate`, when one is set: leave it unset, or the first pass of every new query reads back to that day) at
`search_depth: basic` and 20 results, and the mark is then set to the start of that pass. Nothing is read in bulk, and a URL a
retired query already collected is skipped.

**Paid searches a day.** A pass makes one request per active approved query; a window whose answer fills a page (20 results) is split
by date, so a busy query on a two-day window can take up to three requests. The expected number is the number of queries; the real
number is the sum of `requests` and `credits` on that day's `QRUN#` records. Yield by section is a join: each `QRUN#` names its
`queryId`, and the `QUERY#` record names its `sectionId`.

A query's `highWater` moves to the start of a pass that read it to its end. A new query starts from its `startDate` or the
provider's default recency; a paused query resumes from its old `highWater`, so nothing between is lost.

## QueryRun

`MONITOR#web-<id>` / `QRUN#<startedAt>#<runId>#<queryId>`: `monitorId`, `queryId`, `runId`, `startedAt`, `finishedAt`, the
provider parameters used (`topic`, `start_date`, `end_date`, windows asked, `search_depth`), `resultsReturned`, `newCount`
(new candidates), `duplicateCount` (already known), `credits` (provider credits spent) and `stoppedBy` when unfinished.
A pass pages **every** window the provider can return: a full page splits the date range until no window fills a page (the
provider has no offset), so a QueryRun's `resultsReturned` is everything the provider had for the range.

## Candidate (shared across all monitors)

One record per canonical URL for the whole table, whatever found it (Hacker News, an email submission, a web search):
`CAND#<hash of canonical URL>` / `CAND`.

- `canonicalUrl`, `title`, `publishedAt`, `firstFoundAt`.
- `provenance[]`: `{monitorId, queryId?, runId, tavilyScore?, publishedDate?, foundAt}`. Finding a URL again appends provenance;
  it never creates a second candidate. Dedupe across HN, email and web is this key.
- **Enrichment is written once**, content-addressed: capture, summary and body live in write-once records
  (`CONTENT#<sha256>`, large text in S3) and the candidate holds only their hashes. Two monitors finding the same URL reuse them.
- `decisions` per publication: `{publicationId, jobId, via, label, confidence, criteriaFingerprint, decidedAt}`. **The decision
  key is item revision plus criteria fingerprint**: a candidate is decided once per pair, and decided again when its item revision
  changes (a later capture adds the body, an editor corrects the title) or the criteria change.
- `votes`: editor Accept/Reject per publication (the existing feedback records, linked by candidate).

Discoveries (`DISC#...`) remain the per-monitor routing records the router already works from; each points at its candidate.
Existing HN, email and Hugging Face rows are indexed into candidates by a backfill; until then the `URL#<hash>` / `MON#<id>`
records of the first slice answer "was this found already".

## QueryYield (derived)

For each query over time: found (candidates with this query in provenance) -> Cyclotron included (decision label positive for the
monitor's publication) -> editors accepted (vote Accept on the delivered Reference). Computed from provenance, decisions and
votes, by week; stored as derived rows (`QYIELD#<queryId>#<week>`) that can be rebuilt at any time. Rejected and unreviewed
counts are kept so a funnel never hides the bottom.

## Learning loop

Votes score the queries that found each item (every query in an item's provenance shares the credit or blame). A scheduled
optimizer (a Lambda, weekly by default, per monitor) reads the yield and the accepted/rejected References and **proposes**:

1. **New queries** drafted from accepted references (what they are about, how they were phrased), each with a rationale.
2. **Retirement** of queries whose items keep getting rejected, with the numbers as the reason.

Each proposal is a `PROPOSAL#<id>` record shown as an Accept/Reject card (the one Accept/Reject vocabulary; buttons and a reason
textarea, no dropdowns). Accept applies the change through the same path as an editor's edit (history entry, `approvedBy`);
Reject records the reason and teaches the next proposal. The optimizer never edits a query itself. "Keeps getting rejected" is
learned from the data (a scan statistic over the query's recent items against the monitor's base rate), not a fixed count.

## UI

- **Monitoring page**: a list of monitors with source icons (Lucide `Search` for web, `Rss` for feeds, `Mail` for email), status,
  last run and the week's yield.
- **Monitor detail**: a per-query funnel (found -> included -> accepted), add / edit / pause / retire a query, a **Suggested
  queries** panel of Accept/Reject cards with reasons, and a run-history timeline of QueryRuns.
- **References feed cards**: a "Found by" chip naming the monitor and query (from provenance).

The UI needs a screenshot review before it ships; it is not part of the backend slice.

## Delivery plan

1. **Backend slice (this week)**: monitor + query records seeded from the drafted queries, QueryRun records, the shared
   candidate and provenance with dedupe across HN, email and web by canonical URL, `holdDecisions` routing, every-page collection.
2. **Optimizer**: yield derivation, proposals, the scheduled Lambda.
3. **UI**: Monitoring page, monitor detail, suggested-queries panel, "Found by" chip.
4. **Backfill**: existing HN / email / Hugging Face discoveries into candidates.

Tests: each behaviour ships Gherkin specs and unit tests with a fake provider (no network).
