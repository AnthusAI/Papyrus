---
name: edition-planning
description: Use this skill when creating a dated Papyrus edition, planning edition slots, dispatching surplus research or reporting assignments, overassigning candidate work, or preparing edition-candidate selection workflows.
---

# Edition Planning Skill

Use this skill when an agent needs to create or prepare a dated Papyrus edition
record and dispatch private research or reporting work ontologically associated
with that edition.

The goal is not to publish every assignment. The goal is to over-dispatch
well-scoped lane work so editors can choose the best outputs for the available
publication slots.

## Which Doc/Skill To Use First

| Need | Start here |
| --- | --- |
| Planning run | This skill |
| Run/review cycle | [`skills/newsroom-story-cycle/SKILL.md`](/Users/ryan/Projects/Papyrus/skills/newsroom-story-cycle/SKILL.md) |
| Data contract truth | [`docs/automated-publication-research-workflow.md`](/Users/ryan/Projects/Papyrus/docs/automated-publication-research-workflow.md) |

## Read First

- `AGENTS.md`: project rules, data boundaries, auth lanes, and layout
  invariants.
- `README.md`: current Newsroom and production workflow overview.
- `skills/category-steering/SKILL.md`: category, taxonomy, graph, auth, and S3
  curation-cycle workflow.
- `skills/reference-intake/SKILL.md`: how new source materials become
  cloud-visible references.
- `skills/researcher-doctrine/SKILL.md`: how researchers apply publication
  doctrine, section doctrine, assignment briefs, and evidence context.
- `skills/newsroom-story-cycle/SKILL.md`: how to run repeatable section-shaped
  research plus parallel reporting agents for one topic.
- `amplify/data/resource.ts`: `Assignment`, `AssignmentEvent`,
  `SemanticRelation`, `Edition`, `Item`, and related auth rules.
- `papyrus`: current authoring commands. Do not invent CLI
  commands that are not present.

If the edition depends on fresh corpus evidence, run the reference-intake and
category-steering workflows first. Edition planning should consume current
reference/category/graph state, not guess from stale local files.

## Core Rules

- Assignments are first-class private `Assignment` records. Do not create
  `Item` rows with `type: "assignment"`.
- Edition planning includes creating or updating the dated private `Edition`
  record. Do not treat the edition as only a date string in assignment metadata.
- Assignment events are append-only audit records. Lifecycle changes should use
  protected actions or the IAM authoring CLI and write `AssignmentEvent` rows.
- Research and reporting assignments are not reader-facing content. Do not
  attach assignments directly to `EditionItem` rows.
- Research agents produce private `research_packet` Messages. Reporting agents
  produce private `reporting_context_packet` Messages. Both are Assignment work
  products, not draft articles.
- Publishable reader content is created later as draft or published `Item`
  records after explicit editor selection, then selected into an `Edition`
  through `EditionItem`.
- Dispatch more assignments than publication slots, then cull/select. The
  default overassignment ratio is `3/2`, so dispatch
  `ceil(publicationSlots * 1.5)` assignments per section/lane target unless an
  editor specifies another ratio.
- Dispatch by configurable Newsroom section plus publication lane. Sections are
  the operational desks; topics/categories are optional knowledge scope for
  retrieval and focus. References are evidence for the assignment. They are not
  the primary planning unit.
- Default active lanes are `reporting`, `analysis`, and `briefs`. `Opinion` can
  exist as a semantic concept, but it is opt-in through publication or desk
  policy and should not be dispatched by default.
- Preserve weaker candidates for review and audit. Do not delete assignment
  records just because they are not selected for publication.
- Keep Papyrus publication-neutral. Edition plans, queues, and assignments
  should use configured categories, desks, corpora, doctrine, and references,
  not hard-coded pilot subject matter.

## How Edition Planning Should Work

Edition planning is **not** “pick one desk name and stop.” It is a stacked set
of decisions:

1. **Edition theme (phase 1, one per edition):** A coverage concept and headline
   theme for the whole issue, grounded in knowledge-base signals (reference
   velocity, concept ranking movement, coverage gaps, prior edition themes).
   `poetry run papyrus knowledge signals trend-report` is the first-pass signal
   feed; `poetry run papyrus editions plan` can materialize multiple ranked
   theme candidates from that report.
2. **Optional / rotating desk (phase 2, at most one):** Which floating desk
   (Arts, Gaming, Health, …) complements the theme without repeating recent
   optional-desk history. This is **not** the edition theme. A phase-2 post that
   says “Arts” is proposing the optional desk, not replacing the phase-1 topic.
3. **Slot fill (phase 3, per desk):** For each confirmed canonical desk plus the
   optional desk when selected, create `EditionSlot` rows from section budgets,
   then dispatch `ceil(slots × 1.5)` **reporting** candidates per desk. Each
   candidate is a distinct story angle bound to a slot rank (`candidateRank`,
   `slotRank`, angle lens). Editors later cull section-first and select winners
   into slots.

What exists today vs what is still thin:

| Layer | Intended | Current automation |
| --- | --- | --- |
| Theme ranking | KB trends + prior editions | `signals trend-report` + optional `editions plan`; CLI `run-story-cycle` still takes an explicit `--topic` |
| Per-slot stories | Ranked candidates per slot from references/concepts | Phase 3 lists assignments; titles are template `Report {topic} for {desk}: {angle}` until richer ranking lands |
| Prior editions | Avoid repeating themes/desks | Phase 2 uses confirmed optional-desk metadata only; full edition-theme memory is not wired yet |
| Research execution | Private packets per assignment | `--through research` / `--through reporting` after dispatch |

Agents should run **plan → rotating-desk → (automatic phase 3 on apply)** for a
new edition, then research/reporting. An empty forum on the nearest upcoming
edition usually means planning has not been re-run after a purge, not that the
UI picked the wrong default edition.

## Edition Slot Plan + Dispatch Checklist

1. Create or update the dated private `Edition`.
2. Materialize `EditionSlot` rows from section budgets before dispatch.
3. Compute section dispatch as `ceil(sectionSlots * 1.5)` by default.
4. Dispatch reporting candidates with deterministic `candidateRank`.
5. Bind each reporting assignment to a concrete slot at creation time:
   - `Assignment.metadata.slotTarget` must include `slotId`, `slotLineageId`,
     `sectionKey`, `slotRank`, `candidateRank`, and `dispatchCount`.
   - write `Assignment --targets_slot--> EditionSlot`.
6. Keep culling section-first by default; cross-section substitution requires
   explicit editor override.
7. Run edition planning as **three sequential messages** on the canonical
   `edition_forum` thread (same thread, increasing sequence numbers):
   - **Phase 1 — edition theme:** proposed theme and coverage concept only.
     Do not treat floating/rotating desks (Arts, Gaming, Health, etc.) as the
     edition theme in this message.
   - **Phase 2 — optional / rotating desk:** after the theme is accepted, run
     `procedures/newsroom/rotating_section_selector.tac` with grounded prior
     optional-desk confirmations only, then post the proposed desk on the same
     edition thread.
   - **Phase 3 — reporting dispatch:** after desks are confirmed (canonical plus
     selected optional desk when applicable), post reporting assignment
     candidates for each slot using the default `ceil(slots * 1.5)` overassignment.
     Defer phase 3 until phase 2 completes when optional desks are still provisional.
   - Re-running the same Coverage Theme plan for the same edition must not post
     duplicate phase-1 kickoff messages when the kickoff body, summary, or
     `importRunId` already exists on the canonical thread.
   - When a later planning pass materially changes the edition topic or posture,
     fork a new forum thread (suffix `-run-<run-id>`) and post a re-plan update
     that links back to the prior kickoff thread in thread metadata
     (`parentThreadId`, `kickoffKind: replan`).
8. Post phase-1 as **proposals**, not decisions:
   - proposed edition theme and coverage concept;
   - explicit steering window for human forum replies (default 48 hours);
   - pointers that phases 2 and 3 will follow on the same thread.
9. Do not create `Item` or `EditionItem` during plan/dispatch.

## Current Safe Workflow

1. Choose the edition identity:
   - `editionDate`, usually `YYYY-MM-DD`;
   - edition slug, usually derived from the date unless the publication already
     has a convention;
   - optional edition lineage/id if updating an existing edition record.
2. Create or update the private dated `Edition` planning record through the
   current editor/admin or IAM authoring role. The edition record is the
   ontological anchor for the assignment batch, even before any reader-facing
   `EditionItem` placements exist.
3. Define section/lane targets:
   - configurable `NewsroomSection` as the operational desk;
   - optional root/focus categories as knowledge scope;
   - lane key, usually `reporting`, `analysis`, or `briefs`;
   - intended publication slot count for the section/lane;
   - desired evidence or source freshness;
   - any editor constraints.
4. Confirm knowledge state is current:
   - new source materials are synced to S3 and imported as `Reference` rows;
   - accepted categories and taxonomy state are current;
   - category/reference relations and semantic graph context are imported;
   - steering feedback has been applied before generating new proposals.
5. Score candidate bundles for each `desk + lane`:
   - freshness;
   - evidence density;
   - source diversity;
   - category confidence;
   - graph relevance;
   - coverage gap;
   - desk-policy fit;
   - duplicate-work penalty.
6. Compute assignment counts per section/lane:
   - default `dispatchCount = ceil(publicationSlots * 1.5)`;
   - lower the count only when an editor explicitly wants less surplus;
   - cap broad searches to avoid flooding reviewers.
7. Create or plan private `Assignment` rows. If the current CLI cannot create
   the exact assignment rows, stop with a clear handoff instead of creating
   surrogate `Item` rows.
8. Link each assignment to the `Edition` record, its Newsroom section, optional
   topic scope, lane concept, and evidence with `SemanticRelation` rows. The
   section index fields support hot queue queries; semantic links make the
   edition-assignment graph navigable.
9. Researchers consume research assignments using
   `skills/researcher-doctrine/SKILL.md` and return private `research_packet`
   Messages.
10. Reporters consume reporting assignments and section research packets to
    return private `reporting_context_packet` Messages.
11. Editors select the strongest reporting packets. Explicit `select` or
    `brief` decisions create child copywriting Assignments, not Items.
12. Copywriting Assignments create or version draft reader-facing `Item`
    records for review. `EditionItem` placement remains a later
    copyediting/layout step.

## Assignment Contract

For edition-candidate research, use:

- `assignmentTypeKey`: `research.edition-candidate`
- `queueKey`: `edition:<editionSlug>:desk:<rootCategoryKey>:lane:<laneKey>`
- `queueStatusKey`: `<queueKey>#<status>` when the model requires it
- `status`: start with the current open/dispatched status expected by the
  protected action or authoring tool
- `title`: concise private task title
- `brief`: editor-readable assignment summary
- `instructions`: researcher-facing work instructions
- `priority`: deterministic from section priority and candidate rank
- `assigneeType`, `assigneeId`, `assigneeKey`: set only when dispatching to a
  specific human, agent, or procedure

Store edition association and planning context in `Assignment.metadata`:

```json
{
  "editionDate": "2026-05-18",
  "editionSlug": "edition-2026-05-18",
  "editionId": "optional-existing-edition-id",
  "editionLineageId": "optional-edition-lineage-id",
  "laneKey": "reporting",
  "laneLabel": "Reporting",
  "laneNodeKey": "editorial.form.reporting",
  "rootCategoryKey": "category-key",
  "rootCategoryLineageId": "category-lineage-id",
  "sectionKey": "technology",
  "publicationSlots": 4,
  "dispatchCount": 6,
  "overassignmentRatio": 1.5,
  "candidateRank": 1,
  "opportunityScore": 72,
  "scoreBreakdown": {
    "freshness": 20,
    "evidenceDensity": 15,
    "sourceDiversity": 10,
    "categoryConfidence": 8,
    "graphRelevance": 4,
    "coverageGap": 10,
    "deskPolicyFit": 10,
    "duplicateWorkPenalty": 5
  },
  "candidateAngle": "Report a fresh evidence-led candidate story.",
  "referenceLineageIds": ["reference-lineage-id"],
  "semanticNodeLineageIds": ["semantic-node-lineage-id"],
  "policyRationale": "Why this assignment fits the publication and desk policy.",
  "expectedOutput": "Research packet for editor review, not reader copy."
}
```

Use stable ids in metadata. Do not key work from display names, short titles,
or generated slugs when a stable id exists.

For section-backed research assignments, store the hot operational fields on
`Assignment` and keep richer doctrine/context data in `Assignment.metadata`:

- `sectionId`
- `sectionKey`
- `sectionType`
- `sectionStatusKey`
- `sectionQueueStatusKey`
- `primaryFocusCategoryKey`
- `topicScopeCategoryKeys`
- `contextProfile`
- `contextTokenBudget`
- `contextSources`

Legacy topic aliases such as `deskCategoryKey`, `focusCategoryKey`,
`researchTrackKey`, and `researchLens` may still be present during migration,
but sections are the desk identity. Topics are knowledge scope.

The current automated-publication desk workflow is documented in
[`docs/automated-publication-research-workflow.md`](/Users/ryan/Projects/Papyrus/docs/automated-publication-research-workflow.md).

## Semantic Links

Use `SemanticRelation` rows to make assignment context navigable:

- `planned_for_edition`: assignment to the dated `Edition` record that caused
  the work.
- `requests_work_on`: assignment to the target `Category`, `Reference`,
  `SemanticNode`, `SemanticRelation`, or `Item`.
- `targets_lane`: assignment to the editorial-form `SemanticNode`, such as
  `editorial.form.reporting`, `editorial.form.analysis`, or
  `editorial.form.briefs`.
- `targets_slot`: reporting assignment to its concrete `EditionSlot` at
  dispatch time. Keep `slotTarget` metadata aligned with this relation.
- Forum anchors (thread model, not relation-only):
  - `edition_forum`: `primaryAnchorKind = "edition"`, `primaryAnchorId = editionId`.
  - `section_forum`: `primaryAnchorKind = "newsroom_section"`,
    `primaryAnchorId = sectionId`, `primaryAnchorLineageId = editionId`.
- `uses_evidence`: assignment to references or comments that support the task.
- `uses_signal`: assignment to graph concepts or relations that influenced the
  opportunity score.
- `derived_from`: assignment to a proposal, comment, category, or research
  signal that caused the work.
- `produces`: assignment to a private packet `Message`, or later to a draft or
  published `Item` after explicit editor selection.

Prefer exact lineage/version ids where the model supports them. Do not depend
on display names for joins.

## Coverage Theme CLI And Edition Intelligence CLI

For repeatable section-shaped research plus reporting, use the Python
Coverage Theme commands. Editor-facing docs and UI should call this a Coverage
Theme: one shared topic or coverage question worked through several section
lenses. The older `run-story-cycle` name remains as compatibility language.

```bash
poetry run papyrus knowledge signals trend-report \
  --corpus-key <corpus-key> \
  --topic "<topic>" \
  --sections <section-key>,<section-key> \
  --json

poetry run papyrus assignments run-story-cycle \
  --date YYYY-MM-DD \
  --topic "<topic>" \
  --category <category-key> \
  --coverage-key <coverage.key> \
  --sections <section-key>,<section-key> \
  --section-budgets <section-key>:<slots> \
  --through reporting \
  --json

### Edition forum messages (agent contract)

After a full planning kickoff, the canonical `edition_forum` thread should have
**up to three posts in order** (same thread, increasing `sequenceNumber`):

| Seq | Phase | Message summary prefix | CLI step |
| --- | --- | --- | --- |
| 1 | Theme | Thread title = derived spine headline; kickoff body has `## Why this edition` | `--through plan` |
| 2 | Optional desk | `Optional desk: {desk}` | `--through rotating-desk` |
| 3 | Reporting dispatch | `Reporting candidates: {spine}` | End of `rotating-desk` apply, or end of `plan` when no optional desk is pending |

Phase 3 message bodies list reporting assignment candidates per desk only (no
process copy about slot math or overassignment in the forum post). The pipeline
still uses `ceil(slots * 1.5)` overassignment when materializing assignments.
Do not post phase 3 until phase 2 confirms
the optional desk when `culture`/Arts-style provisional desks are in the plan.

Typical new edition (e.g. `--sections culture,methods`):

```bash
poetry run papyrus assignments run-story-cycle ... --through plan
poetry run papyrus assignments run-story-cycle ... --through rotating-desk --allow-fallback
# Message 3 is posted automatically on the second command when --dry-run is not set.
```

Phase-specific flags:

- `--through plan --refresh-forum-kickoff` replaces phase-1 theme posts only.
- `--through plan --refresh-forum` soft-deletes all three planning forum posts, then re-posts message 1; run `--through rotating-desk` next for messages 2–3.
- `--through rotating-desk` runs phase-2 optional desk selection and posts message 2; posts message 3 when apply is on.
- `--selected-optional-desk arts` skips the selector agent and uses a human desk choice.
- `--skip-rotating-desk` leaves optional desks pending (no phase-2/3 optional dispatch).
- `--include-optional-desks` restores legacy behavior (dispatch every requested optional desk immediately, no phase-2 gate).

Seed the rotating-desk procedure before cloud runs:

```bash
poetry run papyrus procedures seed-required
```

poetry run papyrus assignments story-cycle-output \
  --run-id <coverage-theme-run-id> \
  --json
```

Use `--through plan` to create only the Coverage Theme assignment graph,
`--through research` to persist private research packets, and
`--through reporting` to persist private research and reporting packets. The
default stop point is through Reporting. Do not auto-select reporting packets,
run copywriting, create `Item` rows, or create `EditionItem` rows from this
command.

Use `poetry run papyrus editions plan` when the edition budget should
be generated from a signal report plus section slots. Its target behavior:

- create or update the dated private `Edition` planning record;
- compute section/lane dispatch counts from planned publication slots;
- create or update `Assignment` rows without duplicating active work;
- link assignments to the `Edition`, `NewsroomSection`, topic `Category`,
  coverage `SemanticNode`, lane concept, references, and graph signals with
  `SemanticRelation`;
- append `AssignmentEvent` audit rows;
- emit a verification report with counts by section, lane, queue, and target type.

Until that CLI exists, use the currently implemented protected actions and IAM
authoring tools. If they cannot create the needed rows, report the missing
tooling explicitly.

## Verification

After planning or dispatching edition assignments:

- list the expected queues with the current assignment CLI, for example:

  ```bash
  poetry run papyrus assignments list \
    --queue edition:<editionSlug>:<sectionKey> \
    --status open
  ```

- verify `/newsroom/assignments` shows the private queue for editor/admin users;
- verify assignment context includes edition date, edition slug, section key,
  lane key, slot count, dispatch count, category context, and score breakdown;
- verify every assignment has a `planned_for_edition` `SemanticRelation` to the
  dated `Edition`;
- verify every assignment has `targets_section`, `targets_topic`,
  `requests_work_on` for the coverage concept, and `targets_lane` for the lane
  semantic concept;
- verify evidence and target links are present through `SemanticRelation`;
- verify no `Item` rows were created with `type: "assignment"`;
- verify no assignment was attached directly to reader-facing `EditionItem`.

## Handoff

Report:

- edition date and slug;
- section slot counts and dispatch counts;
- assignment ids and queues created or planned;
- target categories, references, and semantic nodes used;
- any missing category/reference freshness prerequisites;
- whether the work is only planned, dry-run, or actually written through the
  editor/admin or IAM-authoring role.
