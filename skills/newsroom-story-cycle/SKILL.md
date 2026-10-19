---
name: newsroom-story-cycle
description: Use this skill when running or inspecting Papyrus story-cycle workflows that research one topic through multiple Newsroom sections, dispatch parallel reporting assignments, retrieve private packet output, or prepare editor selection without creating final copy.
---

# Newsroom Story Cycle Skill

Use this skill when a coding agent needs a repeatable operator path for:

- researching one topic through several `NewsroomSection` lenses;
- dispatching multiple parallel reporting assignments per section;
- finding the resulting private information packets;
- preserving the boundary between assignment work product and publication copy.

The story-cycle is a newsroom budget loop, not an article generator. It creates
private context for editors and copywriters.

## Which Doc/Skill To Use First

| Need | Start here |
| --- | --- |
| Planning run | [`skills/edition-planning/SKILL.md`](../edition-planning/SKILL.md) |
| Run/review cycle | This skill |
| Data contract truth | [`docs/automated-publication-research-workflow.md`](../../docs/automated-publication-research-workflow.md) |

## Domain Model

Keep these concepts separate:

- **Section**: the operational news desk lens, backed by `NewsroomSection`
  mission, policy, guidance, and kill criteria.
- **Topic**: accepted taxonomy scope, backed by `Category`.
- **Coverage concept**: the richer question or concept, backed by
  `SemanticNode`.
- **Research packet**: private `Message` work product with
  `messageKind = "research_packet"`.
- **Reporting packet**: private `Message` work product with
  `messageKind = "reporting_context_packet"`.
- **Draft Item**: reader-facing copy shell created only after editor
  `select`/`brief`.
- **EditionItem**: placement in a reader edition; never created by story-cycle
  packet generation or packet review.

New packet writes use `Assignment --produces--> Message`. Legacy
`Message --comment--> Assignment` packet links may still be read.

Forum context defaults for assignment execution:

- include edition forum threads first when `assignment.editionId` is present;
- include only same-section forum threads for `(edition, section)` lineage when
  those threads exist (planning no longer creates section-forum kickoffs by
  default—see [`skills/edition-planning/SKILL.md`](../edition-planning/SKILL.md));
- never leak other sections' threads into the assignment context.

## Edition forum planning messages

Coverage Theme planning posts **three sequential messages** on the edition
forum thread when optional desks are deferred to phase 2:

1. `Edition theme (phase 1):` — theme and coverage concept only (not Arts/culture
   as the edition theme).
2. `Optional desk (phase 2):` — one proposed floating/rotating desk after
   `rotating_section_selector.tac` (or `--selected-optional-desk`).
3. `Reporting dispatch (phase 3):` — reporting assignment candidates per slot with
   1.5× overassignment.

Use `--through plan` then `--through rotating-desk` for the full sequence. See
edition-planning skill for flags and idempotency rules.

## Default Smoke Command

Run dry-run first. Treat the run as a Coverage Theme in editor-facing language:
one shared topic worked through multiple section lenses. The Python
`coverage-themes run` command is the primary operator surface; the older Node
`assignments run-story-cycle` name remains a compatibility alias.

```bash
poetry run papyrus assignments run-story-cycle \
  --date 2026-05-21 \
  --topic "AI in video games" \
  --category <corpus-key> \
  --coverage-key coverage.ai-in-video-games \
  --sections <section-id>,<section-id> \
  --section-budgets <section-id>:2,<section-id>:1 \
  --research-mode source_discovery \
  --max-parallel-research 2 \
  --max-parallel-reporting 3 \
  --through reporting \
  --json
```

Use the assignment-desk signal feed before edition planning when the topic is
not already chosen:

```bash
poetry run papyrus knowledge signals trend-report \
  --corpus-key <corpus-key> \
  --topic "AI in video games" \
  --sections <section-id>,<section-id> \
  --json
```

Use `--through plan` for assignment graph only, `--through research` to stop
after private research packets, and `--through reporting` to stop after private
reporting packets. `--through reporting` is the default. Story-cycle runs do not
auto-select packets or run copywriting.

The command applies writes by default. Use `--dry-run` when you only want local output
under `.papyrus-runs/story-cycle-<run-id>/` and should create no GraphQL
records.

Run without `--dry-run` when the plan is acceptable and the current
`PAPYRUS_GRAPHQL_ENDPOINT` / `AWS_PROFILE` point at the intended
environment. Apply mode may persist `Assignment`, `AssignmentEvent`, `Message`,
`ModelAttachment`, and `SemanticRelation` records. It must not create `Item` or
`EditionItem` records during packet generation.

Applied reruns reuse existing packet Messages by default so a Coverage Theme can
resume downstream phases without re-running successful upstream agents. Pass
`--refresh-packets` only when the intent is to regenerate those packet payloads.
Reuse is decided per assignment by checking for the deterministic packet
Message, so an applied rerun with every packet present makes zero agent calls.

`--max-parallel-research` and `--max-parallel-reporting` bound how many agent
runs execute at once in each phase (capped at 12); output order stays stable.
Packets missing a required key, or carrying an `editor_recommendation` outside
`select`, `merge`, `brief`, `hold`, `kill`, fail the run instead of being
filled with defaults. Apply reports per-record `failures` and exits not-ok; a
rerun resumes from what already persisted.

In live apply smoke tests, pass `--require-agent-success` so degraded agent
output fails instead of being masked by deterministic fallback packets. Pass
`--allow-fallback` only when fallback behavior is the thing being tested.

## Output Discovery

After a run, inspect the grouped private output:

```bash
poetry run papyrus assignments story-cycle-output \
  --run-id <coverage-theme-run-id> \
  --json
```

The output should be grouped by section and show:

- research packet id or dry-run packet path;
- reporting packet ids or dry-run packet paths;
- reporting angle;
- editor recommendation;
- accepted evidence count;
- proposed reference count;
- risk flags;
- coverage gaps;
- open questions;
- copywriter brief.

For applied runs, the Story Budget board in `/newsroom/assignments?view=budget`
should show Coverage Theme phase state: plan, research, reporting, review,
copywriting, or draft, with reporting candidates grouped by edition and section.

## Section Lenses

Story-cycle commands take `--sections` as a comma-separated list of
`NewsroomSection` ids; with no `--sections` they use every enabled section in
`sortOrder`. An unknown id fails with the list of enabled ids. Each desk's
research lens comes from its `NewsroomSection` row (`assignmentGuidance`, then
`editorialMission`, then `title`), and its default slot count comes from
`defaultPageBudget` unless `--section-budgets` overrides it. Floating and
rotating desks are optional-desk material in edition forum kickoff messages,
not the edition theme decision in phase 1.

## Reporting Assignment Shape

Reporting assignments should use:

- `assignmentTypeKey = "reporting.candidate"`;
- `sectionKey` / `sectionId` for the desk lens;
- `topicScopeCategoryKeys` and `primaryFocusCategoryKey` for taxonomy scope;
- coverage concept metadata such as `coverageConceptKey`;
- `slotTarget` with section slots, candidate rank, and dispatch count;
- `angleDiversity` with the reporting lens and duplicate-angle metadata;
- `expectedOutput = "Private reporting context packet for editor selection and copywriting, not reader copy."`.

Multiple reporting assignments in one section may share the same coverage
concept, but they must carry distinct angle metadata.

## Packet Requirements

Reporter output must include:

- `editor_recommendation`
- `recommended_angle`
- `risk_flags`
- `coverage_gaps`
- `open_questions`
- `accepted_reference_ids`
- `proposed_references`
- `copywriter_brief`

It should also preserve lineage to the section research assignment or research
packet with `derived_from`.

Fresh web findings remain `proposed_references` until reference intake accepts
them. Do not promote proposed references to evidence or copywriting support
inside the story-cycle run.

## Editor Selection

Use this phase as the review-and-selection surface. Reporting packet review can
mutate slot status but still must not place edition content.

Review a reporting packet with:

```bash
poetry run papyrus assignments review-reporting-packet \
  --assignment <assignment-id> \
  --message <message-id> \
  --decision select|merge|brief|hold|kill \
  --note "<editor rationale>" \
  --dry-run
```

Remove `--dry-run` only after reviewing the plan.

- `select` creates a child `copywriting.article-draft` Assignment and
  `derived_from` relations to the reporting Assignment and packet Message. It
  sets the linked slot status to `selected`, sets `selectedAssignmentId`, and
  writes `EditionSlot --selected_by--> Assignment`.
- `brief` creates a child `copywriting.brief-draft` Assignment and
  `derived_from` relations to the reporting Assignment and packet Message. It
  sets the linked slot status to `briefed`, sets `selectedAssignmentId`, and
  writes `EditionSlot --selected_by--> Assignment`.
- `hold` and `kill` write the review event, reset the linked slot to `open`,
  and clear `selectedAssignmentId`.
- `merge` requires `--target-item <id>` and links to that Item. It does not
  fill or mutate a slot unless an explicit slot mutation is performed
  separately.

No packet review creates `Item` or `EditionItem` placement. Run copywriting
after selection with:

```bash
poetry run papyrus assignments run-copywriting \
  --assignment <copywriting-assignment-id> \
  --dry-run
```

Decision table:

| Decision | Slot mutation | Copywriting assignment | Edition placement |
| --- | --- | --- | --- |
| `select` | `selected` + winner set | `copywriting.article-draft` | none |
| `brief` | `briefed` + winner set | `copywriting.brief-draft` | none |
| `hold` | `open` + winner cleared | none | none |
| `kill` | `open` + winner cleared | none | none |
| `merge` | none by default | none | none |

## Forum Operator Loop

For collaborative edition dogfood runs, operate forum threads from
`/newsroom/messages` in forum mode:

- keep one `edition_forum` thread for cross-section coordination (three planning
  messages: theme → optional desk → reporting dispatch);
- use `section_forum` only for ad-hoc desk threads if editors create them;
- append human replies directly in the relevant thread;
- treat those messages as default context for editor/reporter assignment runs.

## Verification

For story-cycle or packet-review changes, run:

```bash
npm run test:categories
python procedures/newsroom/tests/test_newsroom_tools.py
```

Run `npm run lint` and `npm run typecheck` when code or UI files changed.
