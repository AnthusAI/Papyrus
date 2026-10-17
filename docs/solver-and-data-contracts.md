# Solver, renderer and data contracts

Which module owns layout, content normalization and the cloud backend, and how the solver turns an edition plan into pages. Moved out of AGENTS.md.

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
  copywriting writes the draft copy as the next version of the same content
  item, in `article` or `brief` format. Draft creation is not edition
  placement.
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
- The public read path uses `authMode: "identityPool"` (Cognito guest / unauthenticated
  IAM role). Do not depend on expiring AppSync API keys for SSR reader traffic.

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
- The data API supports public API-key reads, Cognito user-pool auth (newsroom
  editor sessions), the Cognito identity pool (guest reads, authenticated
  reads/writes), and **IAM** for registered Lambda functions
  (`allow.resource(...)`) and for the CLI and automation. AppSync IAM
  authorization is enabled on the API (`enableIamAuthorizationMode`), so access
  for IAM principals is controlled by IAM policy (`appsync:GraphQL`), not by
  schema rules. The CLI's role is the `<siteId>-papyrus-authoring` role created
  by `infra/amplify-app-shell`. There is no Lambda authorizer and no secret for
  GraphQL access.

`src/papyrus_content` owns the content authoring CLI:

- `poetry run papyrus` is the canonical backend CLI surfaced by
  the `papyrus` command groups.
- The CLI is GraphQL authoring and inspection.
- `src/papyrus_content/graphql_authoring.py` owns GraphQL authoring calls, always
  signed with SigV4 from the standard AWS credential chain (CLI and Lambda alike).
- `graphql_authoring.py` uses **fixed** query field lists and explicit input
  shaping. Do not add runtime schema introspection to adapt to undeployed fields.
  See [Schema and API alignment (no compatibility shims)](schema-and-api-alignment.md).
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
