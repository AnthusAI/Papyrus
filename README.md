# Papyrus

You are focused on a topic. For us, it is AI/ML information systems. For you,
it might be golf club technology, underwater basket weaving, oil markets, local
politics, or any other beat worth watching closely.

Papyrus turns that focus into a fully automated newsroom. Research agents
monitor the beat while you sleep, update a publication-specific knowledge base,
and surface surprising developments. Editor agents turn those signals into
assignments. Reporter agents prepare private reporting packets: the verified
facts, source trail, open questions, risks, angle, and copywriter brief an editor
needs before commissioning reader-facing copy. Copywriter agents turn selected
packets into draft Items for review. The next morning, you can open your
newsroom and see what it found, what it recommends, what needs copywriting, and
what is ready for review.

You steer it like an executive editor, as much or as little as you want:
choosing the canonical categories for topic coverage, configuring editorial
sections for the issue, setting editorial policy, selecting the strongest
packets for copywriting, commenting on drafts, and culling assignments before
publication. When you step back, Papyrus keeps operating from the momentum you
already gave it: accepted categories, current policy, section doctrine, open
assignments, prior decisions, and rejected proposal memory.

The beat is configuration, not code. The current AI/ML corpus is pilot content,
not an application assumption. A Papyrus publication changes subject by
changing publication configuration, corpus set, category/graph steering state,
edition plans, and worker instructions.

To start a new publication from a pile of files, follow
[`docs/new-publication-from-corpus.md`](docs/new-publication-from-corpus.md).
That workflow defines the corpus accession shape, reference-prospect intake,
accepted-only analysis manifests, authoritative labels, topic granularity
profiles, and `analysis.reindex` assignment path used to bootstrap a knowledge
base from scratch.

## A Taxonomy-Aware, Ontology-Aware CMS

Papyrus is a CMS, but it manages the newsroom around the articles, not just the
articles themselves: references, knowledge artifacts, canonical topics,
ontology, assignments, drafts, published items, editions, and editorial
decisions.

The taxonomy layer decides what the publication covers. Newspaper sections are
a separate editorial configuration that defines the role a piece serves in the
issue (for example News vs History vs Methods). Papyrus stores an accepted, versioned category tree
as `CategorySet` + strict parent/child `Category` rows. Editors can accept,
reject, rename, move, split, merge, or ignore proposed topic changes; accepted
changes shape the publication, and rejected proposals become steering memory
for future cycles.

The ontology layer stores meaning, not just association. `Reference` records
hold strict external identifiers and provenance. `SemanticNode` records model
typed entities and concepts. `SemanticRelation` records preserve explicit,
versioned subject/object relationships, while seeded `SemanticRelationType`
records define official relationship keys, domains, inverse labels, and
context-pack tags. `SemanticRelation.predicate` remains a compatibility field;
new relation writers also denormalize `relationTypeId`, `relationTypeKey`, and
`relationDomain`. Together they let Papyrus track what a
thing is, what it refers to, how it relates to other things, and why it matters
to the publication.

Papyrus cultivates that model with human review plus aggregate, unsupervised,
and semi-supervised proposal cycles. Automated analysis can find patterns in
the knowledge base, propose topics, suggest ontology relationships, cluster
references, or identify weak sections. Editors can guide heavily, lightly, or
not at all for a while; the CMS keeps the accepted model stable and carries
rejected ideas forward as constraints.

That makes agent context richer than vector search alone. Instead of retrieving
only nearby text, research, editor, and reporter agents can receive context
packs with accepted taxonomy, steering decisions, citations and references,
related publication items, semantic neighbors, open assignments, and the
relationship paths that explain why something matters. The same model can power
reader-facing structure: coherent sections, source-grounded context,
related-article links, and navigation around emerging ideas.

The output is a real newspaper-style reader experience: a Next.js/React site
powered by [`@chenglou/pretext`](https://github.com/chenglou/pretext), with
planned front page teasers, exact continuation handoff, shared continuation
pages, and solver-owned editorial furniture such as images and pull quotes.
Pretext is the text-fit oracle. Papyrus owns the edition layout plan,
responsive grids, page regions, block geometry, scoring, continuation labels,
and React rendering.

## Newspaper layout, not web layout

Normal web layouts usually let text flow in a single article view. Newspapers do
something more complex:

- put several article starts on one front page;
- stop each article at a precise cutpoint;
- continue articles elsewhere without duplicating or skipping words;
- combine more than one article tail on a shared page;
- use photos, optional pull quotes, rules, and page furniture to balance short or long
  copy;
- keep the whole layout responsive.

Papyrus treats this as a deterministic layout-solving problem. It uses a
validated composable layout language rather than a fully open-ended optimizer:
an edition has pages, pages have regions, regions have blocks, and blocks can
own local grids and furniture. The solver turns those editorial instructions
into concrete geometry, then asks Pretext to measure exactly which lines fit
inside each solved block.

## Solver vs. Renderer

In a normal browser-first layout, React renders article markup and CSS gives the
browser constraints such as columns, width, floats, and line height. The browser
then decides the actual line breaks and element positions during layout. That is
great for ordinary article pages, but it makes newspaper continuations hard:
the app does not naturally know which exact word was last visible on page 1, or
where page 3 should resume.

Papyrus flips that responsibility. The solver runs before the newspaper page is
drawn. It takes articles, page width, viewport context, edition recipes, planned
continuation pages, and optional furniture candidates. It asks Pretext to fit
text into explicit boxes and around explicit obstacles. The solver then returns
the finished layout: page heights, story boxes, measured text lines, image and
pull-quote rectangles, continuation labels, and exact text cursors.

The renderer is deliberately simpler. `components/newspaper.tsx` and CSS draw
the solved result. They should not decide how many lines fit, where an article
continues, whether a pull quote fits, or how tall a page should be. If an object
changes the available copy area, it belongs in the solver first so Pretext can
measure text around it.

## Layout System Guide

The durable rules for the current design system are documented in
`docs/layout-system.md`. Read that guide before changing vertical rhythm,
masthead chrome, responsive front-page recipes, article-frame composition,
continuation height policy, furniture sufficiency, captions, the front footer,
or the archive grid.

## How It Works

Fixture articles still live in `lib/articles.ts`. They are the stable base for
tests and reproducible layout scenarios. Edge-case BDD fixture variants live in
`lib/layout-scenarios.ts`.

The app does not read any store directly from UI components. Content flows
through a `ContentRepository` boundary, which returns normalized
`EditionContent`: edition metadata, generic publication items, and a required
layout plan. The default content source is Amplify GraphQL in every environment.
URLs with `?scenario=<id>` load named fixture scenarios for BDD/debug only.

The GraphQL repository maps Amplify Data records into the same
`PublicationItem`, `ArticleImageAsset`, and `EditionContent` shape before
layout starts. Storage media is stored as S3 paths on `MediaAsset` records,
then resolved into signed display URLs at request time.

`buildNewspaperLayout` in `lib/newspaper-layout.ts` builds the active edition
from normalized publication items, the edition layout plan, the current page
width, and viewport height. It creates article flows, solves each page region,
solves each block, and returns generic solved pages for React to render.

Each article flow keeps a cursor into prepared Pretext text. When a block lays
out text, it consumes from the current cursor and returns a new cursor. That
range is recorded as a `PlacedTextRange`, which is the source of truth for
continuations.

The front page is now just a composable page using the `front.mosaic` preset
with `articleFrame` blocks. Those blocks still use solver-owned story boxes:
the solver measures each story's label, headline, deck, byline, body slot, and
continuation jump area so stories in the same row share the same rendered
height.

Continuation pages are planned before layout starts. The plan lives on the
Amplify `Edition.layoutPlan` record. It names page presets, regions,
blocks, local grid preferences, cut policies, jump targets, media placement
rules, pull-quote options, and content requirements. Page labels such as
`SEE READING ON A3` come from that plan, not from whatever page happens to be
generated next. Continuation headings use the article's `shortSlug` when it
exists, as in `READING FROM A1`; without one they fall back to `FROM A1`.

Article blocks try a bounded set of responsive local-grid and furniture
variants. The solver can inset aspect-preserving images into one or more
columns, place or omit optional pull quotes, change text column heights, and
then use Pretext to fit the remaining copy around the resulting obstacles. The
best valid variant is chosen deterministically. The stored plan controls
placement intent and constraints; TypeScript remains the source of truth for
how those constraints are solved.

`components/newspaper.tsx` renders the solved layout. It does not decide where
text cuts, how tall pages are, or which image variant wins. It receives placed
pages, blocks, lines, images, and CSS variables from the layout engine.

## Cloud Content

Papyrus includes an Amplify Gen2 backend in `amplify/`. The backend is defined
in TypeScript:

- Auth creates an `editor` group for seed/editor writes.
- Data exposes a general CMS model centered on `Item`, plus `Tag`,
  `MediaAsset`, `Edition`, and `EditionItem`.
- Storage keeps media in a private S3 bucket with guest read through Amplify
  Storage APIs and editor write/delete on `media/*`. The same Amplify bucket
  also owns private `corpora/*` prefixes for Biblicus corpus working data.

The first cloud media strategy uses signed Storage URLs, not raw public S3
object URLs. `MediaAsset.storagePath` is stable data. `GraphQLContentRepository`
calls Amplify Storage `getUrl` and injects temporary URLs into normalized
article image assets. Because signed URLs expire, GraphQL-backed pages render
dynamically.

The Data API is multi-auth. Public site reads use the API key from Amplify
outputs. Cognito user-pool auth remains available for future app/editor
surfaces. CLI authoring uses the separate Lambda authorizer, with
`PAPYRUS_GRAPHQL_JWT` sent directly to AppSync. Deploying that lane requires an
Amplify secret named `PAPYRUS_JWT_SECRET`; the authorizer also enforces the
configured issuer, audience, and scope values.

Cloud content is seeded from fixture content in `lib/articles.ts` and
`lib/layout-plan.ts`. The seed uploads article images to Storage and creates the
related CMS records. It does not create a CMS UI.

## Credentials

Use an AWS profile for AWS access. That is the right credential mechanism for
Amplify sandbox, deployment, and seeding from a local machine.

Papyrus already follows that split:

- AWS credentials come from the normal AWS SDK/CLI chain, usually
  `AWS_PROFILE` plus your local `~/.aws` config.
- App-level settings belong in `.env`.
- The seed script can still use Cognito editor credentials when seeding through
  Amplify Auth.
- The content CLI uses a direct bearer token in `PAPYRUS_GRAPHQL_JWT` for
  authoring requests. It does not log into a Papyrus user pool.

Papyrus has three distinct GraphQL auth lanes:

- the site reads GraphQL content with API-key auth;
- Cognito user-pool auth remains available for app/editor surfaces;
- the authoring CLI writes content with a JWT accepted by AppSync through the
  configured Lambda authorizer.

## Newsroom

`/newsroom` is the Papyrus newsroom operations workspace. `Topics` is the
taxonomy steering tab. `Sections` is the operational desk surface backed by
`NewsroomSection` doctrine and budgets. `Doctrine` is the publication-wide
mission and policies surface. The page is driven by the configured corpora for
the publication, not by hard-coded corpus names. Papyrus owns the human steering
state in GraphQL: knowledge corpora,
import runs, artifacts, accepted category sets, strict-tree categories, private
`Reference` metadata, private `SemanticRelation` links, proposals, and
append-only decisions.

Edition planning and assignment dispatch use first-class private `Assignment`
records, not `Item` rows with assignment types. Follow
[skills/edition-planning/SKILL.md](skills/edition-planning/SKILL.md) when
creating a dated edition, planning section slots, or dispatching surplus
candidate work. Follow
[skills/newsroom-story-cycle/SKILL.md](skills/newsroom-story-cycle/SKILL.md)
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
[skills/researcher-doctrine/SKILL.md](skills/researcher-doctrine/SKILL.md):
publication doctrine is the global editorial constitution, section doctrine is
the local desk standard, and the assignment brief is the immediate task.
Doctrine stays private and editable in Papyrus data; the skill defines how
agents apply it while gathering evidence and preparing research packets.
Coding agents that need to run the same assignment workflow outside a Tactus
procedure should use
[skills/newsroom-research-workflow/SKILL.md](skills/newsroom-research-workflow/SKILL.md).
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
[`docs/newsroom-worker-bootstrap.md`](docs/newsroom-worker-bootstrap.md).
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
editor/admin and JWT-authoring only; API-key reads are limited to the projection
tables. Publishing materializes approved current versions into projections, so
the reader path stays a direct AppSync read without a Lambda call.

Raw Biblicus steering payloads and import internals live in `KnowledgeRawPayload`,
which is private to editor/admin users and the JWT-authorized worker lane.
Actual corpus contents do not belong in GraphQL. `Reference` records store only
strict metadata such as Biblicus `item_id`, title, authors, source URI, S3/corpus
path, media type, checksum, dates, and sanitized provenance. Stable IDs such as
`category_key`, classifier ids, snapshot/artifact refs, corpus identity, and
category lineage ids are the API contract; display names are editable copy, not
keys. New knowledge-base source materials should follow
[skills/reference-intake/SKILL.md](skills/reference-intake/SKILL.md): register
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
[skills/researcher-doctrine/SKILL.md](skills/researcher-doctrine/SKILL.md) so
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

## Commands

```bash
npm run dev
npm run dev:127
npm run lint
npm run typecheck
npm run build
poetry install
poetry run papyrus --help
poetry run papyrus procedures execute-tactus 'return api_list{}'
poetry run python procedures/newsroom/tests/test_newsroom_tools.py
npm run sandbox
npm run seed:amplify
poetry run papyrus ops content inspect
poetry run papyrus ops categories import-config --config corpora/papyrus-steering.yml
poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml
poetry run papyrus ops categories import-steering --config corpora/papyrus-steering.yml --corpus-key <key>
poetry run papyrus ops categories import-steering --bundle <steering-export.json>
poetry run papyrus knowledge topics export-category-set --category-set <id> --output <accepted-category-set.json>
poetry run papyrus ops categories import-projection --config corpora/papyrus-steering.yml --target-corpus-key <key> --authority-corpus-key <key> --bundle <projection.json>
poetry run papyrus knowledge concepts import-types --config corpora/papyrus-semantic-relation-types.yml
poetry run papyrus knowledge concepts backfill --config corpora/papyrus-semantic-relation-types.yml
npm run test:bdd
npm run test:bdd:backend
npm run test:bdd:agent-live
```

## Internal knowledge base search

Accepted references, ontology, and graph neighbors are queried through one
shared engine (`knowledgeQuery`). Coding agents and newsroom procedures should
use it for **internal research** before web search or new reference intake.

Quick start (requires `PAPYRUS_GRAPHQL_ENDPOINT` and `PAPYRUS_GRAPHQL_JWT` in
`.env`; see `.env.example`):

```bash
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --query "specific question about accepted corpus knowledge" \
  --profile researcher \
  --format both \
  --max-tokens 1200
```

Full workflow, troubleshooting, and vector-index maintenance:
[`docs/internal-knowledge-research.md`](docs/internal-knowledge-research.md).
Query tuning and output shape:
[`skills/knowledge-query/SKILL.md`](skills/knowledge-query/SKILL.md).
Bounded multi-step researcher loops (ReAct-style) vs one-shot researchers:
[`docs/agent-loop-patterns.md`](docs/agent-loop-patterns.md).

## Python Newsroom Package

Papyrus now packages its Python newsroom tooling as the Poetry-managed
`papyrus` module.

Use Poetry as the canonical Python entrypoint:

```bash
poetry install
# Editable sibling ../Biblicus (entity extraction, HTML heuristics, graph NER dev):
./scripts/install-biblicus-local.sh
poetry run papyrus --help
poetry run papyrus assignments build-context --assignment <assignment-id>
poetry run papyrus procedures execute-tactus 'return api_list{}'
poetry run papyrus knowledge signals trend-report --corpus-key <key> --topic "<topic>" --sections culture,methods --json
poetry run papyrus editions plan --date YYYY-MM-DD --sections culture,methods --section-budgets culture:2,methods:1 --signal-report <signal-report.json> --json
poetry run papyrus assignments run-story-cycle --date YYYY-MM-DD --topic "<topic>" --category <category-key> --coverage-key <coverage.key> --sections culture,methods --section-budgets culture:2,methods:1 --through plan|research|reporting --json
poetry run papyrus assignments story-cycle-output --run-id <coverage-theme-run-id> --json
poetry run python procedures/newsroom/tests/test_newsroom_tools.py
```

Newsroom agents use the single-tool Tactus pattern from Plexus. Their Tactus
procedures load only `execute_tactus` from `procedures/newsroom/tactus_tools/`;
inside that tool, snippets use the packaged `papyrus` host module for GraphQL
reads, desk context assembly, Biblicus evidence, docs/API discovery, and dry-run
record-plan builders. The older compatibility shims under
`procedures/newsroom/tools/` still exist for path-based tooling, but the
canonical implementation now lives in `src/papyrus_newsroom/`.

Coverage Theme orchestration is Python-first. `signals trend-report` is the
assignment-desk signal feed, `editions plan` turns signals plus section slots
into private assignment graphs, `assignments run-story-cycle` advances that graph
through research or reporting packet creation, and `assignments story-cycle-output`
rediscovers the applied private state from GraphQL. The older
`poetry run papyrus assignments run-story-cycle` and
`assignments story-cycle-output` commands remain compatibility surfaces while
operators migrate.

Fresh external web research is a Tactus standard-library capability, not a
Papyrus adapter. Researcher and reporter snippets should use
`local web = require("tactus.web")` and then call `web.search{...}` or
`web.synthesize{...}` with `provider = "openai"` when the assignment context
requests current web evidence. Web results stay in private `research_packet` or
`reporting_context_packet` proposed-reference fields until reference intake
registers them; Papyrus does not write accepted evidence records directly from
web search.

Copy `.env.example` to `.env` when you need local overrides. `.env*` is ignored
by git, while `.env.example` is intentionally committed as the template.

`npm run test:bdd` runs the Gherkin layout scenarios against a running app. It
defaults to `http://127.0.0.1:3001`; set `PAPYRUS_BASE_URL` to test another
server.

`npm run test:bdd:backend` runs deterministic backend Behave features (Python)
and excludes live-agent scenarios.

`npm run test:bdd:agent-live` runs only the backend live-agent Gherkin smoke
suite via Behave (Python).
The live-agent suite is sandbox-only (`/Users/ryan/Projects/Papyrus` workspace)
and defaults the chat-agent model policy to `gpt-5-nano`.
Live scenarios persist tagged test records by default for dogfooding
(`behave-live-agent-*` prefixes); set `PAPYRUS_LIVE_AGENT_CLEANUP=1` to delete
records after each run.
`npm run test:bdd:agent-local` runs the same live-agent Behave scenarios but
invokes the local Rust console responder binary directly (no Lambda deploy).
This uses a dedicated local responder lane (`responseTarget=local`) so cloud
Lambda processing does not interfere with local runs, while still writing
Message rows through the configured GraphQL endpoint.
Use focused local loops for faster iteration:
`npm run test:bdd:agent-local:hello`, `:docs`, `:create`, `:get`, `:update`,
and `:error-shape`.
Before local/live agent runs, validate the reference action GraphQL contract
with `npm run check:reference-action-contract`.

In development, no query string means the live GraphQL edition. Use
`/?scenario=current-edition` or another named scenario id only when you need a
reproducible fixture layer for testing.

For Amplify development, run `npm run sandbox` to provision a local cloud
sandbox. After the sandbox has generated `amplify_outputs.json`, run
`npm run seed:amplify` to upload fixture content and media.

Seed content supports optional profiles so one Papyrus-based site can keep
custom fixture content without overwriting the base default fixture:

- Set `PAPYRUS_SEED_PROFILE=<profile-id>` before `npm run seed:amplify`
- Optional profile file path:
  `amplify/seed/profiles/<profile-id>/seed-edition-content.json`
- Fallback path (always available):
  `amplify/seed/seed-edition-content.json`

For content inspection and admin against a deployed API:

```bash
poetry run papyrus ops content inspect
poetry run papyrus ops content list articles
poetry run papyrus ops corpora worker-bootstrap --config corpora/papyrus-steering.yml --json
poetry run papyrus ops corpora status --config corpora/papyrus-steering.yml --corpus-key <key> --json
poetry run papyrus ops corpora sync-from-cloud --config corpora/papyrus-steering.yml --corpus-key <key> --dry-run
poetry run papyrus ops corpora sync-to-cloud --config corpora/papyrus-steering.yml --corpus-key <key> --dry-run
poetry run papyrus ops categories import-config --config corpora/papyrus-steering.yml
poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml
poetry run papyrus ops categories import-steering --config corpora/papyrus-steering.yml --corpus-key <key>
poetry run papyrus assignments research-packets --assignment <assignment-id>
poetry run papyrus knowledge signals trend-report --corpus-key <key> --topic "<topic>" --sections culture,methods --json
poetry run papyrus assignments run-story-cycle --date YYYY-MM-DD --topic "<topic>" --category <category-key> --coverage-key <coverage.key> --sections culture,methods --section-budgets culture:2,methods:1 --through reporting --json
poetry run papyrus assignments story-cycle-output --run-id <coverage-theme-run-id> --json
poetry run papyrus assignments run-story-cycle --date YYYY-MM-DD --topic "<topic>" --category <category-key> --coverage-key <coverage.key> --sections culture,methods,business,law --section-budgets culture:2,methods:1,business:1,law:1 --through plan|research|reporting [--refresh-packets] --json
poetry run papyrus assignments story-cycle-output --run-id <story-cycle-run-id> --json
poetry run papyrus assignments review-reporting-packet --assignment <assignment-id> --message <message-id> --decision select|merge|brief|hold|kill --note "<editor rationale>" --dry-run
poetry run papyrus assignments run-copywriting --assignment <copywriting-assignment-id> --dry-run --json
poetry run papyrus assignments copywriting-output --run-id <story-cycle-run-id> --json
poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json
poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --json
poetry run papyrus references register-catalog --config corpora/papyrus-steering.yml --corpus-key <key> --catalog <metadata/catalog.json> --status pending --ingestion-rationale "<summary, research focus, editorial mission fit>"
poetry run papyrus references export-analysis-manifest --config corpora/papyrus-steering.yml --corpus-key <key> --output accepted-reference-manifest.json
poetry run papyrus references export-scope-training --config corpora/papyrus-steering.yml --corpus-key <key> --output reference-scope-training.json
poetry run papyrus knowledge topics export-category-set --category-set <id> --output accepted-category-set.json
poetry run papyrus ops categories import-projection --config corpora/papyrus-steering.yml --target-corpus-key <key> --authority-corpus-key <key> --bundle projection-results.json
poetry run papyrus ops content delete all --yes
```

`references curate-recent` is assignment-only for re-curation operations:
Default apply mode dispatches `curation.reference-refresh` assignments and returns queue
status; it does not execute inline curation stages.

`references register-catalog` is the canonical bridge from corpus accession
files into Papyrus workflow state. In default apply mode, it creates a
`KnowledgeImportRun`, sanitized `KnowledgeRawPayload`, `Reference` and
`ReferenceAttachment` records, ingestion-rationale `Message` rows, workflow
`SemanticRelation` links, and one open `curation.reference-intake` `Assignment`
per pending reference. The filesystem catalog is not the queue after
registration; pending references and assignments are.

For routine reference curation, use the operator runbook:

1. `poetry run papyrus ops content inspect`
2. `poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json`
3. rerun without `--dry-run` once dry-run output looks correct.

Common curation command recipes:

```bash
# List candidate references (newest first)
poetry run papyrus references list --corpus-key <key> --status accepted --limit 25

# Curate one specific reference (dry-run)
poetry run papyrus references curate-recent --corpus-key <key> --reference <reference-lineage-id> --dry-run --json

# Curate a recent batch (dry-run)
poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json

# Curate all references in a corpus (dry-run; add to dispatch)
poetry run papyrus references curate-recent --corpus-key <key> --all --max-count 250 --dry-run --json
```

`references curate-recent` runs identifier prepass first, then title/subtitle,
summary, and quality in order. It writes resumable manifests under
`.papyrus-runs/reference-curation-<run-id>/manifest.json` and returns nonzero
when any reference fails so automation can detect degraded runs.
Reference subtitle display is canonical: the Newsroom UI shows `metadata.subtitle`
from the reference metadata attachment verbatim when present.

Knowledge search quick recipes:

```bash
# General semantic knowledge search
poetry run papyrus knowledge query --query "text classifier benchmarking" --max-tokens 600 --format both

# Desk-anchored semantic knowledge search (section/desk anchor)
poetry run papyrus knowledge query --query "AI in games" --anchor newsroomSection:technology --max-tokens 600 --format structured

# Build the exact desk-aware assignment agent context used by research/reporting
poetry run papyrus assignments build-assignment-agent-context --assignment-id <assignment-id> --max-tokens 4000 --recent-days 30
```

Set `PAPYRUS_GRAPHQL_ENDPOINT` and `PAPYRUS_GRAPHQL_JWT` before running
authoring commands. The JWT is sent in the AppSync `Authorization` header using
the Papyrus Lambda-authorizer scheme. No Papyrus editor login or local
auth-session cache is involved.

The CLI still contains legacy `diff` and `sync` commands for source-driven
publishing, but those commands require a local source adapter. The runtime no
longer has a committed `content/articles` Markdown store, so do not cite
`content sync edition current` as the production publishing path unless a
current source payload exists and has been validated.

`content delete all --yes` removes CMS records through the same
JWT/Lambda-authorizer authoring lane. Use it only for an explicitly requested
reset. Do not use it for production content refreshes.

For local cloud work, use an AWS profile, for example:

```bash
AWS_PROFILE=default AWS_REGION=us-east-1 npm run sandbox
AWS_PROFILE=default AWS_REGION=us-east-1 npm run seed:amplify
AWS_PROFILE=default npm run dev:127
```

## Local Dev 431 Troubleshooting

For Papyrus local workflows, prefer `http://127.0.0.1:3000` (run
`npm run dev:127`) instead of `localhost`. Browser cookies on `localhost` are
shared across local projects and can eventually trigger `HTTP 431` from an
oversized request header.

Quick diagnostic (no code changes):

```bash
curl -I -H "Cookie: x=$(python - <<'PY'\nprint('a'*20000)\nPY)" http://127.0.0.1:3000/newsroom/assignments
```

If that returns `431`, the error class is header-size/cookie bloat rather than
route logic.

## Newsroom Cloud Procedures Runbook

Papyrus newsroom procedures are cloud records (`ProcedureDefinition` and
`ProcedureVersion`) managed in `/newsroom` Administration under the
`Procedures` panel.

Source of truth for seeded procedure code:

- `procedures/newsroom/research_explorer.tac`
- `procedures/newsroom/reporter.tac`
- `procedures/newsroom/ingestion_reference_register.tac`

The seed process copies those files into `ProcedureVersion.tactusSource`:

- `amplify/seed/seed.ts` loads source files from `procedures/newsroom/`
- `npm run seed:amplify` upserts `ProcedureDefinition` + published v1
  `ProcedureVersion` rows

After editing local `.tac` files, reseed to refresh cloud procedure source:

```bash
AWS_PROFILE=<profile> AWS_REGION=<region> npm run seed:amplify -- --identifier <sandbox-id>
```

CLI cloud resolution contract:

- Required CLI procedure aliases are defined in
  `corpora/papyrus-required-procedures.json`
- `papyrus` resolves required procedure keys by alias, fetches
  cloud definitions by key, writes the selected `ProcedureVersion.tactusSource`
  into the run directory, executes that source with `tactus run`, and records
  the parsed output/error back on `ProcedureRun`
- If a required key is missing, CLI fails hard with explicit remediation:
  `Run npm run seed:amplify to preload standard procedures.`

Operator verification checklist:

1. Open `/newsroom` -> Administration -> Procedures.
2. Select a procedure row and verify `Version Draft -> Tactus/Lua Source`
   shows real code, not a placeholder.
3. Run `poetry run papyrus assignments run-research --assignment <id> ...` and
   confirm it resolves and runs the cloud procedure.
4. Inspect `.papyrus-runs/<run-id>/llm-context/summary.json` and
   `.papyrus-runs/<run-id>/llm-context/calls.jsonl` to verify the exact per-call
   LLM message history (including system prompt and user/tool messages) used during
   the agent run.
5. Use `.papyrus-runs/<run-id>/llm-context/execute_tactus_calls.jsonl` to verify
   tool-level context inputs (`assignment_context`, `assignment_agent_context`,
   `knowledge_query`, and any web calls) used during the run.

Current execution limitation (important):

- CLI-backed research/reporting runs execute cloud `ProcedureVersion.tactusSource`
  as user-editable Tactus code.
- Direct Lambda immediate execution still dispatches by procedure marker/key in
  `amplify/functions/assignment-action/handler.ts`; it does not yet execute
  arbitrary Tactus source inside Lambda.

## Production Content Operations

Production content lives in Amplify Data. The reader path uses API-key GraphQL
reads through `ContentRepository`; production writes and repairs should use the
JWT/Lambda-authorizer authoring lane or an explicit AWS-backed maintenance
script. Do not repair production by adding a runtime Markdown content source.

Production authoring uses the deployed AppSync API, not the sandbox:

```bash
export AWS_PROFILE=default
export AWS_REGION=us-east-1
export PAPYRUS_GRAPHQL_ENDPOINT=https://ur2anu47d5f67eq7sjzoqpyuze.appsync-api.us-east-1.amazonaws.com/graphql
export PAPYRUS_JWT_SECRET_SSM_PARAM=/amplify/d3on1y5vlrxmam/main-branch-aeb7dfa526/PAPYRUS_JWT_SECRET
```

Mint a fresh short-lived JWT from the production Amplify SSM secret:

The full production authoring and category/graph steering guide lives in the
agent skill at [skills/category-steering/SKILL.md](skills/category-steering/SKILL.md).

```bash
export PAPYRUS_GRAPHQL_JWT="$(npm run -s auth:refresh-jwt)"
```

Or write it directly into local `.env` for this workspace:

```bash
npm run auth:refresh-jwt -- --write-env .env
```

If your shell already exported an old `PAPYRUS_GRAPHQL_JWT`, refresh the active
shell value directly:

```bash
eval "$(npm run -s auth:refresh-jwt -- --format shell)"
```

Then verify the authoring lane before writing:

```bash
poetry run papyrus ops content inspect
poetry run papyrus ops content list articles
```

Treat `poetry run papyrus ops content inspect` as a hard preflight gate for live
CLI smoke runs. If it fails (for example `401 Unauthorized`), refresh JWT auth
first and do not continue with live write/read smoke commands.

For production content refreshes, use targeted GraphQL upserts. The safe pattern
is:

1. Dump or inspect `edition-current`, its `EditionItem` records, referenced
   `Item` records, media, and tags.
2. Generate a planned diff before mutations.
3. Confirm the diff targets only `edition-current` and the intended
   `Item`, `Tag`, `ItemTag`, `EditionItem`, and `MediaAsset` records.
4. Apply only targeted upserts/deletes. Do not run `npm run seed:amplify`, do
   not run sandbox provisioning, and do not run `content delete all --yes`.
5. Re-run `content list articles` and smoke-check the deployed site.

Sections are editor-configured newsroom objects, not inferred taxonomy labels.
When publishing an edition, set `Item.section`, `Tag.label`, and
`ItemTag.tagSlug` to the configured editorial sections chosen for that issue.

If the deployed production code is older than the local layout-plan schema, a
newer `Edition.layoutPlan` can make production return `500` during layout-plan
validation. Prefer deploying the current app before publishing advanced
layout-plan fields. If production must be restored without a deploy, make a
targeted compatibility repair to `edition-current.layoutPlan`, then re-smoke the
site and document exactly which fields were removed.

The production archive has one important invariant: a published edition must
have all of these fields set:

- `Edition.status = "published"`
- `Edition.editionDate`, for canonical date routes such as `/2026/may/13`
- `Edition.publishedAt`, for archive listing and freshness sort order

If the home page or a date route can load an edition but `/archive` says
`No published editions are available yet`, check `publishedAt` first. The
archive API lists editions through the `status + publishedAt` index, so records
created before that field was populated can be published and still absent from
the archive. Backfill the edition with a stable timestamp such as
`2026-05-13T12:00:00.000Z`, then verify the archive endpoint returns at least
one preview:

```bash
curl -sS "$PAPYRUS_BASE_URL/api/archive/editions?limit=1"
```

For local sandbox content, use `npm run seed:amplify`. That seed path uses
fixture content and Cognito editor credentials, uploads media to Storage, and
sets `publishedAt` on the seeded edition. Treat it as a sandbox/dev workflow,
not as an implicit production publish command.

## Layout Scenario Tests

Executable BDD scenarios live in `features/*.feature`. They describe newspaper
layout behaviors in durable product language: open a named scenario at a
viewport size, flip to a page, and assert outcomes such as no cropped measured
lines, no furniture overlap, no dead continuation columns, and a specific image
template winning.

Scenario URLs such as `/?scenario=shared-blank-column-pressure` select named
fixture content through the same content repository boundary used by the app.
They are not a renderer-side bypass.

Do not put BDD scenario fixtures in production content records. Test scenarios
belong in `lib/layout-scenarios.ts` so they remain deliberate, reproducible
examples.

The step definitions use Playwright to inspect both rendered DOM rectangles and
the solved layout exposed as `window.__PAPYRUS_LAYOUT__`. That lets a scenario
check the visible page and the solver decision without encoding rectangle math
inside the feature file.

## Important Files

- `docs/layout-system.md` explains the current layout-system invariants:
  vertical rhythm, mastheads, responsive front recipes, article composition,
  continuations, height policy, furniture, captions, footer, and archive.
- `lib/articles.ts` contains fixture article data, image asset metadata, and
  helpers for article text and image assets.
- `lib/content-repository.ts` loads GraphQL content by default and supports
  `?scenario=<id>` overrides for BDD/debug fixtures.
- `lib/graphql-content-repository.ts` loads Amplify Data records, resolves
  Storage paths to signed URLs, and normalizes cloud content into
  `PublicationItem` objects.
- `amplify/` defines the Gen2 Auth, Data, Storage, and seed resources for the
  cloud content backend.
- `papyrus` is the JWT-backed content authoring CLI for
  GraphQL inspect/list/diff/sync workflows.
- `lib/content-types.ts` defines `EditionContent` and `ContentRepository`.
- `lib/publication-items.ts` defines generic publication items and article
  adapters used by the solver and direct article routes.
- `lib/layout-scenarios.ts` contains reproducible layout scenario fixture sets
  used by the app and BDD tests.
- `lib/layout-plan.ts` defines and validates the Zod-backed composable layout
  language: pages, regions, blocks, responsive spans, media placement, pull
  quote placement, and content requirements.
- `lib/newspaper-layout.ts` owns the Pretext layout engine, responsive page
  grids, region/block solving, placed text ranges, adaptive furniture, and
  solved page heights.
- `components/newspaper.tsx` renders the solved newspaper scroll edition,
  measured text lines, continuation photos, and direct article links.
- `features/` contains executable Gherkin scenarios and Playwright-backed step
  definitions for layout behavior.
- `app/articles/[slug]/page.tsx` renders full direct article pages.
- `app/globals.css` contains the newspaper visual language and the CSS variables
  consumed from solver output.

Pretext measurement depends on browser canvas APIs, so the newspaper layout is
computed after client hydration. The server-rendered shell is intentionally
minimal.
