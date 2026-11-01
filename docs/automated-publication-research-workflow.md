# Newsroom Assignment Work Product Workflow

Papyrus newsroom automation revolves around `Assignment` records and private work
products. Research and reporting agents do not normally create reader-facing
copy. They create structured context packets that let editors decide what should
be selected, merged, briefed, held, killed, or sent to copywriting.

This file keeps the older automated-publication research path aligned with the
current general model. Automated-publication systems may be one covered beat, but
the workflow is publication-neutral: change the corpus config, accepted
taxonomy, ontology, sections, doctrine, and edition plan, and the same machinery
should work for another publication.

## Which Doc/Skill To Use First

| Need | Start here |
| --- | --- |
| Planning run | [`skills/edition-planning/SKILL.md`](../skills/edition-planning/SKILL.md) |
| Run/review cycle | [`skills/newsroom-story-cycle/SKILL.md`](../skills/newsroom-story-cycle/SKILL.md) |
| Data contract truth | This file |

## Mental Model

Use these objects as distinct editorial concepts:

- `NewsroomSection`: the operational section lens. It supplies mission, policy,
  assignment guidance, kill criteria, visual guidance, and recent section memory.
- `Category`: the accepted taxonomy scope. It says what body of knowledge the
  work belongs to.
- `SemanticNode`: the richer coverage concept, entity, or question. It lets
  several sections work on the same underlying topic without collapsing their
  editorial angles.
- `Assignment`: the private unit of work for a human, agent, or procedure.
- `Message`: the private work product attached to an assignment.
- `ModelAttachment`: the structured body and metadata payload for a private
  work product or event.
- `Item`: reader-facing publication copy. It is created only after editor
  selection, copywriting, or explicit publishing workflow.
- `EditionItem`: layout placement. It is never created by packet generation or
  packet review.

The normal graph shape is:

```text
Edition
  <- planned_for_edition - Assignment
Assignment
  - targets_section -> NewsroomSection
  - targets_topic -> Category
  - requests_work_on -> SemanticNode
  - targets_lane -> SemanticNode(editorial.form.*)
  - uses_evidence -> accepted Reference
  - produces -> Message(research_packet or reporting_context_packet)
  - derived_from -> source Assignment or source Message
```

New packet writes use `Assignment --produces--> Message`. Existing
`Message --comment--> Assignment` packet links remain readable for compatibility.

## Edition Slot Orchestration

`EditionSlot` is the planning unit for section-first culling and final packet
selection. Story-cycle dispatch binds reporting candidates to concrete slots
before review starts.

Field contract:

- `id`, `editionId`, `sectionKey`, `slotRank`
- `targetType` (`article|brief`)
- `targetLengthBand`
- `minImageAssets`
- `status` (`open|assigned|selected|briefed|filled|killed`)
- `selectedAssignmentId`
- `createdAt`, `updatedAt`

Current flow:

- Slot creation starts in `assigned` status during planning.
- Reporting dispatch must set assignment metadata `slotTarget` and write
  `Assignment --targets_slot--> EditionSlot`.
- Review `select|brief` writes `EditionSlot --selected_by--> Assignment` and
  sets slot status to `selected` or `briefed` with `selectedAssignmentId`.
- Review `hold|kill` keeps the slot available by resetting slot state to
  `open` and clearing `selectedAssignmentId`.
- Review `merge` does not mutate slot state unless an explicit slot mutation is
  requested separately.
- `filled` and `killed` remain later editorial/layout lifecycle states, not
  reporting-packet review outcomes.

Decision matrix:

| Decision | Slot status mutation | Slot relation mutation | Copywriting child | Notes |
| --- | --- | --- | --- | --- |
| `select` | `selected` + set `selectedAssignmentId` | add `selected_by` | `copywriting.article-draft` | Marks slot winner candidate. |
| `brief` | `briefed` + set `selectedAssignmentId` | add `selected_by` | `copywriting.brief-draft` | Marks slot winner candidate for brief lane. |
| `hold` | `open` + clear `selectedAssignmentId` | none | none | Candidate kept private; slot stays available. |
| `kill` | `open` + clear `selectedAssignmentId` | none | none | Candidate rejected; slot stays available. |
| `merge` | none by default | none by default | none | Does not fill a slot unless explicitly attached. |

Section-first culling rule:

- Compare and cull candidates within each section slot budget first.
- Cross-section substitution is an explicit editor override, not a default.

Story Budget should be read as a slot-centric board:

- per-slot pipeline state;
- candidate stack mapped to each slot;
- selected winner per slot;
- fill delta and unresolved slots;
- section rollups as derived aggregates.

## Edition And Section Forum Threads

Upcoming edition coordination uses first-class `MessageThread` rows with forum
thread kinds:

- `edition_forum`: `primaryAnchorKind = "edition"` and
  `primaryAnchorId = <editionId>`.
- `section_forum`: `primaryAnchorKind = "newsroom_section"`,
  `primaryAnchorId = <sectionId>`, and
  `primaryAnchorLineageId = <editionId>`.

Section forums are many-to-one: multiple threads are allowed for the same
`(edition, section)` lineage.

Message threading contract is unchanged:

- `Message.threadId` links to the parent thread.
- `Message.parentMessageId` links replies.
- `Message.sequenceNumber` preserves chronology.

### Kickoff + Human Steering

Coverage Theme planning posts **three sequential messages** on the canonical
`edition_forum` thread (increasing `sequenceNumber` on the same thread):

| Phase | Summary prefix | Content |
| --- | --- | --- |
| 1 | `Edition theme (phase 1):` | Proposed edition theme and coverage concept; pointers to phases 2–3. Floating/rotating sections are **not** the edition theme. |
| 2 | `Optional desk (phase 2):` | One proposed optional section after `rotating_section_selector.tac` (informed by the accepted theme). |
| 3 | `Reporting dispatch (phase 3):` | Reporting assignment candidates per confirmed section, with default `ceil(slots * 1.5)` overassignment. |

Phase 3 is deferred until phase 2 completes when optional sections are still
provisional (floating or rotating sections). Recent optional-section
history in phase 2 uses **confirmed** prior selections only (`selectedOptionalDeskKey`
on past editions)—not provisional `sectionBudgets` rows.

Planning no longer posts default `section_forum` kickoffs; section-specific steering
for dispatch lives in message 3 and in assignment briefs. Legacy `section_forum`
threads may still exist and remain readable in assignment context.

CLI: `--through plan` (message 1), then `--through rotating-desk` (messages 2–3
on apply). See `skills/edition-planning/SKILL.md` for flags.

The planner is idempotent on the canonical edition forum thread: an accidental
re-run with the same kickoff body or `importRunId` must not append a duplicate
phase post. A materially new planning pass should fork a new thread and post a
re-plan update there so the original chronology stays intact.

Humans append replies in the edition thread. That chronology is shared editorial
memory for the edition run.

### Assignment Context Inclusion Defaults

Assignment context assembly must include forum threads by default:

1. If an assignment has `editionId`, include edition-forum thread history first.
2. If an assignment is section-bound, include only section-forum thread history
   for that same `(edition, section)` lineage.
3. Never include forum threads from other sections.

Current policy is full-history inclusion (no compaction) in chronological order
within each thread.

## Packet Types

`research_packet` is the exploratory evidence product. It can summarize accepted
internal evidence, source snapshots, proposed references, unresolved gaps,
queries, source-diversity notes, and an intake handoff. Fresh web findings are
source-material prospects, not accepted evidence.

`reporting_context_packet` is the candidate product. It packages the
context required for possible copywriting of one article or brief. It should
include:

- `summary`, `section_key`, `edition_id`, `candidate_rank`, `slot_target`
- `why_now`, `nut_graf_candidate`, `recommended_angle`
- `confirmed_facts`, `source_trail`, `accepted_reference_ids`
- `proposed_references`
- `recent_desk_memory_used`, `coverage_gaps`, `open_questions`
- `risk_flags`, `verification_needs`, `source_diversity_notes`
- knowledge-orientation trace: `source_trail`, `knowledge_queries`,
  `papyrus_uris_inspected`, and optional `knowledge_blocked_reason`
- `copywriter_brief`
- `editor_recommendation`: `select`, `merge`, `brief`, `hold`, or `kill`

Both packet types are private `Message` rows with
`messageDomain = "assignment_work"` plus `ModelAttachment` payloads. The
human-readable body lives in a `ModelAttachment` with role `message_body`; the
structured packet lives in a `ModelAttachment` with role `metadata`.

## Multi-search research (`research.multi`)

Most assignments are researched with the site's normal search (Google first: the default chain is `gemini,openai`). Multi-search is
a special mode an editor reserves for an assignment that deserves a wider net. It is **opt-in per assignment and never the
default**: nothing creates a `research.multi` assignment or runs it automatically, and an assignment created without `--type` is
still `research.candidate`.

**Picking the mode.** The mode is the assignment type, chosen when the assignment is created, beside `research.tavily-deep`:

```bash
papyrus research create --type research.multi --title "Assess Fastino GLiDE's claims on reasoning benchmarks" --section ai
papyrus assignments research-multi <assignment-id> [--dry-run]
```

`research-multi` writes by default; `--dry-run` runs the searches and the two model calls, prints the plan and the per-provider
contribution, and writes nothing. Also accepted: `--corpus-key`, `--config`, `--model`, `--intake-proposals false`, `--json`.
The newsroom lists no assignment types today, so the CLI (and `Assignment.create` with `type`) is where an editor picks the mode.

**What it does** (`src/papyrus_content/multi_search_research.py`):

1. *Plan.* One model call (`DEFAULT_LLM_MODEL`, the OpenAI Responses API) turns the brief (title, summary, notes, instructions and
   the assignment's section, angle and topic scope) into search queries, each with a short purpose such as "independent
   benchmarks". The number of queries comes from the brief; there is no fixed count.
2. *Fan out.* Every query runs on every configured provider of `papyrus_content.web_search` (a key, or AWS credentials and
   `BEDROCK_SEARCH_MODEL` for Bedrock), one thread per provider. A failure is recorded with its kind (`plan_exhausted`, `auth`,
   `rate_limited`, ...) and never stops the others; a provider whose key is refused or plan is spent is not asked again. A provider
   with no key is listed as unavailable, not as a failure.
3. *Merge.* URLs are canonicalised (tracking parameters, fragment, `www.`, trailing slash) and de-duplicated. Each source keeps the
   providers that found it, the queries, its best rank, its title and its snippets. A source only one provider found is kept.
4. *Synthesise.* One model call over the merged sources, cited by index, writes the claims with their supporting sources, where the
   sources disagree, and the open questions. Claims or positions citing a source that does not exist are dropped and counted.

**The packet.** It is written through the same path as `research.tavily-deep` (`apply_research_packet`, then
`intake_research_packet_proposals`), so the newsroom shows an ordinary research packet whose body also lists the claims,
disagreements and open questions. `proposedReferences` come from the merged set and each names its providers. The packet metadata
adds `claims`, `disagreements` and `multiSearch`: the queries, `sourceProviders` (providers and best rank per source), and
`providers`, the per-provider contribution:

| field | meaning |
| --- | --- |
| `queriesRun`, `hits` | queries the provider answered, and hits it returned |
| `sources`, `uniqueSources` | merged sources it found, and those no other provider found |
| `failures` | `{query, kind, status, message}` for each failed query |
| `elapsedMs` | time spent in that provider's calls |

**Failure.** If no provider answers (or none is configured, or the planning or synthesis call fails) no packet is written. A
`multi_search_error` Message and a `research.multi.failed` AssignmentEvent record the reason, as `research.tavily-deep` does.
Fetching pages is not part of this mode; snippets are the evidence, so every claim is a lead to verify, not a verified fact.

## Context Order

Agents should assemble context in this order:

1. Publication mission and policies.
2. Section mission, section policies, assignment guidance, and kill criteria.
3. Assignment brief, editor questions, candidate rank, slot target, and angle.
4. Accepted taxonomy and coverage concept context.
5. Accepted knowledge-base evidence only.
6. Recent section memory and shared coverage-node memory.
7. Fresh-source needs and proposed-reference gaps.

Doctrine is private operating guidance. It shapes packet judgment but should not
be copied into reader-facing fields.

## Reference Boundary

Only current accepted `Reference` records are evidence-eligible. Pending
reference prospects and rejected scope memory remain visible for curation and
training workflows, but they are not source support for reader-facing claims.

When a researcher or reporter finds a new web source, the packet should store it
as `sourceSnapshots` and/or `proposedReferences` with an ingestion rationale.
Reference intake then registers the prospect as pending. Curation later accepts
or rejects it. Only accepted references can become `uses_evidence` links,
knowledge-query evidence, section memory, or copywriting support.

## Story-Cycle Run

The repeatable smoke-test and operator flow is CLI-first. In editor-facing
language, one run is a Coverage Theme: a shared topic or coverage question
worked through multiple section lenses. The CLI command remains
`assignments run-story-cycle` for compatibility.

```bash
poetry run papyrus assignments run-story-cycle \
  --date 2026-05-21 \
  --topic "AI in video games" \
  --category AI-ML-research \
  --coverage-key coverage.ai-in-video-games \
  --sections <section-id>,<section-id> \
  --section-budgets <section-id>:2,<section-id>:1 \
  --research-mode source_discovery \
  --max-parallel-research 2 \
  --max-parallel-reporting 3 \
  --through reporting \
  --json
```

`--through plan` creates only the Coverage Theme assignment graph.
`--through research` also persists private `research_packet` work products.
`--through reporting` also persists private `reporting_context_packet` work
products and is the default. Story-cycle orchestration never auto-selects
packets or runs copywriting.

Dry-run is the default. It creates local output under
`.papyrus-runs/story-cycle-<run-id>/`: `manifest.json`, child research logs,
child reporting logs, packet JSON files, and `story-cycle-output.json`.

Cloud procedure runs also write structured per-call LLM context trace artifacts
under each run directory:

- `llm-context/summary.json`: indexed metadata and call list
- `llm-context/calls.jsonl`: one record per LLM call with the exact message
  array sent to the model (system prompt + history + user/tool messages)
- `llm-context/execute_tactus_calls.jsonl`: one record per `execute_tactus`
  call, including harness, args, and the exact `tactus` snippet passed to the
  runtime

Use these files as the canonical local audit trail for context engineering
debugging and verification.

Apply mode persists private work products only: `Assignment`, `AssignmentEvent`,
`Message`, `ModelAttachment`, and `SemanticRelation`. It must not create
`Item` or `EditionItem` records during packet generation. In live apply mode,
degraded agent output fails unless `--allow-fallback` is explicit; use
`--require-agent-success` in smoke tests when fallback packets should be treated
as a failure. Applied reruns reuse existing packet Messages by default so a
Coverage Theme can resume downstream phases; pass `--refresh-packets` only when
the intent is to regenerate already persisted packet payloads.

Inspect output with:

```bash
poetry run papyrus assignments story-cycle-output \
  --run-id <story-cycle-run-id> \
  --json
```

For applied Coverage Themes, output is rediscovered from GraphQL first and uses
the local manifest only for log paths and diagnostics. The output is grouped by
section and shows the research packet, reporting
packets, angles, editor recommendations, accepted evidence counts, proposed
reference counts, risk flags, gaps, open questions, and copywriter briefs.

## Editor Selection

Editors review `reporting_context_packet` rows from `/newsroom/assignments` or
the CLI:

```bash
poetry run papyrus assignments review-reporting-packet \
  --assignment <assignment-id> \
  --message <message-id> \
  --decision select|merge|brief|hold|kill \
  --note "<editor rationale>" \
  --dry-run
```

Decision effects:

- `select`: create a child `copywriting.article-draft` Assignment, link it back
  to the reporting Assignment and packet Message with `derived_from`, and record
  the event.
- `brief`: create a child `copywriting.brief-draft` Assignment, link it back to
  the reporting Assignment and packet Message with `derived_from`, and record
  the event.
- `merge`: require `--target-item <id>`, link the assignment to that target
  `Item`, and record the event.
- `hold`: record the event and keep the packet private.
- `kill`: record the event and keep the packet private.

Run the copywriting Assignment after selection:

```bash
poetry run papyrus assignments run-copywriting \
  --assignment <copywriting-assignment-id> \
  --dry-run
```

Copywriting creates or versions draft `Item` records. Packet review itself does
not create `Item` or `EditionItem` records.

Packet review never creates `EditionItem` placement. Placement remains a later
copyediting/layout step after a draft exists.

## UI Surface

`/newsroom/assignments` has two related views:

- `Queue`: lifecycle and worker coordination, including claim, release,
  complete, cancel, and reopen.
- `Story Budget`: editorial budget review for `reporting.candidate`
  assignments grouped by edition and section.

Keep those workflows separate. Lifecycle actions answer "who is working this
assignment and is it done?" Story Budget decisions answer "what should happen to
this reporting packet?"

## Procedure Usage

Researchers use `procedures/newsroom/research_explorer.tac` or
`procedures/newsroom/researcher.tac` to produce `research_packet` payloads.
Reporters use `procedures/newsroom/reporter.tac` to produce
`reporting_context_packet` payloads for live `reporting.candidate`
assignments. Agents do not own persistence mechanics; the CLI/procedure layer
turns payloads into deterministic `Message`, `ModelAttachment`, and
`SemanticRelation` writes.

Live reporting runs use a strict path: one deterministic internal-orientation
step (`assignment_context`, `assignment_agent_context`, then one broad scoped
`knowledge_query`) before any optional follow-up lookup. Reporter tool flow does
not rely on `done` short-circuit behavior in this path.

Reporting runs are immutable packet history. Multiple packet Messages may exist
for one Assignment, and downstream copywriting should treat the most recent
successful `reporting_context_packet` Message as canonical unless an explicit
editor workflow chooses a specific Message id.

When orientation cannot complete, the default behavior is a valid `hold` packet
with explicit `knowledge_blocked_reason` (plus orientation-attempt metadata),
not a pipeline crash.

When current external evidence is required, Tactus snippets should import the
standard web module:

```tactus
local web = require("tactus.web")
```

Use `web.search{...}` or `web.synthesize{...}` with `provider = "openai"`.
Papyrus consumes the normalized result in private packet fields; it does not
write accepted source records directly from web search.
