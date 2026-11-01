# AGENTS.md

Operating manual for any coding agent (Codex, Cursor, Claude Code) or person working in the Papyrus engine repository. For what Papyrus is and how it ships, read [README.md](README.md) first. Everything here was checked against the code on `origin/develop` on 2026-10-23.

## Read this first

- This is the **engine**. Site repositories (Shipped-web, Distinctive-web, Pilobol.us, and so on) hold only site settings; fix the engine here, release it, bump the pin there.
- Work in a **git worktree**, branched from `origin/develop`. The shared checkout `~/Projects/Papyrus` is used by several sessions: never switch its branch and **never `git stash`**.
- Every task lives on the **Kanbus board** (project key `PPY`). Create or update the issue before coding.
- Every behaviour change ships with **Gherkin specs** (narrative, complete). Unit tests alone are not enough.
- Read `AGENTS.local.md` (gitignored, machine-local) before any AWS command, but treat the repository docs as the reference: that file may name the legacy account `335163751677` as production, and production is `papyrus-production` (`712236451410`).
- Wording: never write "desk" in prose; attribution is just "AI" (for example "Edited by AI on DATE"); the shared directory tenant is an **Account**, never "Organization". Code identifiers that still say desk (`components/news-desk-*.tsx`, `NewsDeskShellState`, `news-desk-*` CSS classes, `deskId`, `desk_category`, `papyrus editorial pack` help text) are kept as they are; do not rename them in a docs change and do not copy the word into new prose.

## Map of the parts

| Part | Where | Docs |
| --- | --- | --- |
| Standard Markus projector and front end | `src/papyrus_content/markus_renderer/`, `src/papyrus_content/project_commands.py`, `web/projection.json` in a site | [building a static site](docs/building-a-papyrus-static-site.md), [standard site](docs/standard-site.md), [markus markup](docs/markus-content-markup.md) |
| CMS backend and console | `amplify/` (data, auth, storage, `functions/`, `publication/`), `app/newsroom`, `components/` | [how Papyrus works](docs/how-papyrus-works.md), [newsroom operations](docs/newsroom-operations.md), [how a publish flows](docs/how-a-publish-flows.md) |
| Plugins | `amplify/plugins/{signup,newsletter,reader-steering,home-page,alexa}`, registry in `amplify/plugins/registry.ts` | [plugins](docs/plugins.md) |
| Proposals queue (core to every site): `Proposal` model, `fileProposal`, `transitionProposal`, `editProposal`, `listStoryDrafts`, Administration Proposals panel | `amplify/functions/proposal-actions`, `components/proposals-panel.tsx`, `lib/proposals-admin.ts`, `papyrus proposals` | [reader steering](docs/reader-steering.md#proposals) |
| Reader steering: votes on any subject, flags, ratings, comments, votes on and public files for Proposals | `amplify/plugins/reader-steering`, `src/papyrus_content/reader_steering/`, `papyrus reader`, `papyrus proposals` | [reader steering](docs/reader-steering.md) |
| Newsletter: double opt-in, clean `/newsletter/*` pages, branded email theme, roundups, alerts | `amplify/plugins/newsletter`, `app/api/newsletter/*`, `infra/newsletter/` | [newsletter](docs/newsletter.md) |
| Edge | `infra/edge/` (`s3-projection-cms.yaml`: NotFoundPage Lambda@Edge, `/api/*` pass-through, #560) | [edge README](infra/edge/README.md), [site hosting](docs/site-hosting.md) |
| App shell (Amplify apps, roles, domains per site) | `infra/amplify-app-shell/` | [app-shell README](infra/amplify-app-shell/README.md), [site hosting](docs/site-hosting.md) |
| Monitoring and the router | `src/papyrus_content/monitoring*.py`, `infra/monitoring/` | [monitoring in the cloud](docs/monitoring-cloud.md), [local HN worker](docs/monitoring-hn-pilot.md) |
| Shared relevance Cyclotron | `src/papyrus_content/relevance_cyclotron.py`, `pyproject.toml` group `cyclotron` | [Cyclotron](docs/cyclotron-priming.md), [steering and relevance](docs/steering-and-relevance.md) |
| Procedure runner and Tactus procedures | `infra/procedures/`, `procedures/newsroom/`, `papyrus procedures` | [procedure runner](docs/procedure-runner.md), [newsroom procedures runbook](docs/newsroom-procedures-runbook.md) |
| Knowledge run (local and cloud), weekly archive, projection lease | `infra/scheduled-jobs/`, `infra/knowledge-run/`, `amplify/publication/projection-lease.ts`, `papyrus knowledge` | [workstation run](docs/knowledge-workstation-run.md), [cloud run](docs/knowledge-cloud-run.md), [knowledge snapshot](docs/knowledge-snapshot.md), [lease](docs/site-hosting.md#projection-lease-one-projection-at-a-time) |
| Automations (including story-state triggers) | `src/papyrus_content/automations.py`, `src/papyrus_content/story_triggers.py`, `amplify/functions/automation-view`, `papyrus automations`, `papyrus stories fire-triggers` | [automations](docs/automations.md) |
| Idea pipeline v0, trend stories, monitor stories | `src/papyrus_content/ideas/` (`trends.py`, `monitor_stories.py`), `papyrus ideas digest\|synthesize\|trends\|monitor-stories` | [idea pipeline](docs/idea-pipeline.md) |
| Review requests and the Notification Center (console home) | `src/papyrus_content/review_requests.py`, `components/notification-center.tsx`, `lib/review-requests.ts`, `papyrus reviews`. Merged to `develop` (#642); live on a site after its data API deploys | [notification center](docs/notification-center.md), [review requests](docs/review-requests.md) |
| GA4 and consent | `src/papyrus_content/markus_renderer/consent.py`, `analytics_events.py` | [site hosting: Analytics](docs/site-hosting.md#analytics-google-analytics-4) |
| Pretext layout solver and reader | `lib/`, `renderers/`, `features/` | [layout system](docs/layout-system.md), [solver and data contracts](docs/solver-and-data-contracts.md) |
| Operator CLI | `src/papyrus/`, `src/papyrus_content/cli.py` | [operator CLI](docs/operator-cli.md), [CLI login](docs/cli-login.md) |
| Packaging | `packages/`, `release.config.cjs` | [releasing](docs/releasing.md) |

Other code: `corpora/` (one-time doctrine and steering imports), `features_backend/` (behave specs, 70-plus features), `features/` (cucumber layout specs), `skills/` and `.agents/skills/` (agent workflows), `scripts/` (TypeScript tests), `src/papyrus_newsroom` and `src/papyrus_knowledge_query` (Python newsroom libraries).

## Git workflow

Git Flow. Agents commit, push and open pull requests as normal delivery.

- Branch from `origin/develop`, named after the Kanbus issue: `feature/PPY-xxxxxx-slug`, `fix/...`, `chore/...`, `docs/...`, `board/...` (a `cursor/` prefix when host tooling requires it).
- Never commit to `develop` or `main` directly. Work lands on `develop` by pull request, merged with a **merge commit** once CI is green.
- Board-only changes (the `project/` directory) are small `board/<slug>` branches and pull requests, merged the same way; in practice that is what the history shows. If a board change belongs to an implementation, include it in that PR.
- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `ci:`. Only `feat:`, `fix:` and breaking changes release; `chore:` and `docs:` do not. Never amend or force-push a commit that may have reached `develop` or `main`.
- Commits end with the attribution line your tool is configured to add; pull request bodies end with the tool's generated-with line.
- **Promotion to `main`** is a pull request `develop` to `main` with a merge commit. Never promote, or merge to `main`, without an instruction in your task or from a human. Standing instruction (Ryan, 2026-10-18): once CI is green, agents may promote `develop` to `main`, let the release publish, and open and merge the version-bump pull requests on the Papyrus test sites without asking again. Never touch Anth.us. Never change this rule yourself.
- Stage deliberately; trees are often dirty. Never `git add -A` while someone else's work is in flight.
- Done means pushed, with the branch, PR link and verification recorded on the Kanbus issue. Report whether the change reached `develop` and whether a `develop` to `main` PR exists.
- When finished, remove your worktree: `git worktree remove <path>` from the shared checkout.

```bash
cd ~/Projects/Papyrus && git fetch origin
git worktree add -b docs/my-change ~/Projects/Papyrus-worktrees/my-change origin/develop
```

## Hard rules

- **Never run a reconcile without the deployed plugin list, and never use `--allow-deletions`** unless a refusal was reviewed and the deletions are intended. `papyrus ops content project --reconcile` (not a dry run) refuses when the plugin list it would use is unknown or differs from the deployed one (`PAPYRUS_PLUGINS`, or `custom.papyrusPlugins` in `amplify_outputs.json`), and never deletes pages under a known plugin's prefix (#594; spec `features_backend/projection-reconcile-plugin-pages.feature`). Always run `--reconcile --dry-run` first.
- **Projections take the projection lease** (`papyrus-projection-locks`, one projection per site bucket at a time). Never bypass it, and clear a stuck lease only after confirming the holder is gone ([lease](docs/site-hosting.md#projection-lease-one-projection-at-a-time)). Snapshots and projections run only from a checkout whose `origin/main` is current: a stale checkout once deleted 282 wiki pages.
- **A failed Amplify deploy is read before anything is retried** (Ryan, 2026-10-31; builds cost $0.01 a minute and 74 of 542 builds in 30 days failed). Run `papyrus-infra amplify job-log --app-id <id> --latest-failed` (read-only; `AWS_PROFILE=papyrus-production`) and quote the cause before doing anything else. `redeploy-this-version` is only for an environment failure (throttle, out of memory, network) and only once; a code failure is fixed with a new commit through CI, and that push is the retry. Amplify builds only deploy: no lint, type-check or tests run inside them.
- **Secrets go in SSM SecureString** (generated by infrastructure code, or `papyrus site google-secrets set`), never in the repository, `site.json`, branch variables or chat. **No real email addresses in the repository**: use placeholders (`newsletter@<sendingDomain>`); allowlists live in AWS configuration.
- **Shared checkouts: never switch branches, never `git stash`.** Use worktrees. Remove them when done.
- **Production AWS**: use `AWS_PROFILE=papyrus-production` and assert the account (`aws sts get-caller-identity --query Account --output text` prints `712236451410`) before any write. Never run `ampx pipeline-deploy` locally. Stack changes go through a CloudFormation change set that a human reads. `aws sso login` is interactive; only the user can run it.
- **GA4 consent is the Anth.us standard**: Consent Mode v2 with the first-party banner. `analytics_only` exists but stays **off** on every site.
- **Human review is never a story state.** Do not add a "review" stage to a content item; human review is a review request ([review requests](docs/review-requests.md)).
- **Never create Cognito password users**; sign-in is Google only.
- **Reader steering stays closed in production** until Prospectus returns a site subject; do not add a flag to open it.
- Subject areas, corpus names and categories never go into application logic; the pilot-identifier guard (`procedures/guards/check_pilot_identifiers.py`) fails CI on new ones.
- Ask before changing shared infrastructure (see Ownership).

## Common tasks

Run from a worktree. Python commands use `poetry run` (or the Poetry virtualenv's Python with `PYTHONPATH=src`).

### Install and run the tests

```bash
npm ci
poetry install --extras "newsroom markus priming" --with cyclotron
echo '{}' > amplify_outputs.json                 # git-ignored stub for the type check
npm run typecheck && npm run lint
npm run test:bdd:backend                          # behave over features_backend/
poetry run behave features_backend/projection-reconcile-plugin-pages.feature
poetry run pytest -q procedures/newsroom/tests/test_ideas.py
npm run test:schema-parity
npm test                                          # all TypeScript and Lambda tests
python procedures/guards/check_pilot_identifiers.py
```

Cucumber layout specs need Playwright (`npx playwright install --with-deps chromium`, then `npm run test:bdd`). Live-agent specs (`test:bdd:agent-live`) call real models; do not run them without being asked. Full list: [verification](docs/verification.md), [Python CLI and testing](docs/python-cli-and-testing.md).

### Preview the console locally

```bash
npm run dev:preview        # seeded, no AWS: http://127.0.0.1:3002/newsroom/work
npm run dev:127            # real backend via amplify_outputs.json: http://127.0.0.1:3001
```

If the user is already running the dev server on 3001, use it and do not restart it.

### Bump the Papyrus pin in a site

After a release is published (`npm view @anthusai/papyrus dist-tags`), edit the same exact version in four files of the site repository, in one pull request:

- `package.json` (`@anthusai/papyrus`)
- `infra/package.json` (`@anthusai/papyrus`)
- `infra/site.json` (`papyrusVersion`)
- `requirements-publication.txt` (`papyrus-newsroom[markus]==X.Y.Z`)

Run `npm install` in both places to refresh the lockfiles. A release that changes the schema or functions deploys the backend with the site, so read the release notes. Merging to the site's `main` deploys it (see README, "How a change reaches production"). Pin stable versions; the `next` tag is for trying a prerelease.

### Deploy

- **A site**: merge its pull request to `main`. Public repositories deploy through Actions OIDC, private ones in AWS. The deploy re-renders the site.
- **App-shell stack**: `cd infra/amplify-app-shell && npm ci`, then `SITE=/abs/path/infra/site.json AWS_PROFILE=papyrus-production npm run diff`, then `npm run deploy` after a human has read the diff.
- **Shared stacks** (`papyrus-monitoring`, `papyrus-procedure-runner`, edge, newsletter sending): hand-run with a change set (`aws cloudformation create-change-set`, then `describe-change-set`, then execute). Each README says which parameters to pass.
- **Engine**: promote `develop` to `main` (see Git workflow); the release publishes the packages. The engine itself deploys nothing to a site.

### Re-project safely

```bash
papyrus ops content project --reconcile --dry-run     # what is behind; deletes nothing
papyrus ops content project --reconcile               # repair; needs the deployed plugin list
papyrus ops content project --all                     # full re-render; never deletes
```

Export the AWS credentials first if the CLI cannot refresh SSO (`eval "$(aws configure export-credentials --profile papyrus-production --format env)"`). A failed projection never fails a save: look at the dead-letter queue and run the dry run ([runbook](docs/site-hosting.md#operations-runbook)).

### Register a site procedure

From the site repository root:

```bash
papyrus procedures register --file procedures/<name>.tac --key <site>.<monitor>.<name> --dry-run --json
papyrus procedures register --file procedures/<name>.tac --key <site>.<monitor>.<name>
```

It validates the procedure with Tactus, derives the parameter schema from its `input` block, bundles the skills its agents name, and stores a new published version (an unchanged digest changes nothing). To start it from a monitor, add `procedureTriggers` and `openaiKeyParameter` to the site's router publication ([procedure runner](docs/procedure-runner.md)).

### Create or change an automation

```bash
papyrus automations list
papyrus automations create --id <site>.<name> --title "..." --monitor <monitor> --publication <site> \
  --procedure <procedure key> --input '{"field":"{placeholder}"}' --dry-run
papyrus automations update --id <site>.<name> --enabled false --max-concurrent 4 --budget-usd 5
papyrus automations run --id <site>.<name> --input '{...}' --dry-run
papyrus automations runs --id <site>.<name> --limit 20
```

`create`, `update` and `run` need `papyrus login` (editor or admin) or `PAPYRUS_GRAPHQL_AUTH=iam`. Monitor triggers and "story enters a stage" event triggers (`--on-stage S --next-stage T`) start anything today ([automations](docs/automations.md)).

### Add a site to the Hacker News routing

1. Add the site's AppSync API id as a parameter and its Reference intake and `relevance_decision_is` grants to `infra/monitoring/papyrus-monitoring.yaml` (follow `RouterDataParadeIntakePolicy` and `RouterDecisionRelationPolicy`; the role's inline policy is size-limited, so use managed policies).
2. Create a change set for `papyrus-monitoring` and read it first.
3. Add the publication to the router config and seed it (the validator refuses a config the router would reject):

   ```bash
   AWS_PROFILE=papyrus-production python3 infra/monitoring/seed_router_config.py --table <table> --file router.json --replace
   ```

   The table name is in SSM `/papyrus/monitoring/table-name`. The publication entry needs `publicationId`, `site` and `appsyncEndpoint`; the site's backend must have exactly one canonical `KnowledgeCorpus`. Keep `mode: dry-run` until the Cyclotron has an output `<publicationId>-relevance` with labels `include` and `exclude`, then flip with `--set mode=live`.
4. Tell the owner of the shared Cyclotron and of monitoring (see Ownership). Details: [monitoring in the cloud](docs/monitoring-cloud.md#the-router-step-4).

### Start a new Papyrus site

The twelve steps are in [README.md](README.md#start-a-new-papyrus-site). The traps: `infra/site.json` must have an `aws` block; the app shell is deployed from this repository's `infra/amplify-app-shell`, not from the site; the four pins must match; Google secrets are set with `papyrus site google-secrets set`; a site with CMS routes behind its own CloudFront needs the Lambda@Edge 404 handler, not `CustomErrorResponses`; and the mission doctrine is data in the backend (`papyrus sections doctrine set`), never a file in the repository.

### Run the weekly knowledge run

Local: [workstation runbook](docs/knowledge-workstation-run.md). Cloud: `aws stepfunctions start-execution --state-machine-arn <arn> --name manual-$(date -u +%Y%m%dT%H%M%S) --input '{"publication":"shipped"}'` ([cloud run](docs/knowledge-cloud-run.md#operating-it)). Both write through the projection lease.

## Board conventions (Kanbus)

`kbs` (Rust) is the board CLI; `kanbus` (Python) is equivalent but slower. Never read or edit `project/` directly, and never `cat` or `jq` issue JSON ([CONTRIBUTING_AGENT.md](CONTRIBUTING_AGENT.md) has the full workflow).

- Run every board command as `KANBUS_REALTIME_BROKER=off kbs ...`. It turns the realtime broker off, which agent sessions do not need.
- Statuses: `open` to `in_progress` to `closed`. A move from `open` to `blocked` is not allowed: go through `in_progress` first, then block.
- `kbs update` does not take `--agent-*` provenance flags on every installed version; if it rejects them, drop them. On `kbs create`, pass `--no-agent-provenance` to silence the provenance warning.
- Hierarchy: initiative, epic, task, sub-task; bug, story and chore hang under any of them. Read ids from the `kbs` output (a create prints the new id; `kbs show <id>` prints the parent).
- Board changes go in via a `board/<slug>` pull request. Record the branch, PR link and verification on the issue before closing it.
- Human review is never a status: use review requests ([docs](docs/review-requests.md)).
- Ryan's board names: the **newsroom board** or **Papyrus board** means the Anth.us publication board (Kanbus key `ANTH`, repository `AnthusAI/anthus-semantic-knowledge-base`, checked out at `~/Projects/anthus-semantic-knowledge-base`); the **product board** or **PPY board** is this repository's. `pods/anthus-blog` is a submodule of that repository, live only after `git submodule update --init`; if `kbs list` there shows no stories you are in the stale empty template.

## Rules, each with its enforcement (layout, content, newsroom, CLI)

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
| GraphQL auth: configured editorial CLI sessions use normal Google/Cognito user-pool auth via `papyrus login`, with renewable secrets in the platform secure store (macOS Keychain, Linux Secret Service/kernel keyring/memory agent, Windows Credential Manager) through the shared `cli-login` library. Operator commands explicitly select IAM; Lambdas keep their managed IAM roles. Never fall back from failed user auth to IAM or use guest/API-key authoring. | `features_backend/cli-user-auth.feature`, `test_cli_user_auth.py`, and `refuse_guest_auth`; provider/client setup and live permission parity require review. See `docs/cli-login.md`. |
| Schema drift is fixed by deploying, never by shims: no runtime introspection, reduced-field fallbacks or dual-shape normalizers. | `npm run test:schema-parity` covers `schema.ts` vs `resource.ts`; shims are unenforced. See [docs/schema-and-api-alignment.md](docs/schema-and-api-alignment.md). |
| No backward-compatibility fallbacks for old schema, GraphQL, content, plan or CLI shapes unless the user asks. Clean breaks. | Unenforced. |
| Published editions set `status`, `editionDate` and `publishedAt`; archive listing depends on `publishedAt`. | Unenforced. Check `curl "$PAPYRUS_BASE_URL/api/archive/editions?limit=1"`; see [docs/production-content-operations.md](docs/production-content-operations.md). |
| BDD fixtures never go in production content records. | Unenforced. |
| `.env*` stays ignored; `.env.example` is the committed template. New required settings go in `.env.example`. | `.gitignore` (`.env*`); `.env.example` completeness is unenforced. |
| Python-first backend: new utilities, CLIs, automation and backend tests are Python. JS/TS is for the frontend and its harnesses. | `npm run check:backend-node-policy`. |

### URLs people see

| Rule | Enforced by |
| --- | --- |
| People never land on, and are never sent to, an `/api/...` URL (Ryan). `/api/*` is only for machine endpoints: form POST targets, RFC 8058 List-Unsubscribe-Post, and JSON. Every page a person opens is a clean page of the site; a route a browser can reach answers with a redirect to one, and email links are clean URLs. | `scripts/test-newsletter-api.ts` and `scripts/test-newsletter-pages-browser.ts` (every redirect and every final URL), `scripts/test-prospectus-sign-in-routes.ts`; other routes unenforced. See [docs/newsletter.md](docs/newsletter.md). |

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
| **Messages come only from people** (Ryan, 2026-10-29; epic PPY-781d26). Nothing creates a `Message` automatically: not votes, monitor deliveries, reports, ontology runs, story-stage moves, form triage or agent Reference notes. A machine result lives on the record it is about (a `Reference` field, a `ModelAttachment`, `Item.metadata.stageMoves`) or is printed, and never gets a replacement log model. Stage 1 (PPY-cd2940) stopped those writers and moved their readers (votes are `curation*` fields on the `Reference`; see [reference curation pipeline](docs/reference-curation-pipeline.md#a-vote-is-recorded-on-the-reference)); the remaining machine Messages are the packets below, the console chat, the forum posts and the console web-context turns (stage 2, PPY-59edce), and the existing machine Messages are deleted in stage 3 (PPY-30eb69). | `features_backend/messages-only-from-people-writers.feature`. Stage-2 writers are unenforced. |
| Research and reporting produce private `Message` packets with `ModelAttachment` payloads, linked `Assignment --produces--> Message`. Only copywriting creates reader-facing draft copy. (Stays until stage 2 of the rule above.) | Unenforced. `features_backend/research-reporting-context.feature` covers orientation traces only. |
| Reporting review (`select`, `merge`, `brief`, `hold`, `kill`) never creates `EditionItem`; edition placement is a later layout step. | `features/newspaper-layout.feature` ("reviews reporting packets without publishing placement"). |
| A story based on a Reference is linked to it (`uses_evidence`, role `based_on`, by lineage ids) and has its own text: never seeded from the Reference's captured text (the copy guard refuses 12+ shared words); only a post's image may be seeded from the preview. Every creation path goes through `create_story_from_references`. | `features_backend/story-from-reference.feature`, `features/newsroom-story-references.feature`, `procedures/newsroom/tests/test_story_from_reference.py`. See [Stories based on a Reference](docs/reference-curation-pipeline.md#6a-stories-based-on-a-reference-core-rules). |
| Only current accepted `Reference` rows feed evidence sets, analysis, publication memory, context packs and edition planning. Packet `proposedReferences` are prospects until intake registers them. | `is_evidence_eligible_reference` in `src/papyrus_newsroom/reference_policy.py` is the single gate where callers use it; coverage of every consumer is unenforced. See `skills/reference-intake/SKILL.md`. |
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

## Ownership and coordination

Roles as of 2026-10-23. Ryan decides priorities; when unsure who owns a thing, ask in the session that started it rather than guessing.

- **Engine (this repository)**: the Papyrus implementation sessions. Releases are cut here; site sessions consume them by pin.
- **Site repositories**: each site has its own implementation session (for example the Shipped session owns shipped.anth.us and `AnthusAI/Shipped-web`). Do not change a site repository from an engine task except for an agreed pin bump.
- **Shared infrastructure**: `papyrus-monitoring` (collectors, router, its AppSync grants), `papyrus-procedure-runner`, the knowledge run and projection lease table, the edge stacks and the newsletter sending stacks serve several sites. Tell Ryan and the session that last changed the stack before a change set is executed, and never run two deploys of one stack at once.
- **Prospectus**: tell the Prospectus session before merging to Prospectus `main`; deploys must not overlap. Anth.us is never touched without explicit instruction.
- **Cyclotron**: the shared relevance Cyclotron belongs to the Cyclotron sessions. Adding a publication output or binding is a request to them.
- **Spend**: use the models a task names; do not start paid or model-calling runs that were not requested.

## Current state (2026-10-23)

- **Live**: standard Markus projector and the edge handler on Markus sites; newsletters on Shipped; reader-steering code and Proposals (reader writes closed in production); monitoring and router (dry-run or live per the router config); procedure runner for Distinctive Mark's TTAB analysis; automations slices 1 and 2; the cloud knowledge run (Shipped first); GA4 with Consent Mode v2.
- **Merged, awaiting a release and a data API deploy per site**: review requests and the Notification Center home (#642, PPY-ab6a50 and PPY-1cd261, under PPY-9ff95b).
- **In progress**: the idea pipeline beyond v0 (PPY-8ffc18: scheduling and weekly trends; unattended runs cannot file Proposals because `fileProposal` is not open to IAM); outbound newsletters beyond Shipped (PPY-31455f); publication-agnostic Monitoring (PPY-2d77c8).
- **Planned**: automation outputs go to review by default (PPY-2b4bda); schedule, event and manual automation triggers; Data Parade binding into the shared Cyclotron (PPY-cad5f6, blocked); votes and flags checking that their subject exists (PPY-d9e384).
- **Known stale docs**: `docs/standard-site.md` and `packages/README.md` still describe the packages as a spike that publishes nothing (they publish; see `docs/releasing.md`); `docs/newsletter.md` opens with "not yet enabled on any site" (Shipped has it on). Prefer README.md and the topic pages when they disagree.

Epics and ids: PPY-9ff95b (automation), PPY-991a32 (Shipped engine support), PPY-bcfd2d (standard front end), PPY-1f1489 (four-site alignment), PPY-ad3da5 (one content item, one lifecycle).

## Where things live

- Documentation: [docs/README.md](docs/README.md), grouped by task.
- The board: Kanbus project `PPY` (`KANBUS_REALTIME_BROKER=off kbs list`); the wiki under `project/wiki/` is the only part of `project/` you may edit directly.
- Skills for agents: `skills/` and `.agents/skills/`.

## Verification

Before opening a PR run what the change touches: `npm run lint`, `npm run typecheck`, `npm run build`, `npm run test:bdd`, `npm run test:bdd:backend`, `npm run test:bdd:operator-cli`, and the relevant `npm run test:*` scripts. Amplify, archive and browser smoke checks: [docs/verification.md](docs/verification.md). CI runs `.github/workflows/tests.yml` (not every local script is wired in). Use the dev server on port 3001 if the user is running it, and do not restart it.

Everything else is in [docs/README.md](docs/README.md). Kanbus mechanics are in [CONTRIBUTING_AGENT.md](CONTRIBUTING_AGENT.md).
