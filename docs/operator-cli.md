# Operator CLI (dual backend)

One `papyrus` command against a local pod or the cloud newsroom. Executable spec: `features_backend/operator-cli.feature`.

Operators use **one** `papyrus` command on PATH (`[project.scripts] papyrus =
papyrus.cli:main`). It is a thin facade over `papyrus_content` and
`papyrus_newsroom` today; the operator surface is converging on the same argv for
**local pod** and **cloud** backends.

- **Same verbs, same flags.** Core operator commands include `papyrus references
  list`, `papyrus references show <id>`, and `papyrus assignments list`. Local pod and cloud must accept the same argv and
  return the same human-readable output shape (tabular list rows, detail blocks,
  exit codes). Executable specs live in `features_backend/operator-cli.feature`.
- **Backend is config, not a second command tree.** Select `local` or `cloud`
  from project config (`backend`, `local.podPath`, `cloud.graphqlEndpoint`) or
  with `--backend local|cloud`. Do not fork the noun vocabulary per backend.
- **Local pod backend** reads the Anth.us publication submodule
  (`pods/anthus-blog`, repo `AnthusAI/anthus-semantic-knowledge-base`): story
  artifacts, hooks, and pod reference rows. It does
  **not** revive a local Markdown content store (`content/articles/`) or emulate
  hosted corpus sync, editions, or the layout solver.
- **Cloud backend** uses the existing GraphQL/AppSync newsroom (`Reference`,
  `Assignment`, editions, knowledge-query). Corpus key, publication, endpoint,
  and credentials come from steering/config defaults (`threat-intelligence` today);
  operators should not need `--corpus-key` or `PYTHONPATH=src` for the common
  path.
- **Object kinds are explicit.** Cloud `assignments list` rows are GraphQL
  `Assignment` work records (`kind: newsroom-assignment`). Local `assignments
  list` rows are Kanbus **pod stories** (`kind: pod-story`), not GraphQL
  Assignments. A pod story's `assignment` **stage** is Kanbus workflow state —
  use `kbs` for board columns and transitions. Cloud `references` rows are
  GraphQL `Reference` records (`kind: cloud-reference`); local rows are pod
  evidence/source artifacts (`kind: pod-reference`).
- **`kbs` stays the board.** Kanbus owns issues, columns, screenshots, and
  workflow transitions. `papyrus` owns newsroom objects (references, assignments,
  editions, knowledge). Do not merge `kbs` into `papyrus`.
- **Auth is operator UX.** Cloud authoring signs with the AWS credential chain
  (`AWS_PROFILE`); there is no `papyrus auth` group and no token to refresh.
  Missing AWS credentials must print recovery guidance, not a Python traceback.
- **Local pod references** live under `stories/<story-id>/references/*.json`.
  `papyrus references register --backend local` requires `--story <story-id>`
  or `local.defaultStory` in operator CLI config; never hard-code a story path.
  Same URL within the same corpus is an identity: re-register must refuse rather
  than overwrite accepted `status`/`why`/`title`. `accepted` and `pending` rows
  require a non-empty `--why`; `rejected` with empty why writes no row. List
  output includes `url`; show output includes `url` and `why`.
- **Kanbus `project_key` is stable.** Changing `.kanbus.yml` `project_key` does
  **not** remint existing issue ids or filenames under `project/issues/`. After a
  key change, legacy ids (for example `WIKI-*` rows when the key is `ANTH`) keep
  their old prefix; `papyrus` local-pod commands warn when legacy prefixes are
  detected. Pass `--story` explicitly; do not assume new work lands on a retired
  story id.

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
