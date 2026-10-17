---
name: researcher-doctrine
description: Use this skill when doing Papyrus research-agent work, preparing research packets, resolving assignment context, or applying publication and Newsroom section doctrine to evidence gathering.
---

# Researcher Doctrine Skill

Use this skill when acting as a Papyrus researcher, designing a researcher
procedure, reviewing a research packet, or deciding how a research assignment
should apply editorial doctrine.

For coding-agent execution details, CLI inspection commands, Message-backed
research packets, reporting-packet follow-up, and reference-intake work, also
use
[`skills/newsroom-research-workflow/SKILL.md`](../newsroom-research-workflow/SKILL.md).

Doctrine is private operating guidance. It is not reader-facing content and it
is not a replacement for evidence.

## Core Model

Doctrine has two primary scopes:

- **Publication doctrine** applies to all newsroom work.
- **Section doctrine** applies to the configurable Newsroom section that owns
  the assignment.

Topic/category doctrine or metadata may still guide retrieval, but topics are
knowledge scope, not the operational desk identity.

Each scope has two slots:

- **Mission** defines purpose, audience, topic focus, and durable editorial
  priorities.
- **Policies** define standards, boundaries, sourcing expectations, review
  rules, terminology rules, and privacy constraints.

Keep the doctrine text editable in Papyrus data. This skill defines how agents
should use that doctrine, not what the doctrine must say.

## Context Order

Load and apply context in this order:

1. Publication mission and publication policies.
2. Section mission, section policies, assignment guidance, and kill criteria.
3. Assignment brief and editor questions.
4. Relevant category, semantic graph, reference, and corpus evidence context.
5. Recent section activity, topic activity, and prior related coverage.

Publication doctrine is the global editorial constitution. Section doctrine is
the local desk standard. The assignment brief is the immediate task.

If these conflict, surface the conflict in the research packet instead of
silently resolving it. Do not let a narrow assignment shortcut override
publication doctrine unless an editor explicitly says so.

## Research Behavior

Use doctrine to decide what matters, not to invent facts.

- Prefer durable research trends over novelty.
- Treat trending topics as signals to investigate, not reasons to publish.
- Anchor findings in concepts, methods, evidence, and long-running patterns.
- Connect new developments back to the accepted category tree and semantic
  graph when useful.
- Prefer primary sources, scholarly sources, original datasets, durable
  references, and explicit provenance.
- Flag uncertainty, missing evidence, weak support, conflicts, and open
  questions.
- Avoid promotional framing around companies, products, personalities, or
  launches unless the evidence makes them materially relevant.
- Preserve enough source trail for editors and reporters to audit the packet.

## Section And Topic Scope

Newsroom desks now revolve around configurable sections. An assignment may also
carry `topicScopeCategoryKeys` and a `primaryFocusCategoryKey`; use those for
retrieval, evidence filtering, and topic framing without treating them as the
desk itself.

If the applicable section doctrine is missing, continue with publication
doctrine and report that the section doctrine slots are empty.

## Privacy Boundary

Publication and section doctrine are private newsroom data.

Do not quote private doctrine directly in reader-facing drafts unless an editor
explicitly instructs that the text is publishable. Use doctrine to shape
judgment, source selection, coverage gaps, and recommended angles.

Never expose private assignments, unpublished curation notes, private reference
attachments, internal steering comments, or doctrine records as reader-facing
copy.

## Research Packet Shape

For live `Assignment` records, a research packet is a private work-product
`Message`, not a file, publication `Item`, folder, or new top-level GraphQL
model:

- `Message.messageKind = "research_packet"`.
- `Message.messageDomain = "assignment_work"`.
- `ModelAttachment(role = "message_body")` stores the human-readable packet body.
- `ModelAttachment(role = "metadata")` stores JSON with
  `kind = "research.packet.created"`, `assignmentId`, and the structured
  `research` packet.
- New writes link `Assignment --produces--> Message`; older
  `Message --comment--> Assignment` packet links remain readable.

The legacy assignment-`Item` path may still store the packet under
`Item.editorial.newsroom.research`, but do not extend that path for live
assignment work.

When returning a research packet, include these fields inside the structured
packet:

- `summary`: concise evidence-backed finding.
- `doctrine_context`: which publication and section doctrine slots were available,
  without dumping full private text unless the receiving surface is private.
- `section_key`, plus topic-scope category keys when available.
- `evidence_item_ids`: stable external or Papyrus reference ids.
- `queries`: the searches or corpus queries used.
- `source_snapshots`: short auditable source summaries.
- `proposed_references`: candidate source materials for intake, including an
  `ingestion_rationale`.
- `research_notes`: reasoning that helps editors and reporters.
- `open_questions`: unresolved questions.
- `coverage_gaps`: missing sources, weak evidence, or absent viewpoints.
- `recommended_angle`: how the assignment should proceed under the doctrine.

For standing Papyrus desk-backed research workflows, keep any doctrine-backed
comparisons and inclusion/risk work in private structured fields rather than
flattening them into reader-facing prose. For the current automated-publication
workflow, include `comparison_findings` and `rubric_assessments` alongside the
normal packet fields, but derive them from live doctrine plus the current
section/topic-scope context rather than a hard-coded rubric file. See
[`docs/automated-publication-research-workflow.md`](../../docs/automated-publication-research-workflow.md)
for the current section-context contract.

If a packet could become reader-facing later, keep private doctrine and private
curation details in structured private fields, not prose that might be copied
directly into an article.

Fresh web results are not accepted references. Keep them in `source_snapshots`
and `proposed_references`; do not put web `evidence_candidate_id` values in
`evidence_item_ids`.

Coding agents can inspect live assignment packets with:

```bash
poetry run papyrus assignments research-packets --assignment <assignment-id>
```

## Implementation Notes

Papyrus stores doctrine as private `Item` rows with `type = "doctrine"`:

- publication slugs: `editorial-doctrine-mission` and
  `editorial-doctrine-policy`;
- legacy desk slugs: `desk-doctrine-${safeCategoryKey}-mission` and
  `desk-doctrine-${safeCategoryKey}-policy`;
- body paragraphs live in `Item.body`;
- new section-backed workflows should prefer section doctrine from the
  assignment context. Legacy category-tied desk doctrine may still be present
  during migration.

Research agents should consume doctrine through authenticated Newsroom or
assignment-context paths. Do not load doctrine through public reader
repositories, published projections, archive routes, article routes, or edition
loads.
