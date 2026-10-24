# Agent rules in detail

The full text of the Core Rules that [../AGENTS.md](../AGENTS.md) summarizes. When a rule here and AGENTS.md disagree, fix both in the same change.

- **Site hosting** is a configuration axis separate from renderer and layout.
  Read [`docs/site-hosting.md`](site-hosting.md) before standing up or
  changing Amplify apps for a publication. Root `amplify.yml` here is **SSR /
  WEB_COMPUTE** for p.apyr.us only (`ampx pipeline-deploy`, `.next` artifacts).
  Markus sites default to `backend.publication` `s3-projection` (S3 bucket
  behind CloudFront, no reader app; edge templates in `infra/edge/`). A Markus
  site that keeps an Amplify reader (app-shell `reader`, `backend.reader`) or sets `publication: false`
  uses the static `WEB` reader app described by
  [`docs/hosting/amplify-static.yml.example`](hosting/amplify-static.yml.example)
  — do not cargo-cult this repo's SSR build spec.
- Before running any AWS-, Amplify-, sandbox-, or deployment-related command,
  read `AGENTS.local.md` and follow its local account/profile/env guidance.
  Treat `AGENTS.local.md` as required preflight context for cloud operations on
  this machine.
- Papyrus is an Amplify Gen 2 project. Production backend/frontend deployment is
  done from `main` through the configured DevOps/Amplify pipeline. Do not run
  `ampx pipeline-deploy` (or other direct production `ampx` deploy commands)
  from local agents unless the user explicitly asks for that exact override. Use
  `ampx` locally for sandbox workflows only.
- Papyrus is Python-first for backend workflows. Create new backend utilities,
  CLIs, automation, API tests, and backend BDD harnesses in Python by default.
  Use JavaScript/TypeScript only for the Next.js/React frontend and
  frontend-specific test harnesses.
- Do not add backward-compatibility fallbacks for old schema, GraphQL, content,
  layout-plan, or CLI shapes. See
  [Schema and API alignment (no compatibility shims)](schema-and-api-alignment.md).
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
  `npm run seed:amplify` (which seeds users, sections, doctrine and procedures;
  articles are seeded with `poetry run papyrus ops content seed-edition`). `.env*` must stay ignored, and `.env.example` is the
  committed template.
- **GraphQL auth split (do not mix):**
  - **Editorial CLI users** may use the configured native Google/Cognito login
    in [CLI login](cli-login.md), under the same server-checked user permissions
    as the newsroom. Renewable session material belongs only in macOS Keychain;
    public publication/client selection metadata may be persisted separately.
    Never scrape browser cookies, log tokens, invent grants, use API-key/guest
    authoring, or fall back to a broader IAM identity when user auth fails.
  - **Operator IAM commands** explicitly use `PAPYRUS_GRAPHQL_AUTH=iam` and the
    standard AWS chain (SSO, assumed role, OIDC or build role). Native user login
    does not grant deployment or infrastructure authority. This user-auth lane
    intentionally replaces the former IAM-only CLI policy; it does not change
    Lambda role auth or introduce a custom authorizer.
  - **Deployed Lambda functions** call AppSync with **IAM only** (SigV4 /
    `authMode: "iam"` on the Amplify data client). The same signing code serves
    CLI and Lambdas. Do not set secrets on Lambdas for GraphQL access, and do
    not add alternate GraphQL auth paths inside Lambda code. Grant access with
    `allow.resource(<function>)` on the data schema and `appsync:GraphQL` on the
    function role.
- Production authoring uses the deployed production AppSync endpoint, not the
  sandbox. Authenticate with an AWS profile for the production account's
  authoring role; do not write credentials into `.env`. Follow
  `skills/category-steering/SKILL.md` for the category/graph steering import
  workflow.
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
  for evidence sets, topic modeling, graph analysis, section memory, context
  packs, assignment evidence, or edition planning.
- For **internal knowledge base search** (accepted references, semantic + graph
  context packs), read `docs/internal-knowledge-research.md` first, then
  `skills/knowledge-query/SKILL.md`. Run queries with
  `PYTHONPATH=src python -m papyrus_newsroom knowledge-query` or
  `poetry run papyrus-newsroom knowledge-query` (not ad-hoc GraphQL). Use
  `--execution local` only when developing engine behavior; default remote
  execution needs `PAPYRUS_GRAPHQL_ENDPOINT` and AWS credentials (`AWS_PROFILE`).
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
- The Newsroom is the newsroom operations surface. `Topics` is one tab,
  not the whole product concept. Use `/newsroom` and Newsroom naming in UI,
  docs, and tests. Future assignment and research queues should become tabs
  instead of separate one-off management pages.
- `/newsroom/doctrine` manages publication-wide mission and policies.
  `/newsroom/sections` manages the operational section surface through
  `NewsroomSection` mission, policies, assignment guidance, kill criteria, and
  budgets. Legacy category-tied section doctrine may still exist for migration, but
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
- Assignment lifecycle changes use protected actions or the IAM authoring CLI
  and append `AssignmentEvent` audit rows. The Newsroom `Assignments` tab
  should show claim/release/complete/cancel/reopen workflow actions, not
  candidate culling.
- **One content item, one lifecycle** (`docs/content-item-lifecycle.md`). A
  piece of content is one `Item` lineage from the moment work on it starts
  until publication. `Item.stage` carries the lifecycle (`idea`,
  `assignment`, `reporting`, `copywriting`, `illustration`, `typesetting`,
  `published`, `held`, `spiked`); `Item.versionState` still versions the copy. Research,
  reporting and copywriting Assignments are work on that content item and
  carry its `itemLineageId`; they never create a second piece of content. The
  name editors see is `SiteBrand.contentItemName` (default Story). Do not
  build Story-to-Article hierarchies.
- Editorial selection is separate from assignment lifecycle. Reporting packet
  decisions use `AssignmentEvent.eventType` values
  `reporting_select`, `reporting_merge`, `reporting_brief`, `reporting_hold`,
  and `reporting_kill`, with structured metadata in a `ModelAttachment` owned by
  the event. `select` and `brief` create private copywriting Assignments
  (`copywriting.article-draft` or `copywriting.brief-draft`) on the same
  content item, not new `Item` lineages.
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
  decisions queue copywriting Assignments; copywriting is the first stage that
  writes reader-facing copy, as the next version of the content item that
  dispatch created at the `report` stage. Edition placement remains a later
  copyediting/layout step.
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
    theme (phase 1), optional section (phase 2), reporting dispatch (phase 3);
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
  plan` as the Python assignment-section layer when an edition should be planned
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
