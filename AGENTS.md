# AGENTS.md

This file is the operating manual for AI agents maintaining Papyrus. Read it
before changing the layout engine, renderer, fixture data, or publication model.

## Project Purpose

Papyrus is a Next.js/React newspaper layout lab using `@chenglou/pretext` for
precise text fitting. The goal is not just to render articles. The goal is to
experiment with a reusable design language for newspaper-style publications:
front-page teasers, planned continuation pages, shared article tails, adaptive
solver-owned furniture, and exact word-for-word continuation handoff.

Papyrus is also intended to be a general-purpose automated newsroom. The current
AI/ML corpus and edition content are pilot configuration, not product-specific
code. A Papyrus deployment should be able to publish about any area of interest
by changing corpus configuration, steering state, publication instructions,
research-agent instructions, and edition plans. Do not bake a subject area,
corpus name, classifier id, or content category into application logic.

Pretext owns text measurement. Papyrus owns everything around that measurement:
edition layout plans, responsive page grids, regions, block geometry, cut
policies, page heights, furniture variants, scoring, continuation labels, and
rendering contracts.

## Continuous integration on `develop` (promote to `main`)

- **`develop` on GitHub (`AnthusAI/Threat-Intelligence`) is the integration
  branch.** Feature work should land on `develop` first.
- **`main` is the release/production branch.** Promote reviewed integration work
  with `develop -> main` PRs.
- Keep integration and release state explicit: report whether a change has
  landed in `develop`, whether a `develop -> main` PR exists, and whether it has
  merged.

## Core Rules

- Before running any AWS-, Amplify-, sandbox-, or deployment-related command,
  read `AGENTS.local.md` and follow its local account/profile/env guidance.
  Treat `AGENTS.local.md` as required preflight context for cloud operations on
  this machine.
- Papyrus is an Amplify Gen 2 project. Production backend/frontend deployment is
  done from `main` through the configured DevOps/Amplify pipeline. Do not run
  `ampx pipeline-deploy` (or other direct production `ampx` deploy commands)
  from local agents unless the user explicitly asks for that exact override. Use
  `ampx` locally for sandbox workflows only.
- Do not commit unless the user explicitly asks.
- Preserve unrelated uncommitted work. This project is often dirty because it is
  being iterated in conversation.
- Papyrus is Python-first for backend workflows. Create new backend utilities,
  CLIs, automation, API tests, and backend BDD harnesses in Python by default.
  Use JavaScript/TypeScript only for the Next.js/React frontend and
  frontend-specific test harnesses.
- Do not add backward-compatibility fallbacks for old schema, GraphQL, content,
  layout-plan, or CLI shapes. See
  [Schema and API alignment (no compatibility shims)](#schema-and-api-alignment-no-compatibility-shims).
- Default to clean breaks. Do not add fallback behavior unless the user
  explicitly requests it.
- Keep the current one-page React flipper. Do not reintroduce Turn.js, jQuery,
  or DOM-mutating layout loops.
- Do not make React measure rendered DOM to decide layout. The solver should
  decide geometry before render using shared tokens and Pretext.
- Do not use CSS line clamping for measured article copy. Text lines must come
  from Pretext.
- Every rendered measured line must be vertically all-or-nothing. A line should
  not appear unless its full paint box fits inside the clipped text area.
- Continuation routing is planned, not emergent. Page labels must come from the
  edition plan. Front-page jump labels should read like `SEE READING ON A3`,
  and continuation headings should read like `READING FROM A1`. If an article
  has no `shortSlug`, use `MORE` in the jump label and omit the slug in the
  continuation heading, for example `SEE MORE ON A2` and `FROM A1`.
- Exact cursor handoff matters. Never duplicate or skip article text between
  front-page excerpts and continuation pages.
- Headline scale is an editorial token, not a CSS tweak or a side effect of
  block order. Use canonical `typography.headlineScale` names: `banner`,
  `feature`, `standard`, `rail`, and `brief`.
- Use Papyrus's canonical newspaper vocabulary when discussing layout changes
  with users and other agents. Prefer phrases like `feature headline`,
  `rail headline`, `articleFrame composition`, `local grid`, `media inset`,
  `planned continuation`, and `solver-owned furniture` over generic wording
  like "make it bigger" or "move the image around."
- Keep cloud content behind `ContentRepository`. Amplify, GraphQL, and Storage
  types must not leak into `lib/newspaper-layout.ts`.
- Do not make the S3 bucket raw-public. Use Amplify Storage access rules and
  signed `getUrl` URLs for reader media unless the architecture is explicitly
  changed.
- The production Amplify Storage bucket also owns private `corpora/*` prefixes
  for Biblicus corpus working data. Treat S3 as the durable corpus source of
  truth, and local `corpora/` symlinks as working copies only.
- `corpora/papyrus-steering.yml` is the tracked steering config contract. It
  defines publication corpus keys, roles, classifier ids, local paths, and S3
  prefixes. Do not hard-code the AI/ML pilot corpus names in Papyrus logic.
  Materialize config changes with `poetry run papyrus ops categories import-config`.
- Research agents should be driven by editable publication doctrine, section
  doctrine, publication/corpus config, accepted category state, and assignment
  context, not by hard-coded subject assumptions. Follow
  `skills/researcher-doctrine/SKILL.md` when designing or running researcher
  behavior. Keep domain-specific guidance in doctrine/config data and do not add
  domain assumptions to `/newsroom`, the content CLI, GraphQL models, or layout
  code.
- Coding agents that operate research, reporting, or story-cycle workflows
  should follow `skills/newsroom-research-workflow/SKILL.md` and
  `skills/newsroom-story-cycle/SKILL.md`. Live Assignment packets are private
  `Message` work products with `ModelAttachment` payloads; they are not files,
  folders, publication `Item` rows, or new top-level models. New packet writes
  use `Assignment --produces--> Message`; legacy
  `Message --comment--> Assignment` packet links remain readable. Inspect
  research packets with
  `poetry run papyrus assignments research-packets --assignment <id>`, and use
  `assignments story-cycle-output` for run-level research/reporting output.
- Use an AWS profile for local Amplify/AWS access.
- `.env` is for Papyrus runtime settings and the seed editor credentials used by
  `npm run seed:amplify`. `.env*` must stay ignored, and `.env.example` is the
  committed template.
- **GraphQL auth split (do not mix):**
  - **CLI and other non-Lambda tools** use `PAPYRUS_GRAPHQL_ENDPOINT` plus
    `PAPYRUS_GRAPHQL_JWT` (minted via `poetry run papyrus auth refresh-jwt`).
    That JWT is sent to AppSync through the **Lambda JWT authorizer** lane only.
    Do not add a Papyrus editor login flow or local auth-session cache for CLI publishing.
  - **Deployed Lambda functions** call AppSync with **IAM only** (SigV4 /
    `authMode: "iam"` on the Amplify data client). Do not mint JWTs, do not set
    `PAPYRUS_JWT_SECRET` on Lambdas, and do not add alternate GraphQL auth paths
    inside Lambda code. Grant access with `allow.resource(<function>)` on the
    data schema and `appsync:GraphQL` on the function role.
- Production authoring uses the deployed production AppSync endpoint, not the
  sandbox. Mint short-lived production JWTs from the Amplify SSM
  `PAPYRUS_JWT_SECRET`; do not write production secrets or freshly minted
  production JWTs into `.env`. Follow `skills/category-steering/SKILL.md` for
  the exact token minting and category/graph steering import workflow.
- Category and graph steering imports must not mirror Biblicus corpus contents
  into Papyrus GraphQL. Papyrus stores steering state, artifact references,
  category copy, proposals, decisions, strict private `Reference` metadata,
  private `ReferenceAttachment` file-path metadata, private append-only
  `Message` commentary, `SemanticNode` rows, `SemanticRelation` links,
  and stable external `item_id` references; Biblicus and S3 remain the owners of
  corpus content. Follow `skills/reference-intake/SKILL.md` for ingesting or
  registering new knowledge-base source materials correctly.
- Research packet `proposedReferences` are source-material prospects for
  reference intake, not accepted evidence. Register them through
  `references register-catalog` or the repeatable Biblicus corpus path before
  curation or evidence use. Only current accepted `Reference` rows may be used
  for evidence sets, topic modeling, graph analysis, desk memory, context
  packs, assignment evidence, or edition planning.
- For **internal knowledge base search** (accepted references, semantic + graph
  context packs), read `docs/internal-knowledge-research.md` first, then
  `skills/knowledge-query/SKILL.md`. Run queries with
  `PYTHONPATH=src python -m papyrus_newsroom knowledge-query` or
  `poetry run papyrus-newsroom knowledge-query` (not ad-hoc GraphQL). Use
  `--execution local` only when developing engine behavior; default remote
  execution needs `PAPYRUS_GRAPHQL_ENDPOINT` and `PAPYRUS_GRAPHQL_JWT`.
  `knowledgeQuery` is the shared CLI/Lambda path; prefer local CLI iteration
  for context-pack content changes and deploy only when ready for AppSync.
- Bounded exploratory researcher loops vs one-shot researchers are documented in
  `docs/agent-loop-patterns.md` (`research_explorer.tac` vs `researcher.tac`).
  “Ralph loop” is an external host-loop pattern; this repo does not implement it.
- When bootstrapping a new publication from a file pile, follow
  `skills/publication-bootstrap/SKILL.md` and
  `docs/new-publication-from-corpus.md`. Convert loose files into a corpus
  accession with stable item ids, sidecars, and `metadata/catalog.json`; then
  register reference prospects, curate accepted references, export
  accepted-only Biblicus manifests, and create `analysis.reindex` assignments
  instead of hard-coding topic lists or running mixed-status corpora through
  analysis.
- The Newsroom is the newsroom operations surface. `Topics` is one desk tab,
  not the whole product concept. Use `/newsroom` and Newsroom naming in UI,
  docs, and tests. Future assignment and research queues should become desk tabs
  instead of separate one-off management pages.
- `/newsroom/doctrine` manages publication-wide mission and policies.
  `/newsroom/sections` manages the operational desk surface through
  `NewsroomSection` mission, policies, assignment guidance, kill criteria, and
  budgets. Legacy category-tied desk doctrine may still exist for migration, but
  new assignment context should prefer section doctrine.
- Assignments are first-class private `Assignment` work records, not cloud
  `Item` rows with `type: "assignment"`. Do not create assignment Items or
  encode pending work in article/item status fields.
- Assignments are generalized newsroom tasks for humans, agents, and
  procedures. Relate them to `Reference`, `Item`, `Category`, `CategorySet`,
  `SemanticNode`, `SemanticRelation`, `Message`, `SteeringProposal`,
  and future models through `SemanticRelation` links such as
  `requests_work_on`, `uses_evidence`, `produces`, `blocked_by`, and
  `derived_from`.
- Official semantic relationship metadata lives in `SemanticRelationType`
  records seeded from `corpora/papyrus-semantic-relation-types.yml`.
  `SemanticRelation.predicate` remains required for v1 compatibility and
  indexes, but new relation writes must also set `relationTypeId`,
  `relationTypeKey`, and `relationDomain` by resolving the seeded type. Use
  `poetry run papyrus knowledge concepts import-types --config corpora/papyrus-semantic-relation-types.yml`
  after schema deploy, then `poetry run papyrus knowledge concepts backfill --config corpora/papyrus-semantic-relation-types.yml`
  to denormalize existing relation rows.
- Assignment lifecycle changes use protected actions or the JWT authoring lane
  and append `AssignmentEvent` audit rows. The Newsroom `Assignments` tab
  should show claim/release/complete/cancel/reopen workflow actions, not
  edition-candidate culling.
- Editorial selection is separate from assignment lifecycle. Reporting packet
  decisions use `AssignmentEvent.eventType` values
  `reporting_select`, `reporting_merge`, `reporting_brief`, `reporting_hold`,
  and `reporting_kill`, with structured metadata in a `ModelAttachment` owned by
  the event. `select` and `brief` create child private copywriting Assignments
  (`copywriting.article-draft` or `copywriting.brief-draft`), not `Item` rows.
  `hold` and `kill` create no Items; no reporting packet review creates
  `EditionItem` placement.
- For dated edition setup, section slot planning, and surplus research
  and reporting assignment dispatch, follow `skills/edition-planning/SKILL.md`
  and `skills/newsroom-story-cycle/SKILL.md`. The default
  overassignment ratio is `3/2`, but assignments remain private `Assignment`
  records. Create or update the dated private `Edition` record first, then
  dispatch by configurable `NewsroomSection`, accepted topic scope, coverage
  `SemanticNode`, and publication lane (`reporting`, `analysis`, and `briefs`
  by default). Link assignments to that edition, section, lane, topic, coverage
  node, lineage source, and evidence with `SemanticRelation` rows. Reporting
  agents produce private context packets first; explicit editor `select`/`brief`
  decisions queue copywriting Assignments; copywriting is the first stage allowed
  to create draft reader-facing `Item` records. Edition placement remains a
  later copyediting/layout step.
- EditionSlot orchestration guardrails:
  - planning/dispatch agents should start with
    `skills/edition-planning/SKILL.md`;
  - run/review agents should start with
    `skills/newsroom-story-cycle/SKILL.md`;
  - the canonical slot data contract and decision matrix lives in
    `docs/automated-publication-research-workflow.md`;
  - reporting assignment dispatch must bind slots via `slotTarget` metadata and
    `Assignment --targets_slot--> EditionSlot`;
  - reporting review must not create `EditionItem`; `select`/`brief` may set
    slot winner state and queue copywriting assignments only.
- Edition forum-thread guardrails:
  - Coverage Theme planning posts **three messages** on `edition_forum` in order:
    theme (phase 1), optional desk (phase 2), reporting dispatch (phase 3);
    see `skills/edition-planning/SKILL.md` and
    `docs/automated-publication-research-workflow.md`;
  - use `MessageThread` forum kinds `edition_forum` and `section_forum`;
  - anchor edition threads to `Edition` and section threads to
    `(NewsroomSection, edition lineage)`;
  - assignment context should include edition forum first, then same-section
    forum threads only when present;
  - do not leak other sections' forum threads into assignment context;
  - reporting/review still must not create `EditionItem`.
- Treat multi-section story-cycle runs as Coverage Themes in editor-facing UX
  and docs. The Python `papyrus assignments run-story-cycle` command is the
  primary operator surface. The default stop point is `--through reporting`, after private
  research and reporting packets but before editor selection or copywriting. Use
  `--through plan` or `--through research` when intentionally stopping earlier.
  Applied reruns reuse existing packet Messages by default; use
  `--refresh-packets` only when the operator intentionally wants to regenerate
  packet payloads.
  In live apply smoke tests, require agent success unless fallback/degraded
  packets are explicitly being tested.
- Use `papyrus knowledge signals trend-report` and `papyrus editions
  plan` as the Python assignment-desk layer when an edition should be planned
  from recent accepted knowledge-base trends, section slots, and Coverage Theme
  candidates.
- Style the Newsroom as a newspaper section or editorial insert, not as an app
  dashboard. Steering is passive and optional: proposals are skimmable notes
  beside the edition, and the system keeps following the accepted category set when
  humans provide no new steering.
- Accepted categories have a small first-class typed surface for editor-only
  Newsroom views and appendix pages: versioned `CategorySet` and strict-tree
  `Category` rows. Import accepted taxonomy artifacts into those tables, keep
  full manifests in private `KnowledgeRawPayload`, and append passive Newsroom
  category-register pages to editions only for signed-in editor/admin readers.
  Accepted graph and ontology artifacts may materialize private `SemanticNode`
  and `SemanticRelation` rows for direct Newsroom and procedure queries.
  Biblicus recommendation labels such as `recommend`, `do_not_recommend`, and
  `needs_clarification` are agent labels, not Papyrus review actions.
- Rejected steering proposals are not cosmetic. Export Papyrus review memory
  with `poetry run papyrus ops categories export-steering-feedback --category-set <id> --output <feedback.json>`
  before new taxonomy, ontology, or graph proposal cycles. Accepted category-tree
  exports say what is accepted; steering-feedback exports say what editors
  accepted or rejected and include suppressions. Pass that file to
  `biblicus taxonomy discover` and `biblicus steering graph-signals` with
  `--steering-feedback` so Biblicus avoids re-proposing rejected child topics,
  labels, relationships, or weak patterns.
- Lexical steering is private editorial steering. `CategoryKeyword` rows expose
  keyword evidence for categories in the Newsroom, and `LexicalSteeringRule`
  rows capture ignored terms such as citation/header noise. Seed defaults live
  in `corpora/papyrus-lexical-steering.yml`; export active rules with
  `poetry run papyrus ops categories export-lexical-steering --output <lexical-steering.json>`.
  Do not assume Biblicus consumes that export until the Biblicus agent confirms
  the command contract.

## Schema and API alignment (no compatibility shims)

Local application code and the deployed GraphQL API must describe the same contract.
When CLI or Lambda code fails because a field, model, or input type is missing on
AppSync, that is a **deployment error** — not a signal to add adaptation logic in
Python or TypeScript.

**Do not fix schema drift in code. Fix the deployment.**

### Forbidden (unless the user explicitly approves a temporary emergency repair)

- Runtime schema introspection that **filters** queries or mutations to match
  whatever the remote API currently exposes (for example: dropping undeployed
  fields from `listReferences`, or stripping keys from `CreateReferenceInput`
  before send).
- Fallback read queries with reduced field sets for "older" APIs.
- Dual-shape normalizers that accept both old and new schema shapes.
- Silent `try/except` branches that continue with partial or degraded behavior
  when the API contract does not match code.
- Any logic whose purpose is "make the CLI work against a sandbox that hasn't
  caught up yet." That sandbox will catch up once; the shim stays forever.

These patterns look small at first. They become permanent branches every agent
and every future feature must reason about. **One hour of deployment lag is not
worth years of compatibility debt.**

### Required response when code and deployed schema disagree

1. Confirm local schema in [`amplify/data/resource.ts`](amplify/data/resource.ts)
   (or the relevant Amplify resource) is what code expects.
2. Deploy it to the target environment:
   - **Sandbox:** `npx ampx sandbox` (wait for deploy to finish), then
     `npm run outputs:sandbox` if needed.
   - **Production:** use the normal pipeline; do not patch around prod drift
     from local agents.
3. Re-run the failing CLI command. It should succeed against the updated API or
   fail with a real data/logic error — not a field-undefined validation error.

Do **not** weaken the CLI client, GraphQL authoring layer, or newsroom tools to
paper over an outdated AppSync schema.

### Temporary emergency repairs

Only when the user **explicitly approves** restoring production immediately:

- Keep the repair as narrow as possible (one command, one model, one migration).
- Document exactly why it exists and when it must be removed.
- Remove it from normal read, authoring, repository, and solver paths as soon
  as deployment or data is corrected.

Default is **clean breaks**: fail loudly, deploy schema, move on.

### Concrete anti-pattern (do not repeat)

During Threat Intelligence bootstrap, sandbox AppSync was missing
`Reference.inboundCitationCount`, `Reference.reviewedFeedKey`, and related
fields that already existed in local schema. The wrong fix was adding
`_resolved_fields()` and runtime mutation input filtering in
`src/papyrus_content/graphql_authoring.py`. The right fix was deploying sandbox
schema, then re-running `references create-from-catalog`.

## Solver vs. Renderer Boundary

The newspaper pages are not browser-flow layouts. They are solved layouts that
React renders.

The solver lives in `lib/newspaper-layout.ts`. It owns:

- responsive page grids, regions, local block grids, and continuation routing;
- story box, block, column, page, and furniture geometry;
- every call to Pretext and every measured `TextLine`;
- text cursors and `PlacedTextRange` handoff;
- candidate generation and scoring for images, pull quotes, and other adaptive
  furniture;
- the final page heights and renderer contracts.

The renderer lives mostly in `components/newspaper.tsx` and `app/globals.css`.
It owns:

- mapping solved objects to markup;
- passing solver values through CSS variables or inline dimensions;
- visual styling, page flipping, links, and interaction chrome;
- clipping already-solved text lines inside their solved containers.

Do not move layout decisions into React effects, DOM reads, CSS line clamps,
`getBoundingClientRect()` loops, or browser-native column balancing for the
newspaper pages. Browser layout can style the solved objects, but it should not
decide which article words are visible. If a visual element changes available
copy space, add it to the solver contract as geometry before `layoutTextLines`
runs.

## Main Data Contracts

`lib/articles.ts` owns fixture content:

- `Article` is the editorial source: slug, optional newspaper `shortSlug`,
  section, headline, deck, byline, dateline, primary image, optional reusable
  assets, pull quotes, and body.
- `ArticleImageAsset` is the reusable image model for adaptive page furniture.
- `getArticleText(article)` returns the text stream Pretext consumes.
- `getArticleImageAssets(article)` returns explicit image assets when present,
  or adapts the legacy `article.image` into a continuation-capable asset.
- Keep fixture articles here for reproducible tests and scenario generation.

Papyrus no longer uses a local Markdown content store. Do not add back a
`content/articles/` runtime source. Edition content should come from Amplify
GraphQL (or `?scenario=<id>` fixture overrides for tests/debug only).

`lib/publication-items.ts` owns the generic publication model:

- `PublicationItem` is the normalized item union consumed by the layout solver.
- Supported item types are `article`, `brief`, `correction`, `promo`, `ad`,
  and `sectionHeader`.
- Assignments are not `PublicationItem`s and should not appear in reader
  layout. Keep research and reporting output as private `Assignment` work
  products. Explicit editor selection queues private copywriting Assignments;
  copywriting creates draft `article` or `brief` `Item` records for review.
  Draft creation is not edition placement.
- `articleToPublicationItem` adapts legacy/fixture `Article` objects into
  generic items.
- `publicationItemToArticle` adapts article items back to `Article` for direct
  `/articles/[slug]` routes.
- `getPublicationItemText` and `getPublicationItemImageAssets` are the solver
  helpers for item text streams and reusable media assets.

`lib/content-types.ts` and `lib/content-repository.ts` own the content boundary:

- `EditionContent` is the normalized app input: edition metadata plus
  `PublicationItem[]` and a required `EditionLayoutPlan`.
- `ContentRepository` is the source abstraction for loading edition content,
  resolving one article by slug, and listing article slugs.
- The current repository uses Amplify GraphQL by default and named scenario
  content only when `?scenario=<id>` is present.
- `?scenario=<id>` always selects named scenario content from
  `lib/layout-scenarios.ts`.
- Amplify Data is loaded through `lib/graphql-content-repository.ts`.
- UI routes should use the repository boundary, not import fixture arrays
  directly.

`lib/graphql-content-repository.ts` owns cloud normalization:

- It loads the active `Edition`, its `EditionItem` placements, attached `Item`
  records, and `MediaAsset` records from Amplify Data.
- It resolves `MediaAsset.storagePath` to temporary signed URLs with Amplify
  Storage `getUrl`.
- It never persists signed URLs back into GraphQL. Store stable paths and media
  metadata in Data; generate signed URLs at request time.
- It maps cloud records into `PublicationItem`, `ArticleImageAsset`, and
  `EditionContent`.
- Routes that use GraphQL content must stay dynamic because signed media URLs
  expire.
- Archive listing depends on published editions having both `editionDate` and
  non-null `publishedAt`; if `/archive` is empty while a date route works,
  inspect and backfill `Edition.publishedAt` before changing the renderer.
- The read path does not require a hand-managed token in `.env`. It uses
  `amplify_outputs.json` plus Amplify runtime configuration.
- The public read path should keep using `authMode: "apiKey"` even though the
  API default authorization mode is `userPool`.

`amplify/` owns the cloud backend:

- `amplify/auth/resource.ts` defines email auth and the `editor` group.
- `amplify/data/resource.ts` defines the CMS model: `Item`, `Tag`, `ItemTag`,
  `MediaAsset`, `Edition`, and `EditionItem`.
- `amplify/storage/resource.ts` defines private S3-backed media storage with
  guest read and editor write/delete access on `media/*`.
- `amplify/seed/seed.ts` seeds the sandbox from fixture content, uploads images,
  and upserts CMS records.
- `amplify_outputs.json` is generated output and must stay ignored.
- Do not put BDD fixtures in production content records.
- Local sandbox, seed, and deploy operations should use the caller's AWS
  profile, typically via `AWS_PROFILE` and `AWS_REGION`.
- `amplify/seed/seed.ts` signs into Cognito as the seed editor using
  `PAPYRUS_SEED_USERNAME`, `PAPYRUS_SEED_PASSWORD`, and
  `PAPYRUS_SEED_EMAIL`. Those belong in `.env`, not in source control.
- The data API supports public API-key reads, Cognito user-pool auth, **IAM for
  registered Lambda functions** (`allow.resource(...)`), and a separate **JWT
  authorizer lane for CLI/tools only**. Match the intended `../Plexus/dashboard` shape:
  public API-key access stays available, Cognito remains available, and CLI clients
  send a direct JWT through the AppSync Lambda-authorizer auth scheme.
- The JWT authorizer (`graphql-jwt-authorizer`) and Amplify secret
  `PAPYRUS_JWT_SECRET` are for **CLI authoring only**, not for inbound email,
  console chat, knowledge query, or other Lambdas.

`src/papyrus_content` owns the content authoring CLI:

- `poetry run papyrus` is the canonical backend CLI surfaced by
  the `papyrus` command groups.
- The CLI is GraphQL authoring and inspection.
- `src/papyrus_content/graphql_authoring.py` owns GraphQL authoring calls: JWT
  when run from the CLI; IAM automatically when `AWS_LAMBDA_FUNCTION_NAME` is set.
- `graphql_authoring.py` uses **fixed** query field lists and explicit input
  shaping. Do not add runtime schema introspection to adapt to undeployed fields.
  See [Schema and API alignment (no compatibility shims)](#schema-and-api-alignment-no-compatibility-shims).
- `content inspect`, `content list`, and `content delete all --yes` are the
  stable deployed-API operations. `content diff` and `content sync` are
  source-driven publishing commands; do not use them as a production runbook
  unless the current source adapter and source payload exist.
- Production content refreshes should be targeted GraphQL upserts/deletes after
  an explicit planned diff. Do not run sandbox seed, sandbox provisioning, or
  `content delete all --yes` for a production refresh unless the user explicitly
  asks for that destructive reset.
- In the current CLI authoring path, media assets must use external URLs. Do
  not add half-working direct S3 uploads without also introducing an
  authenticated Storage strategy that matches the chosen credentials model.
- The CLI should expose `inspect`, `list`, `diff`, `sync`, and explicit
  `content delete all --yes`; it also owns `categories import-config`,
  `categories import-steering`, `categories export-category-set`, and
  `categories import-projection` for category, reference, and graph steering.
  Do not add `content login` or `content logout` unless the auth model changes
  again.

`lib/layout-plan.ts` owns the edition layout-plan contract:

- `EditionLayoutPlan` is stored with edition content as editorial intent, not
  solved geometry.
- Amplify stores this shape on `Edition.layoutPlan`.
- The plan is composable: `pages[]` contain `regions[]`, and regions contain
  typed `blocks[]`.
- Page presets currently include `front.mosaic`, `page.regionStack`,
  `page.railMain`, and `page.full`.
- Region types currently include `stack`, `split`, `railMain`, `strip`, and
  `fullPage`.
- Block types currently include `articleFrame`, `itemFrame`, `mediaCluster`,
  `itemStack`, `promoStrip`, `adBlock`, `rule`, and `masthead`.
- `articleFrame` presets currently include `front.teaser`,
  `article.standard`, `article.mediaInset`, and `article.mediaPrelude`.
- Media placement uses responsive intent: anchor, span range, vertical
  placement, collapse policy, crop policy, and wrap behavior.
- `articleFrame.typography.headlineScale` names the headline treatment with
  canonical newspaper terms: `banner`, `feature`, `standard`, `rail`, or
  `brief`. Do not infer headline scale from array position or patch it with CSS.
  When a user asks for a larger or smaller headline, map that request to one of
  these scale names and state the chosen name back in the implementation notes.
- `articleFrame.editorialPriority` names sequential importance with canonical
  terms: `primary`, `secondary`, `tertiary`, or `supporting`. This is separate
  from visual role and headline scale. In `front.mosaic`, one-column layouts
  use this priority so the `primary story` appears first even if it is centered
  or offset in a wide layout.
- `articleFrame.composition` can place label, headline, deck, byline, media,
  and pull quote slots on a local grid. Title slots reserve chrome above the
  body. Lead slots become solver-owned display obstacles inside the body and do
  not consume article cursors.
- Runtime validation uses Zod. A missing or invalid required plan is a
  publishing error; do not add a compatibility layer for previous plan shapes.
- Solved geometry, line positions, selected rectangles, and Pretext cursors must
  not be stored in the plan.

`lib/newspaper-layout.ts` owns layout and solver state:

- `ArticleFlow` tracks one article's current Pretext cursor and placed ranges.
- `PlacedTextRange` records `{ articleId, pageId, blockId, startCursor,
  endCursor, exhausted }`. Treat this as the source of truth for continuation
  correctness.
- `SolvedPage`, `SolvedRegion`, and `SolvedBlock` are the renderer contracts.
- `SolvedFurniture` includes image, pull quote, media cluster, and ad
  furniture with explicit solver-owned geometry.
- `buildNewspaperLayout(items, pageWidth, viewportHeight, layoutPlan)` receives
  generic publication items and the validated edition plan.
- The browser/client solver trusts the repository-normalized plan. Keep Zod
  validation in the content boundary and server/tooling path so Zod does not
  bloat the client newspaper bundle.

`components/newspaper.tsx` should remain mostly a renderer. It can map solved
objects to markup and CSS variables, but it should not decide text cutpoints,
page heights, section splits, or image variant scores.

`features/` owns executable BDD layout scenarios:

- `.feature` files are the durable behavior artifact. Keep them readable and
  product-level.
- Step definitions may use Playwright and geometry helpers to inspect DOM
  rectangles, but do not copy those details into scenario prose.
- Prefer adding a named fixture set in `lib/layout-scenarios.ts` when a bug
  depends on article length, viewport size, images, or pull quotes.
- Do not store test scenarios or edge-case fixtures in production edition
  records.
- The home page accepts `?scenario=<id>` as a content-source selector. It should
  go through `ContentRepository.loadEditionContent`, not bypass the content
  boundary in the renderer.
- The client exposes `window.__PAPYRUS_LAYOUT__` plus
  `window.__PAPYRUS_SCENARIO__` for test assertions.
- Scenarios should assert both rendered geometry and solver choices when a rule
  matters. For example, a blank-column repair should check that no continuation
  column is dead and that the intended image or furniture template won.

## Solver Flow

1. `buildNewspaperLayout(items, pageWidth, viewportHeight, layoutPlan)` creates
   layout config, publication item lookups, article flows, and page-grid
   choices.
2. The solver chooses a responsive page column count from supported counts
   `6, 5, 4, 3, 2, 1`, using the largest count that preserves readable column
   width and forcing one column on mobile.
3. Pages solve in edition-plan order. Page 1 normally uses `front.mosaic`; later
   pages can use region-stack, rail/main, strip, or full-page presets.
4. Each page solves its regions, and each region solves typed blocks inside the
   page grid.
5. `articleFrame` blocks create or resume an `ArticleFlow`. `startCursor:
   "beginning"` starts from the beginning; `startCursor: "current"` resumes
   from the cursor left by earlier blocks with the same `flowKey`.
6. `front.teaser` blocks consume article text first. Their `cutPolicy` can cap
   body lines and assign a planned `jumpTargetPage`.
7. Article blocks with media and pull quotes generate bounded local-grid and
   furniture candidates, convert furniture into text obstacles, run Pretext, and
   commit only the winning text range.
8. The layout returns generic solved pages, regions, blocks, furniture, placed
   text ranges, measured lines, and page heights for React to render.

## Text Fitting Invariants

`layoutTextLines` is the local Pretext wrapper. Preserve these rules:

- Derive visible line capacity from `linePaintHeight`, not just baseline
  `lineHeight`.
- Keep `TextLine.lineHeight` as the baseline advance.
- Keep `TextLine.paintHeight` as the rendered paint box height.
- `MeasuredLines` must render span height from `paintHeight`.
- `hasMore` should probe after the last fully visible line, not after a
  partially visible line.
- If text runs out, leave remaining space blank or spend it with planned
  furniture. Do not stretch lines or move neighboring stories.

## Page Geometry Invariants

- Page height is solver-owned and content-driven.
- Front-page row heights are capped. Extra viewport height should not stretch
  rows unless a recipe intentionally spends that space on furniture.
- During page-turn animation, the shell height should cover the active and
  previous page heights so pages do not clip mid-flip.
- Article block title heights, body heights, furniture heights, and region gaps
  must be reflected in solved page height.
- Composed article-frame chrome boxes must reserve solved paint space before
  body lines are measured. Decks, bylines, images, and pull quotes placed in the
  body field are obstacles, not article text.
- CSS variables passed from React should mirror solver geometry. Avoid duplicate
  independent `clamp(...)` logic for solver-owned measurements.

## Adaptive Furniture

Images and pull quotes are the current space-balancing furniture. Both must be
solver-owned obstacles before article text is measured.

- Image assets come from `getPublicationItemImageAssets`.
- Layout plans express media intent through responsive placement specs:
  `anchor`, `span`, `vertical`, `collapse`, `crop`, and `wrapsText`.
- Article images should normally use aspect-preserving column insets. Full-width
  bands should be explicit block/placement choices, not accidental defaults.
- Placed images and pull quotes become per-column `TextObstacle` rectangles.
  Pretext lays copy into each column around those obstacles.
- Pull quotes are fixture/editorial data, not generated dynamically, and they do
  not consume the article cursor.
- Pull quotes are optional. If they collide with media or make the fit worse,
  the solver should omit them.
- The solver tries a bounded set of variants and chooses deterministically.
- Text-only variants are fallback candidates, not the preferred outcome when a
  block has usable image assets and required media constraints.

When adding a new furniture type, make the solver return explicit geometry and
update React/CSS to render that geometry. Do not make CSS invent layout after
the solver has run.

## How To Extend The Edition

To add or change article data:

- Update content in GraphQL (`Item`, `MediaAsset`, `Edition`, `EditionItem`)
  through the CLI authoring lane.
- Use `skills/edition-planning/SKILL.md` and
  `skills/newsroom-story-cycle/SKILL.md` when creating a dated edition that
  needs new research or reporting candidates. Edition-candidate assignments are
  private `Assignment` records linked to the private `Edition` through
  `SemanticRelation`, and must not be published directly into `EditionItem` rows.
- Published editions must set `status`, `editionDate`, and `publishedAt`.
  `publishedAt` is required for archive listing and freshness order, even when
  date routes can still find the edition through `editionDate`.
- Edit `lib/articles.ts` only for base fixture/test data and scenario work.
- Add edge-case scenario variants in `lib/layout-scenarios.ts`.
- Keep body paragraphs long enough for continuation experiments.
- Add `assets` when an article has more than one usable image.
- Add pull quotes as editorial fixture data when they are useful for balancing
  whitespace.
- Add non-article items through `PublicationItem` normalization when a layout
  needs promos, ads, corrections, masthead items, or section headers.

To add cloud content fields:

- Add CMS fields in `amplify/data/resource.ts` when the field belongs in the
  persisted content model.
- Normalize those fields in `lib/graphql-content-repository.ts` before the
  solver sees them.
- Keep GraphQL schema concerns out of `lib/newspaper-layout.ts`.
- Update `amplify/seed/seed.ts` if fixture seeding should populate the new
  field.
- Prefer secondary indexes for real query access patterns instead of filtering
  large lists in the app.

To add a planned page:

- Add a new entry under `layoutPlan.pages[]` on `Edition.layoutPlan` in GraphQL.
- Choose an existing page preset (`front.mosaic`, `page.regionStack`,
  `page.railMain`, or `page.full`) unless the page needs a new reusable preset.
- Add regions and blocks with stable ids. Reference items by slug, not by array
  position.
- Add `articleFrame.cutPolicy.jumpTargetPage` on earlier blocks when a teaser
  should advertise the planned page.
- Validate required article/image/content constraints before publishing.
- If the deployed production app is older than the local layout-plan schema,
  advanced plan fields can make production reject `Edition.layoutPlan`. Prefer
  deploying current code before publishing newer plan vocabulary; if production
  must be restored immediately, make a narrow compatibility repair and document
  the removed fields.

To add a recipe or solver variant:

- Put main solver behavior in `lib/newspaper-layout.ts`.
- Reuse the generic block solver helpers when possible; avoid reintroducing
  page-specific continuation solvers.
- Try a small deterministic variant set.
- Score by no cropped lines, low unused space, correct cursor handoff, visual
  hierarchy, no furniture collisions, no dead columns, and stable labels.
- Commit text ranges only after the winning candidate is chosen.

To change rendering:

- Keep `components/newspaper.tsx` declarative.
- Pass solver values through CSS variables or inline dimensions.
- Keep direct article routes in `app/articles/[slug]/page.tsx` working.
- Keep the one-page flipper behavior.

## Video pipeline

- Read [publications/threat_intelligence/skills/produce-video/SKILL.md](publications/threat_intelligence/skills/produce-video/SKILL.md) before generating or changing Threat Intelligence videos. It defines branding, pictogram policy, content voice, and edition-overview requirements.
- Threat Intelligence seed videos are generated with `poetry run papyrus videos seed` (Python orchestration) and VideoML `vml pipeline` (Node subprocess via Babulus `packages/videoml-cli` when `~/Projects/Babulus` is present). See [publications/threat_intelligence/docs/video-pipeline.md](publications/threat_intelligence/docs/video-pipeline.md).
- The OpenAI key for TTS is sourced from `.papyrus/config.yaml` `openai.api_key` or `OPENAI_API_KEY` via [src/papyrus_content/papyrus_config.py](src/papyrus_content/papyrus_config.py). Never commit keys; `.papyrus/` stays gitignored.
- Article briefings are `MediaAsset(type="video")` rows linked to article `Item` records. Edition overview teasers live in `Edition.metadata.editionVideo` (also seeded from the fixture top-level `video` block). No separate `VideoAsset` model.
- Sandbox seed video S3 upload is gated by `PAPYRUS_SEED_VIDEOS=1`. Default seed still writes video metadata with local `externalUrl` paths.
- Worktrees without `.papyrus/config.yaml` should set `PAPYRUS_CONFIG` to the main clone config path before running the video pipeline.
- Threat Intelligence videos use **flat solid background colors** matching the blog dark-mode paper (`#191918`). Do not use gradient backgrounds in `TI_BACKGROUND_PROPS` or scene styles — the TI brand language is flat color, not SaaS-style gradients. Pictogram frames, quote cards, and CTA slides all sit on the same flat paper.

## Verification Checklist

Run these after changes:

```bash
npm run lint
npm run typecheck
npm run build
npm run test:bdd
npm run test:bdd:agent-live
```

Amplify checks when cloud content changes:

```bash
npm run sandbox
npm run seed:amplify
npm run build
```

Only run sandbox provisioning when the user expects AWS resources to be created
or updated. It requires configured AWS credentials and may create cloud
resources.

For archive or production content changes, also verify the reader endpoint that
the public page uses:

```bash
curl -sS "$PAPYRUS_BASE_URL/api/archive/editions?limit=1"
```

Browser smoke test these viewports:

- `1280x900`
- `1280x1600`
- `640x1200`
- `390x900`

Check all of the following:

- Page 1 renders one active page.
- The active page count matches the loaded `Edition.layoutPlan.pages.length`.
- The production AI/ML corpus edition currently renders as an 8-page issue:
  Page 1 is the front mosaic, Pages 2 through 7 are planned continuation pages,
  and Page 8 is a stacked page for the ASR and ML-history stories.
- Front-page continuation labels route to the planned page numbers.
- No `.measured-line` is vertically cropped inside `.story-measure` or
  `.continuation-column`.
- Page flipping works one page at a time in both directions.
- No console errors appear during flip or resize.

If the user is running the dev server on port `3001`, use it for smoke tests but
do not stop or restart it unless asked.

`npm run test:bdd` expects a running app and defaults to `http://localhost:3001`.
Use `PAPYRUS_BASE_URL` for another server. Use `PAPYRUS_HEADLESS=false` or
`npm run test:bdd:headed` when debugging geometry visually.

Frontend BDD is site-brand aware. The running app exposes reader capabilities on
`<html>` through `data-site-brand`, `data-default-presentation`,
`data-forced-presentation`, and `data-presentation-choices`. Scenarios declare
requirements with tags such as `@newspaper`, `@blog`, `@presentation-choice`,
and `@brand-agnostic`; incompatible scenarios skip automatically on locked fork
brands instead of failing during setup.

- **Full newspaper regression:** start the app with the canonical BDD brand from
  `config/bdd-canonical.env.example` (`PAPYRUS_SITE_BRAND=papyrus`,
  `NEXT_PUBLIC_PAPYRUS_SITE_BRAND=papyrus`), then run
  `npm run test:bdd:canonical`.
- **Fork checkout CI:** run `npm run test:bdd` against the fork's normal brand.
  Newspaper-only scenarios skip; blog scenarios run when the fork forces or
  defaults to blog.
- **Preflight only:** `npm run test:bdd:check-brand` reports the active site
  profile. Set `PAPYRUS_BDD_REQUIRE_CANONICAL_BRAND=1` to fail when the server
  is not on the canonical Papyrus reader profile.

`npm run test:bdd:agent-live` runs backend live-agent BDD (Behave/Python),
not frontend browser geometry checks.
