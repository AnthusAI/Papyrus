# AGENTS.md


## Ryan's board names

When Ryan says **the newsroom board** or **the Papyrus board**, he means the Anth.us publication board (Kanbus key `ANTH`), not this repo's product board (`PPY`). Call `PPY` the product board or the PPY board.

Source of truth: [AnthusAI/anthus-semantic-knowledge-base](https://github.com/AnthusAI/anthus-semantic-knowledge-base), checked out at `~/Projects/anthus-semantic-knowledge-base`. Work there:

```bash
cd ~/Projects/anthus-semantic-knowledge-base
kbs list    # or: kanbus list
```

Papyrus `develop` also mounts that repo as a git submodule at `pods/anthus-blog`. That path is live only after `git submodule update --init` in a checkout that has `.gitmodules`. The default `~/Projects/Papyrus` tree is often a feature branch whose `pods/anthus-blog` is still the old **empty template**. If `kbs list` shows no stories, you are in the stale copy. Do not conclude the board is empty. Do not use anything under Anth.us `src/blog/` as the publication board.

## Project management with Kanbus

Use Kanbus for task management.
Why: Kanbus task management is MANDATORY here; every task must live in Kanbus.
When: Create/update the Kanbus task before coding; close it only after the change lands.
How: See CONTRIBUTING_AGENT.md for the Kanbus workflow, hierarchy, status rules, priorities, command examples, and the mistakes to avoid. Never inspect project/ or issue JSON directly (including with cat or jq); use Kanbus commands only.
Performance: Prefer kbs (Rust) when available; kanbus (Python) is equivalent but slower.
Warning: Editing project/ directly violates The Way. Do not read or write anything in project/; work only through Kanbus.
Git / PR policy: Rules for product-code commits, branch names, pull requests, and human approval live in this repository's AGENTS.md (outside this Kanbus section). CONTRIBUTING_AGENT.md covers Kanbus board mechanics such as `kbs commit`; follow AGENTS.md for product code and git workflow.

## Purpose

Papyrus is a general-purpose automated newsroom: a Next.js/React newspaper layout lab built on `@chenglou/pretext` plus a Python newsroom of research, reporting and copywriting agents. The AI/ML corpus and editions are pilot configuration. Never bake a subject area, corpus name, classifier id or content category into application logic. Pretext owns text measurement; Papyrus owns everything around it. Background: [docs/how-papyrus-works.md](docs/how-papyrus-works.md).

## Git workflow (mandatory)

Git Flow. Agents commit, push and open PRs as normal delivery.

- Branch from `origin/develop`, named after the Kanbus issue: `feature/PPY-xxxxxx-slug`, `fix/...`, `chore/...` (a `cursor/` prefix when host tooling requires it).
- Never commit implementation to `develop` or `main`. It lands on `develop` by pull request.
- `project/` changes and spec-only Gherkin go straight to `develop`, no PR. If they belong with an implementation, include them in that PR.
- Never merge to `main` or open or merge `develop -> main` without explicit human instruction. Standing instruction (Ryan, 2026-10-18, project thread): once CI is green, agents may promote `develop` to `main`, let the release publish, and open and merge the version-bump PRs on the Papyrus test sites without asking again. Never touch Anth.us. Never merge a change to this rule yourself.
- Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `ci:`). Never amend or force-push a commit that may have reached `develop` or `main`. If you committed to either by mistake, stop and ask.
- Stage deliberately; the tree is often dirty. Never `git add -A` while someone else's work is in flight.
- Done means pushed, with the branch, PR link and verification recorded on the Kanbus issue. Report whether the change has landed in `develop` and whether a `develop -> main` PR exists.

## Rules, each with its enforcement

"Unenforced" means no test, lint or CI check fails when the rule is broken; review is the only guard. Full text: [docs/agent-rules-detail.md](docs/agent-rules-detail.md).

### Layout

| Rule | Enforced by |
| --- | --- |
| The solver decides geometry before render; React never measures the DOM to decide layout, and text lines come from Pretext, not CSS line clamps. | `features/newspaper-layout.feature` (geometry via `window.__PAPYRUS_LAYOUT__`); no-clamp is unenforced. |
| Every measured line is all-or-nothing vertically (`paintHeight`, not just `lineHeight`). | `features/newspaper-layout.feature` and `features/blog-rhythm.feature` (cropped-line steps in `features/step_definitions/layout.steps.js`). |
| Continuations are planned in `Edition.layoutPlan`; labels read `SEE READING ON A3` / `READING FROM A1` (`MORE` / bare `FROM A1` without a `shortSlug`). | `npm run test:newspaper-layout-cursor-continuity`, `features/newspaper-layout.feature`. |
| Exact cursor handoff: never duplicate or skip article text between blocks or pages. | `scripts/test-newspaper-layout-cursor-continuity.ts` (`npm run test:newspaper-layout-cursor-continuity`). |
| The layout plan is validated with Zod at the content boundary; no solved geometry or cursors are stored in it; no compatibility layer for old plan shapes. | `lib/layout-plan.ts` validation at load; "no stored geometry" and "no old shapes" unenforced. |
| `headlineScale` is one of `banner`, `feature`, `standard`, `rail`, `brief`, set in the plan, never patched in CSS. | Zod schema in `lib/layout-plan.ts`; CSS patching unenforced. |
| Keep the one-page React flipper: no Turn.js, jQuery or DOM-mutating layout loops. | Unenforced. |
| Use newspaper vocabulary with users and agents (`feature headline`, `rail headline`, `articleFrame composition`, `local grid`, `media inset`, `planned continuation`, `solver-owned furniture`). | Unenforced. |
| Furniture (images, pull quotes) is solver geometry before text is measured, never invented by CSS. | `features/newspaper-layout.feature` (furniture and blank-column scenarios). |

Module boundaries and solver flow: [docs/solver-and-data-contracts.md](docs/solver-and-data-contracts.md). Layout design rules: [docs/layout-system.md](docs/layout-system.md).

### Content and cloud

| Rule | Enforced by |
| --- | --- |
| Cloud content stays behind `ContentRepository`; Amplify, GraphQL and Storage types never reach `lib/newspaper-layout.ts`. | `npm run check:reader-route-content-source` (routes only); the solver import boundary is unenforced. |
| No local Markdown content store (`content/articles/`). Edition content comes from GraphQL; `?scenario=<id>` fixtures are for tests only. | `npm run test:content-source` (reader reads published models only), `npm run check:reader-route-content-source`. The `content/articles/` ban itself is unenforced. |
| Keep the S3 bucket private. Reader media uses Storage access rules and signed URLs. | `npm run test:guest-read-auth`, `npm run test:identity-pool-model-access`. |
| GraphQL auth: configured editorial CLI sessions use normal Google/Cognito user-pool auth via `papyrus login`, with renewable secrets in macOS Keychain. Operator commands explicitly select IAM; Lambdas keep their managed IAM roles. Never fall back from failed user auth to IAM or use guest/API-key authoring. | `features_backend/cli-user-auth.feature`, `test_cli_user_auth.py`, and `refuse_guest_auth`; provider/client setup and live permission parity require review. See `docs/cli-login.md`. |
| Schema drift is fixed by deploying, never by shims: no runtime introspection, reduced-field fallbacks or dual-shape normalizers. | `npm run test:schema-parity` covers `schema.ts` vs `resource.ts`; shims are unenforced. See [docs/schema-and-api-alignment.md](docs/schema-and-api-alignment.md). |
| No backward-compatibility fallbacks for old schema, GraphQL, content, plan or CLI shapes unless the user asks. Clean breaks. | Unenforced. |
| Published editions set `status`, `editionDate` and `publishedAt`; archive listing depends on `publishedAt`. | Unenforced. Check `curl "$PAPYRUS_BASE_URL/api/archive/editions?limit=1"`; see [docs/production-content-operations.md](docs/production-content-operations.md). |
| BDD fixtures never go in production content records. | Unenforced. |
| `.env*` stays ignored; `.env.example` is the committed template. New required settings go in `.env.example`. | `.gitignore` (`.env*`); `.env.example` completeness is unenforced. |
| Python-first backend: new utilities, CLIs, automation and backend tests are Python. JS/TS is for the frontend and its harnesses. | `npm run check:backend-node-policy`. |

### Deploys and AWS

- Read `AGENTS.local.md` before any AWS, Amplify, sandbox or deploy command. Unenforced.
- Production deploys go through the DevOps pipeline from `main`. Never run `ampx pipeline-deploy` or other production `ampx` deploys from a local agent unless the user names that exact override. Use `ampx` locally for sandbox only. Unenforced.
- Root `amplify.yml` is SSR (`WEB_COMPUTE`) for p.apyr.us only; Markus sites follow [docs/site-hosting.md](docs/site-hosting.md). Unenforced.
- Production content refreshes are targeted GraphQL upserts after a reviewed diff. No sandbox seed or `content delete all --yes` against production. Unenforced. See [docs/production-content-operations.md](docs/production-content-operations.md).

### Newsroom

| Rule | Enforced by |
| --- | --- |
| One content item, one lifecycle: `Item.stage` carries `idea`, `assignment`, `research`, `report`, `editor_select`, `copywriting`, `illustration`, `typesetting`, `published`. No Story-to-Article hierarchy. Research, reporting and copywriting Assignments carry the item's `itemLineageId`. | `procedures/newsroom/tests/test_content_item_lifecycle.py`; [docs/content-item-lifecycle.md](docs/content-item-lifecycle.md). |
| Assignments are private `Assignment` records, never `Item` rows. Lifecycle changes append `AssignmentEvent` rows. | `npm run test:identity-pool-model-access` keeps `Assignment` and `MessageThread` off the identity pool; `features_backend/assignment-management.feature` covers create, list and update. `AssignmentEvent` audit rows are unenforced. |
| Research and reporting produce private `Message` packets with `ModelAttachment` payloads, linked `Assignment --produces--> Message`. Only copywriting creates reader-facing draft copy. | Unenforced. `features_backend/research-reporting-context.feature` covers orientation traces only. |
| Reporting review (`select`, `merge`, `brief`, `hold`, `kill`) never creates `EditionItem`; edition placement is a later layout step. | `features/newspaper-layout.feature` ("reviews reporting packets without publishing placement"). |
| Only current accepted `Reference` rows feed evidence sets, analysis, desk memory, context packs and edition planning. Packet `proposedReferences` are prospects until intake registers them. | `is_evidence_eligible_reference` in `src/papyrus_newsroom/reference_policy.py` is the single gate where callers use it; coverage of every consumer is unenforced. See `skills/reference-intake/SKILL.md`. |
| Corpus contents stay in Biblicus and S3. GraphQL holds steering state, strict `Reference` metadata and `item_id` references only. | Unenforced. |
| Doctrine, not code, carries subject assumptions. No corpus name, classifier id or category in `/newsroom`, the content CLI, GraphQL models or layout code. | Unenforced. Known violations are tracked under epic PPY-36270a. |
| Rejected steering proposals are exported (`export-steering-feedback`) before each new proposal cycle. | Unenforced. See [docs/category-steering-runbook.md](docs/category-steering-runbook.md). |
| New `SemanticRelation` writes set `relationTypeId`, `relationTypeKey` and `relationDomain`. | Unenforced. |
| Cyclotron config refuses invalid blocks and never takes provider keys from config. | `features_backend/cyclotron-relevance-config.feature`. |

Workflows for agents live in `skills/`: `edition-planning`, `newsroom-story-cycle`, `newsroom-research-workflow`, `researcher-doctrine`, `reference-intake`, `category-steering`, `knowledge-query`, `publication-bootstrap`. Newsroom work is styled as a newspaper section, not an app dashboard; steering is passive and optional.

### Operator CLI

| Rule | Enforced by |
| --- | --- |
| One `papyrus` command; local pod and cloud accept the same argv and return the same output shape. Backend is config or `--backend`, not a second command tree. | `features_backend/operator-cli.feature` (`npm run test:bdd:operator-cli`). |
| No traceback on expected failures; operator errors exit 2; the shell environment wins over `.env`. | `features_backend/operator-cli.feature`, `procedures/newsroom/tests/test_operator_errors.py`. |
| `kbs` owns the board; `papyrus` owns newsroom objects. Do not merge them. | `features_backend/operator-cli.feature` (help text). |

Details: [docs/operator-cli.md](docs/operator-cli.md).

## Verification

Before opening a PR run what the change touches: `npm run lint`, `npm run typecheck`, `npm run build`, `npm run test:bdd`, `npm run test:bdd:backend`, `npm run test:bdd:operator-cli`, and the relevant `npm run test:*` scripts. Amplify, archive and browser smoke checks: [docs/verification.md](docs/verification.md). CI runs `.github/workflows/tests.yml` (not every local script is wired in). Use the dev server on port 3001 if the user is running it, and do not restart it.

## Index

Everything else is in [docs/README.md](docs/README.md): architecture, layout, hosting, newsroom operations, runbooks and archives. Kanbus mechanics are in [CONTRIBUTING_AGENT.md](CONTRIBUTING_AGENT.md).
