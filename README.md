# Papyrus

Papyrus is an open-source engine for a continuous, steerable feed of insight about a subject. It watches sources, decides what is relevant from an editor's include and exclude decisions, has editor agents research, write and check up to the publication's policies, and publishes the result for people and agents. The subject is configuration (doctrine, sections, corpus, steering), never code.

This repository is the **engine**. It ships two packages in lockstep, `@anthusai/papyrus` on npm and `papyrus-newsroom` on PyPI, and every Papyrus site installs both at one exact version. A site repository holds only what is specific to that site. Fix the engine here, release it, then bump the pin in the site. Do not copy engine code into a site.

New to the repo? Read this page, then [AGENTS.md](AGENTS.md) (the operating manual for agents and people), then the [docs index](docs/README.md).

## How it relates to the other repositories

| Repository | Role |
| --- | --- |
| **Papyrus** (this repo) | The engine: the newsroom console, the CMS backend (Amplify Gen 2), the standard Markus projector, the `papyrus` CLI, plugins, infrastructure templates and the shared monitoring and procedure stacks |
| Site repositories, for example `AnthusAI/Shipped-web`, `Distinctive-web`, `Pilobol.us`, `Anth.us-Papyrus`, `Threat-Intelligence`, `p.apyr.us`, `DataParade-newsroom` | One per site: `papyrus.config.ts`, `web/projection.json`, theme, `infra/site.json`, the exact Papyrus pins. They are generic containers; sections, missions and scoring live in the site's backend data |
| **Cyclotron** (`AnthusAI/Cyclotron`) | The decision engine. One shared relevance Cyclotron answers include/exclude for the Hacker News router and several sites. The `cyclotron` Poetry group in this repo pins its commit |
| **Prospectus** (`AnthusAI/Prospectus`) | Accounts and sign-in for reader sites. A site's reader features open when Prospectus returns a per-site subject (see [reader steering](docs/reader-steering.md#the-switch-on-condition)). Tell the Prospectus owner before merging to its `main` |
| **Biblicus** | The knowledge layer (corpora, topic models, extraction). Installed from PyPI (`biblicus >=1.15.0`) |
| **Tactus** | The procedure runtime. Newsroom procedures are `.tac` files run by Tactus (`tactus >=0.53.4`) |
| Markus (`anthus-markus`) | The content markup and renderer behind Markus sites (`papyrus-newsroom[markus]`) |
| Kanbus | The work board (project key `PPY`) and its `kbs` CLI |

## Where it runs

- **AWS account `papyrus-production`, id `712236451410`, region `us-east-1`** hosts the sites that belong to the Papyrus platform: Shipped, Distinctive Mark, Pilobol.us, Anth.us, Threat Intelligence, p.apyr.us and Data Parade. Use `AWS_PROFILE=papyrus-production` (SSO; only the person can run `aws sso login`). Sites whose product has its own account (Apricity, Auritus, Kanbus, Cyclotron and Prospectus, Chattic.us) are deployed there instead; each site records its account in `infra/site.json` under `aws`. See [Which account hosts a site](docs/site-hosting.md#which-account-hosts-a-site).
- **Shared stacks** (hand-run CloudFormation or CDK in `712236451410`): `papyrus-monitoring` (collectors and the router), `papyrus-procedure-runner`, the knowledge cloud run and the projection lease table (`infra/scheduled-jobs`), `papyrus-newsletter-sending-<siteId>` (SES), and one edge stack `papyrus-edge-<siteId>` per site.
- **Per site**: a CMS Amplify app (`<siteId>-cms`, platform `WEB_COMPUTE`) that owns the backend (AppSync, DynamoDB, Lambdas, S3), a versioned S3 site bucket, and the site's own CloudFront distribution (`papyrus-edge-<siteId>`, an origin access control to the bucket, `/newsroom*`, `/_next/*` and `/api/*` going to the CMS app). Amplify app ids and distribution ids live in each site's `infra/site.json` (Shipped: app `dkycd9pntgo6d`, distribution `EUQZ249T4OKXH`, `https://shipped.anth.us`).
- **Hosts**: `shipped.anth.us`, `distinctive-mark.com`, `pilobol.us`, `anth.us`, `threat-intelligence.anth.us`, `p.apyr.us`, `dataparade.io/posts`. Editors sign in with Google at `/newsroom`.
- **Legacy account `335163751677`** still holds personal sandboxes (see [aws-sandbox-personal](docs/aws-sandbox-personal.md)) and stale pre-move copies of some apps. Do not create or change production resources there. A gitignored `AGENTS.local.md` on a developer machine may describe that account as production; the repository docs are the reference.

The runtime picture, in short:

- **Save is live.** For a Markus site (`s3-projection`, the default for new sites) the `content-actions` Lambda saves an item and renders only the pages that depend on it into the S3 bucket; CloudFront serves it. There is no build job.
- **Git holds code, theme and settings, not articles.** Content lives in DynamoDB and the site can always be re-projected with `papyrus ops content project --all`.
- **Pretext** (a Next.js server on Amplify that renders on request) is the alternative publication kind, used by Threat Intelligence and p.apyr.us.
- **Local vs cloud.** `papyrus` runs against a local pod or the cloud GraphQL API with the same argv (`--backend local|cloud`, [operator CLI](docs/operator-cli.md)). Procedures run locally under Tactus or in the cloud in the procedure runner Lambda. The weekly knowledge run runs on a workstation ([runbook](docs/knowledge-workstation-run.md)) or unattended in AWS ([cloud run](docs/knowledge-cloud-run.md)). The Hacker News collector has a local SQLite worker and the cloud stack ([monitoring](docs/monitoring-cloud.md)).

Detail: [How a publish flows](docs/how-a-publish-flows.md), [Site hosting](docs/site-hosting.md), [the standard site design](docs/standard-site.md).

## What exists today

Status words: **Live** (in production on at least one site), **Beta**, **In progress**, **Planned**.

- **Standard Markus projector and front end.** One renderer for every Markus site, driven by `web/projection.json`: pages, listings, tags, sitemap, feeds, Markdown twins, `llms.txt`. Live. [Building a static site](docs/building-a-papyrus-static-site.md), [agent-readable sites](docs/agent-readable-sites.md).
- **Plugins and the edge.** Deploy-time plugins (`signup`, `newsletter`, `reader-steering`) and the `papyrus-edge-*` CloudFront stacks with the Lambda@Edge 404 handler for sites that mix S3 and the CMS app (#560). Live. [Plugins](docs/plugins.md), [edge README](infra/edge/README.md).
- **Reader steering.** Votes on any subject, flags, ratings, comments, submissions, moderation, snapshots, and Proposals (PPY-c97ce4, PPY-409d96). Built and tested; reader writes stay closed in production until Prospectus returns a site subject. [Reader steering](docs/reader-steering.md).
- **Newsletter.** Double opt-in, clean `/newsletter/*` pages, branded email theme, roundup issues, alerts, paced sending through SES. Live on Shipped. [Newsletter](docs/newsletter.md).
- **Analytics.** GA4 with Consent Mode v2, a first-party banner and address redaction. `analytics_only` exists and stays off on every site. [Site hosting: Analytics](docs/site-hosting.md#analytics-google-analytics-4).
- **Monitoring and the router.** The collector and router (`papyrus-monitoring`) and the Monitoring page. The shared relevance Cyclotron decides which Hacker News items each site wants (Anth.us, p.apyr.us, Threat Intelligence, Data Parade, Pilobolus); the TTAB monitor feeds Distinctive Mark directly. Beta. [Monitoring](docs/monitoring-cloud.md), [steering and relevance](docs/steering-and-relevance.md).
- **Procedure runner and site procedures.** A site registers its own Tactus procedure with `papyrus procedures register`; the runner executes it in the cloud when a monitor delivers a new Reference. Live for Distinctive Mark. [Procedure runner](docs/procedure-runner.md).
- **Knowledge run.** Weekly topic model, extraction, AI review, snapshot, archive, wiki and projection, local or unattended in AWS, guarded by the projection lease. Beta (Shipped first). [Cloud run](docs/knowledge-cloud-run.md).
- **Automations.** Records that bind a monitor to a procedure, with `enabled`, concurrency and budget limits, cost and run history, and Run now (PPY-9ff95b slices 1 and 2). Monitor triggers are live; schedule, event and manual triggers are stored but not started. [Automations](docs/automations.md).
- **Idea pipeline v0.** `papyrus ideas digest` and `synthesize` turn recent references into private story ideas, run by hand, filed as Items at the `idea` stage (the Idea column of the Stories board, marked "Generated"; `--store json` keeps local files only). Merged to `develop`; `papyrus ideas trends` writes cited trend ideas from the weekly knowledge snapshot (citation check, figure spec, dry run). `papyrus ideas monitor-stories` writes cited story ideas about the items a site's monitors found, any source, ranked by the relevance Cyclotron's verdict. Scheduling is in progress (PPY-8ffc18). [Idea pipeline](docs/idea-pipeline.md).
- **Review requests and the Notification Center** as the console home: flags, timed soft reviews and hard gates, ignore-safe, with steering read back by the step that raised them (`papyrus reviews`). Merged to `develop` (#642, PPY-ab6a50, PPY-1cd261); it takes effect on a site only after that site's data API is deployed with a release that has it. In progress: email, filters and ground-truth correction. [Notification Center](docs/notification-center.md), [review requests](docs/review-requests.md).
- **Reconcile guard.** A reconcile refuses to run without the deployed plugin list and never deletes a plugin's pages (#594). Live. [Site hosting: reconcile](docs/site-hosting.md#the-dead-letter-queue-and-reconcile).
- **Pretext newspaper layout lab, newsroom, knowledge base, editor agents.** Live. [Layout system](docs/layout-system.md), [newsroom operations](docs/newsroom-operations.md), [editor agents](docs/editor-agents.md).

## Quick start

Prerequisites: Node 22 and npm, Python 3.12 or 3.13 (CI uses 3.12), [Poetry](https://python-poetry.org/), [`kbs`](https://github.com/AnthusAI/Kanbus) for the board, and an AWS SSO profile for anything that touches the cloud.

```bash
npm ci
poetry install --extras "newsroom markus priming" --with cyclotron   # what CI installs
poetry run papyrus --help
echo '{}' > amplify_outputs.json     # git-ignored stub so the type check resolves; no secrets
npm run typecheck
npm run lint
npm run dev:preview                  # seeded newsroom at http://127.0.0.1:3002/newsroom/work, no AWS
```

Other local servers: `npm run dev:127` serves the app on `http://127.0.0.1:3001` and needs a real `amplify_outputs.json` (`npm run outputs:sandbox` or `npm run outputs:production`). `cp .env.example .env` holds app-level settings only, never credentials; the shell environment wins over `.env`.

Tests (what CI runs is in `.github/workflows/tests.yml`):

```bash
npm run test:bdd:backend                                  # behave: features_backend/
poetry run pytest -q procedures/newsroom/tests/test_ideas.py   # one Python test file
npm run test:schema-parity                                # schema.ts against resource.ts
npm test                                                  # all scripts/test-*.ts and Lambda tests
npm run test:bdd                                          # cucumber: layout and reader (needs Playwright chromium)
```

More: [verification](docs/verification.md), [Python CLI and testing](docs/python-cli-and-testing.md), [local preview](docs/local-preview.md).

## How a change reaches production

1. **Branch from `origin/develop`** (`feature/PPY-xxxxxx-slug`, `fix/...`, `chore/...`, `docs/...`) and open a pull request to `develop`. Behaviour changes ship with Gherkin specs.
2. **CI** (`tests.yml`, plus `package-smoke.yml` when packages, app or Python code changes) runs the type check, lint, the TypeScript tests, the app-shell CDK build, the Python tests and the pilot-identifier guard. Merge to `develop` with a merge commit once it is green.
3. **A push to `develop` publishes a prerelease** `X.Y.Z-next.N` (npm dist-tag `next`, PyPI `X.Y.Z.devN`).
4. **Promote `develop` to `main` with a pull request and a merge commit** (never a squash). A push to `main` runs `release.yml`: semantic-release (conventional commits) cuts the stable version and publishes `@anthusai/papyrus` to npm and `papyrus-newsroom` to PyPI at the same number, through trusted publishing (OIDC), with no stored tokens. `feat:` releases a minor, `fix:` a patch, `feat!:` or `BREAKING CHANGE` a major. `chore:`, `docs:`, `test:`, `refactor:` and `ci:` do not release. Versions are stamped into the staged packages and never committed back. Agents promote only when told to; see [AGENTS.md](AGENTS.md#git-workflow).
5. **A site picks up a release by bumping its pin** by hand in four places: `package.json`, `infra/package.json`, `infra/site.json` (`papyrusVersion`) and `requirements-publication.txt` (`papyrus-newsroom[markus]==X`). Merging that to the site's `main` deploys it:
   - **Public site repositories** run Actions CI, and a green push to `main` starts the Amplify job through GitHub OIDC (the reusable workflow `.github/workflows/amplify-deploy.yml`). Amplify auto-build is off on `main`.
   - **Private site repositories** run all CI and CD in AWS (Amplify auto-build or CodePipeline).
   - The deploy renders the whole site again (`reprojectOnDeploy`), so merging is the only step. Backend changes ride the same deploy.

Details: [Releasing](docs/releasing.md), [Deploy on merge to main](docs/site-hosting.md#deploy-on-merge-to-main). This repository's own `main` does not deploy a site; the engine ships as packages. Production deploys through `ampx pipeline-deploy` are never run from a laptop.

## Start a new Papyrus site

The steps below are the real sequence; each links to the page that holds the detail. A site repository starts from the layout of a recent one (Shipped-web is the cleanest example) and contains no engine code.

1. **Create the site repository** with `papyrus.config.ts` (`defineSite`), `web/projection.json`, `web/css/`, `amplify.yml`, `infra/site.json` and `requirements-publication.txt`. [Building a static site](docs/building-a-papyrus-static-site.md), [standard site layout](docs/standard-site.md).
2. **Write `infra/site.json`** with an `aws` block (`profile`, `accountId`, `region`). There is no default account, and a file without `aws.accountId` and `aws.region` fails with `does not say where it deploys`. Also set `cms.cognitoDomainPrefix` (distinct per site), `cms.siteOrigin` for a site behind its own edge, and the `github` block with `ownerId` and `repoId`. Examples: [`infra/amplify-app-shell/examples/`](infra/amplify-app-shell/examples), reference: [app-shell README](infra/amplify-app-shell/README.md).
3. **Pin the engine** to one released version in the four places listed above.
4. **Deploy the app shell** from a Papyrus checkout (a human approves the change set; connect the GitHub App once per app and approve a new CodeConnections connection by hand):

   ```bash
   cd infra/amplify-app-shell && npm ci
   SITE=/absolute/path/to/site/infra/site.json AWS_PROFILE=papyrus-production npm run diff
   SITE=/absolute/path/to/site/infra/site.json AWS_PROFILE=papyrus-production npm run deploy
   ```

   [Deploying the app-shell stack](docs/site-hosting.md#deploying-the-app-shell-stack-from-a-checkout), [GitHub App connection](docs/site-hosting.md#one-time-github-app-connection-per-app).
   **First backend build: two deploys.** The full backend is more than CloudFormation's 2,500-resource limit per operation, so a new site's first build runs with the Amplify branch variable `PAPYRUS_BOOTSTRAP_STAGE=1`, then a second build without it. [Exact commands](docs/site-hosting.md#start-a-new-papyrus-site-the-two-deploy-first-backend).

5. **Secrets.** Create the site's Google OAuth client, then from the site repository run `papyrus site google-secrets set` (it stores SSM SecureString secrets after asserting the account) and `papyrus site google-secrets check`. Add editors to a Cognito group after their first sign-in. [Google sign-in](docs/site-hosting.md#google-sign-in), [OAuth setup](docs/google-oauth-setup.md).
6. **Edge.** Give the site its own CloudFront: `backend.publication.distribution` in `papyrus.config.ts`, or a `papyrus-edge-<siteId>` stack from `infra/edge/s3-projection-cms.yaml` (use this one when `/newsroom*` and `/api/*` share the host: it carries the 404 handler). DNS and certificates: [edge README](infra/edge/README.md), [own CloudFront](docs/site-hosting.md#own-cloudfront-in-front-of-the-bucket-papyrus-edge-).
7. **First content and projection.** `papyrus publication init --key <key> --name <name>`, then `papyrus ops content project --all`. [How a publish flows](docs/how-a-publish-flows.md).
8. **Mission doctrine.** Write the mission (three lines: what it is and for whom, what coverage includes, what readers take away) and the policy, then `papyrus sections doctrine set --kind mission --file mission.md` and `--kind policy`. The relevance Cyclotron seeds its rubric from them. [Editorial context](docs/editorial-context.md), [steering and relevance](docs/steering-and-relevance.md).
9. **Newsletter (optional).** Deploy the SES stack `infra/newsletter/papyrus-newsletter-sending.yaml` for the site, then enable the `newsletter` plugin in `papyrus.config.ts`. SES starts in the sandbox. [Newsletter](docs/newsletter.md), [sending stack](infra/newsletter/README.md).
10. **GA4 (optional).** `chrome.ga_measurement_id` plus `chrome.consent_mode` in `projection.json` (the standard Consent Mode v2 banner; leave `analytics_only` off). [Analytics](docs/site-hosting.md#analytics-google-analytics-4).
11. **Hacker News routing (optional).** Add the site's AppSync grants to `infra/monitoring/papyrus-monitoring.yaml`, deploy `papyrus-monitoring` with a change set, add the publication to the router config with `infra/monitoring/seed_router_config.py`, and make sure the shared Cyclotron has a `<publicationId>-relevance` output. The router starts in `dry-run`. [Monitoring: the router](docs/monitoring-cloud.md#the-router-step-4), [AGENTS.md](AGENTS.md#add-a-site-to-the-hacker-news-routing).
12. **Register the site in Prospectus** if it has reader features (`cms.prospectusAccountsApiStageArn`). [Reader steering](docs/reader-steering.md#enabling-it).

## Where to read next

- [AGENTS.md](AGENTS.md): the operating manual, hard rules, common tasks with exact commands, ownership and current state.
- [docs/README.md](docs/README.md): the index of every documentation page, grouped by task.
- [CONTRIBUTING_AGENT.md](CONTRIBUTING_AGENT.md): the Kanbus workflow ("The Way") for the PPY board.
- [docs/code-map.md](docs/code-map.md): where the main files live.

---

Built by [Anthus AI Solutions](https://anth.us). We run this class of system in production. If you need this operated, not just cloned, [talk to us](https://anth.us).
