# Newsroom operations

The `/newsroom` workspace, assignments, Coverage Themes, packets, steering and the pilot production edition. Moved out of the README. Agent workflows live in `skills/`.

## Newsroom

`/newsroom` is the Papyrus newsroom operations workspace. `Topics` is the
taxonomy steering tab. `Sections` is the operational desk surface backed by
`NewsroomSection` doctrine and budgets. `Doctrine` is the publication-wide
mission and policies surface. The page is driven by the configured corpora for
the publication, not by hard-coded corpus names.

`/newsroom` chrome is an application shell (Shadcn tokens and sans fonts), not
the Pretext newspaper masthead. Reader pages keep newsprint/Pretext. Before:
ops sat inside `.paper-page` / `.masthead`. After: `[data-newsroom-chrome=app]`
with a header and section nav. Inner desks (Topics, References, Assignments)
are unchanged in this foundation slice.

Tenant theme packs live on `SiteBrand` (`themePack`, moss/ochre/paper tokens,
independent `renderer`, `hosting`, and `opsChrome`). Papyr.us, Threat
Intelligence, and Pilobolus reuse the same `/newsroom` chrome. Pilobolus is
the first extra pack (`PAPYRUS_SITE_BRAND=pilobol-us`) and maps the Markus
fungus-among-us palette (paper `#f1ead9`, moss `#3f5d43`, ochre `#a35a2a`,
plus dark counterparts) into Shadcn CSS variables. Colors are copied into
Papyrus; the Pilobolus theme file is not loaded at runtime. Typography stays
on the Shadcn stack. Shared ops components read CSS tokens; they do not
hard-code publication names or Pilobolus hexes. GraphQL/AppSync remains the
data source of truth. How to add a pack: [docs/site-theme-packs.md](site-theme-packs.md).
Ops vs reader renderer are independent: [docs/site-stacks.md](site-stacks.md).

```bash
npm run dev
# or: npm run dev:127
```

Then open [http://127.0.0.1:3001/newsroom?demo=1](http://127.0.0.1:3001/newsroom?demo=1).
Set `PAPYRUS_SITE_BRAND=pilobol-us` to apply the official Pilobolus palette.
Offline chrome review can use `amplify/fixtures/demo-amplify-outputs.json` when sandbox generate is unavailable (`npm run dev:127` copies that stub into ignored `amplify_outputs.json` and warns that it is demo-only).

Papyrus owns the human steering
state in GraphQL: knowledge corpora,
import runs, artifacts, accepted category sets, strict-tree categories, private
`Reference` metadata, private `SemanticRelation` links, proposals, and
append-only decisions.

Edition planning and assignment dispatch use first-class private `Assignment`
records, not `Item` rows with assignment types. Follow
[skills/edition-planning/SKILL.md](../skills/edition-planning/SKILL.md) when
creating a dated edition, planning section slots, or dispatching surplus
candidate work. Follow
[skills/newsroom-story-cycle/SKILL.md](../skills/newsroom-story-cycle/SKILL.md)
when running the repeatable research -> reporting cascade for one topic across
multiple sections.

That repeatable cascade is editor-facing as a Coverage Theme: one shared topic
or coverage question, shaped by section doctrine into research packets,
reporting packets, editor decisions, copywriting assignments, draft Items, and
later placement. `assignments run-story-cycle` is the CLI name for running a
Coverage Theme; by default it stops after private reporting packets are created.
Applied reruns reuse existing packet Messages by default so a partial Coverage
Theme can resume forward; pass `--refresh-packets` when existing packet payloads
should be regenerated.

The dated private `Edition` record is created or updated first; each assignment
is then linked to that edition, its `NewsroomSection`, its accepted topic scope,
its coverage concept, its publication lane, and accepted evidence with
`SemanticRelation` rows. The default lanes are `reporting`, `analysis`, and
`briefs`; `opinion` is opt-in through publication or desk policy. The default
dispatch ratio is `3/2`: for each section/lane target, dispatch a small surplus
of candidates so editors can select the strongest outputs without publishing
every result.

Assignments remain private workflow records with append-only `AssignmentEvent`
audit rows and `SemanticRelation` links to categories, references, graph
entities, private packet messages, and eventual drafts. Research and reporting
agents do not create publication Items as their normal work product. They create
private `Message` work products with `ModelAttachment` payloads:

- `research_packet`: internal evidence, source prospects, source snapshots,
  open questions, and reference-intake handoff.
- `reporting_context_packet`: editor-facing context for one candidate story,
  including the angle, confirmed facts, source trail, risks, gaps, verification
  needs, recommendation, and copywriter brief. Reporting packets must include
  knowledge-first orientation trace (`sourceTrail` plus
  `knowledgeQueries`/`papyrusUrisInspected`, or `knowledgeBlockedReason`).

New packet writes link `Assignment --produces--> Message`; older
`Message --comment--> Assignment` packet links remain readable for compatibility.
Fresh web findings stay in packet `proposedReferences` until reference intake
registers them and curation accepts them as `Reference` evidence. Explicit editor
selection is the gate from reporting packet to copywriting:
`select` creates a `copywriting.article-draft` Assignment, `brief` creates a
`copywriting.brief-draft` Assignment, `merge` links the packet to an existing
draft, and `hold`/`kill` keep the packet private. Copywriting is the first stage
allowed to create draft reader-facing `Item` records, and neither packet
generation nor packet review creates `EditionItem` placement.
When reporting runs multiple times for the same Assignment, each run writes a
new immutable packet Message. The most recent successful
`reporting_context_packet` is canonical for downstream copywriting intake by
default.
The editor-only `Assignments` desk tab at `/newsroom/assignments`, including the
Story Budget view, is the review surface for these private queues.

Assignment claiming is an execution lease, not universal identity ownership.
`Assignment.assigneeKey` is the flexible coordination string for the current
worker cycle; it may name a human, a procedure run, a worker process, or a
coding-agent session. Assignment types decide whether claiming is required.
`analysis.reindex` work requires an exclusive claim, ideally with a TTL, before
any Biblicus command plan is executed.

The Newsroom should feel like another section of the newspaper, not a separate
administrative app. Steering proposals are optional editorial notes: the
publication keeps following the accepted category set unless a human chooses to
accept, reject, or rewrite a proposal while reading. Ignoring a proposal is also
valid steering: no decision is recorded, and the accepted course continues.

The steering system is publication-neutral. `corpora/papyrus-steering.yml`
selects the canonical corpus, lists any source/supporting corpora, names local
classifiers, and points at the S3 corpus prefixes. The AI/ML entries in the
checked-in config are the current production example, not a schema assumption.
Future research agents should read their domain-specific instructions from
configuration beside the corpus/publication data, produce Biblicus artifacts,
and import only stable steering outputs into Papyrus.

Researcher behavior should follow
[skills/researcher-doctrine/SKILL.md](../skills/researcher-doctrine/SKILL.md):
publication doctrine is the global editorial constitution, section doctrine is
the local desk standard, and the assignment brief is the immediate task.
Doctrine stays private and editable in Papyrus data; the skill defines how
agents apply it while gathering evidence and preparing research packets.
Coding agents that need to run the same assignment workflow outside a Tactus
procedure should use
[skills/newsroom-research-workflow/SKILL.md](../skills/newsroom-research-workflow/SKILL.md).
Live assignment research packets are private `Message` work products linked to
the `Assignment`, and proposed web sources remain reference prospects until
intake registers them.

Biblicus remains the artifact and worker tool boundary. Workers may run
Biblicus commands that create reproducible artifacts, but Papyrus code should
not edit Biblicus corpus sidecars, catalogs, or internals directly. The local
`corpora/` folder is a working-copy convenience; durable corpus storage lives in
the production Amplify Storage bucket under `corpora/`. The committed
`corpora/papyrus-steering.yml` file is the v1 steering config contract that
names the publication corpora, their roles, local classifier ids, and S3
prefixes. Mirror that YAML to S3 beside the corpus data and materialize it into
GraphQL with `categories import-config`.

For local or EC2 analysis workers, use
[`docs/newsroom-worker-bootstrap.md`](newsroom-worker-bootstrap.md).
Workers must synchronize corpus files from S3 into the local Biblicus working
copy before running analysis, and must separately verify that Papyrus GraphQL has
registered `Reference` rows for the same corpus materials. S3 presence alone
does not make references visible or analysis-eligible.

Private canonical publishing and knowledge records are versioned in place:
`Item`, `Edition`, `CategorySet`, `Category`, `Reference`, and `SemanticNode`
carry lineage, version number, previous version, version state, author/time
metadata, change reason, and content hash. There are no separate version
tables. `EditionItem` rows belong to an exact edition version and point to exact
item versions; `SemanticRelation` rows point to exact subject/object versions.

Public readers use only published projections: `PublishedEdition`,
`PublishedEditionItem`, `PublishedItem`, `PublishedMediaAsset`,
`PublishedCategorySet`, and `PublishedCategory`. Private canonical tables are
editor/admin and IAM-authoring only; API-key reads are limited to the projection
tables. Publishing materializes approved current versions into projections, so
the reader path stays a direct AppSync read without a Lambda call.

Raw Biblicus steering payloads and import internals live in `KnowledgeRawPayload`,
which is private to editor/admin users and the IAM-authorized worker lane.
Actual corpus contents do not belong in GraphQL. `Reference` records store only
strict metadata such as Biblicus `item_id`, title, authors, source URI, S3/corpus
path, media type, checksum, dates, and sanitized provenance. Stable IDs such as
`category_key`, classifier ids, snapshot/artifact refs, corpus identity, and
category lineage ids are the API contract; display names are editable copy, not
keys. New knowledge-base source materials should follow
[skills/reference-intake/SKILL.md](../skills/reference-intake/SKILL.md): register
references and attachment metadata in Papyrus, keep corpus contents in S3 and
Biblicus artifacts, and do not model references as publication `Item` rows.
Private operational text and JSON payloads use `ModelAttachment` rows plus S3
objects under `newsroom/payloads/`. Clients do not need long-lived AWS
credentials for those payloads: the API creates short-lived upload slots, the
client uploads directly to the signed S3 URL, and the API verifies and commits
the attachment row. Bulk Biblicus corpus sync under `corpora/*` remains a
worker/admin S3 operation for now.
`Reference.curationStatus` separates visibility from evidence eligibility:
pending prospects and rejected scope memory stay visible for curation, comments,
votes, and training exports, but only current accepted references may feed
evidence sets, topic modeling, graph analysis, desk memory, context packs, or
edition planning.
Research packets and assignment evidence should also follow
[skills/researcher-doctrine/SKILL.md](../skills/researcher-doctrine/SKILL.md) so
agents apply publication doctrine, section doctrine, assignment briefs, graph
context, accepted evidence, and recent desk activity in the correct order.

Category proposal review writes an append-only `SteeringDecision` and creates
new `Category` versions when accepted edits change category copy or tree state.
Accepted category trees are modeled as strict parent/child `Category` rows under
a versioned `CategorySet`; full Biblicus taxonomy manifests stay private in
`KnowledgeRawPayload`. Signed-in editor/admin readers see passive Newsroom
appendix pages after each edition. Public readers get the normal newspaper
edition with no appended category pages. The Biblicus labels `recommend`,
`do_not_recommend`, and
`needs_clarification` are agent recommendation labels, not Papyrus human review
actions; the Newsroom exposes `accept` and `reject` as explicit human decisions.
Editors can ignore a proposal by leaving it alone.

Rejected proposals must influence future category steering. Before a new taxonomy,
ontology, or graph proposal cycle, export the Papyrus review memory:

```bash
poetry run papyrus ops categories export-steering-feedback \
  --category-set <category-set-id> \
  --output /tmp/papyrus-steering-feedback.json
```

That JSON contains append-only decisions, reviewed proposals, and normalized
`suppressions` scoped by category set, corpus, classifier, and root topic. Workers
must pass it to `biblicus taxonomy discover` and
`biblicus steering graph-signals` with `--steering-feedback` so rejected child
topics, labels, relationships, or weak patterns are not proposed again.
Accepted taxonomy exports define the current tree; steering-feedback exports
carry the positive and negative review memory.

Keyword evidence and ignored-term steering are also first-class private
Newsroom data. `CategoryKeyword` rows show the weighted terms that define each
category or subcategory, while `LexicalSteeringRule` rows capture ignored terms
such as citation/header noise. Defaults live in
`corpora/papyrus-lexical-steering.yml` and are materialized by
`categories import-config`. Export active lexical steering before a new analysis
cycle with:

```bash
poetry run papyrus ops categories export-lexical-steering \
  --output /tmp/papyrus-lexical-steering.json
```

Papyrus exports this contract now; Biblicus support for consuming it during
taxonomy discovery or classifier train/project must be confirmed by the Biblicus
agent before workers rely on it.

## Current Production Edition

The production `edition-current` record is the AI/ML corpus first edition dated
`2026-05-13`. The live content source of truth is Amplify Data, especially
`Edition.layoutPlan`, `EditionItem`, `Item`, `Tag`, `ItemTag`, and `MediaAsset`
records.

- Page 1 is a `front.mosaic` page with six planned `articleFrame` teaser blocks.
- Pages 2 through 7 are planned continuation pages for the front-page AI/ML
  corpus stories.
- Page 8 is a stacked page containing the ASR correction story and ML history
  story.
- The current production edition uses section labels that align with its
  accepted topic taxonomy, such as
  `Self-Evolving LLM Agents`,
  `AI Agent Reliability and Evaluation`,
  `Autonomous AI Scientific Discovery`,
  `Multimodal Document Understanding Pretraining`,
  `LLM Confidence Calibration and Instruction Tuning`,
  `ASR Error Correction and System Combination`, and
  `Early Machine Learning in Games and Backpropagation History`.
- Direct article routes remain available at `/articles/[slug]`.

When production content changes, inspect the live `Edition.layoutPlan` instead
of trusting this README as the layout source of truth.
