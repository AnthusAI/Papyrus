# Site hosting options

Status: **Config types live on `SiteBrand`** (`renderer`, `hosting`, `themePack`,
`opsChrome` in `lib/site-brand.ts`). This file is the hosting runbook for both
publication kinds: Markus sites projected into S3 behind CloudFront
(`s3-projection`) and Pretext sites on Amplify SSR.

Kanbus: PPY-17fcfc (original hosting design), PPY-23a743 (static projection).
Live examples: [Pilobol.us](https://github.com/AnthusAI/Pilobol.us) on
**pilobol.us** and [Anth.us-web](https://github.com/AnthusAI/Anth.us-web) on
**anth.us**, both served from an S3 projection. The picture of how the parts
fit is in the [README](../README.md#how-a-papyrus-publication-fits-together);
editors read [How a publish flows](how-a-publish-flows.md).

## Publication kinds at a glance

| | Markus, `s3-projection` | Markus, Amplify reader (legacy) | Pretext, Amplify SSR |
| --- | --- | --- | --- |
| Where pages live | Static files in a versioned S3 site bucket | Static build output on an Amplify `WEB` app | Rendered on request by a Next.js server (`WEB_COMPUTE`) |
| What serves them | Our own CloudFront stack (`papyrus-edge-<site>`) with edge functions | Amplify's CDN | Amplify's CDN in front of the compute |
| What a Save does | The `content-actions` Lambda renders only the affected pages and invalidates their paths | Starts an Amplify build of the whole site | Calls the reader's `/api/revalidate` |
| Save to visible | Seconds (see [Publish to visible](#publish-to-visible)) | Minutes (a full build) | Up to about two minutes |
| Apps per site | One (the CMS) | Two (CMS and reader) | One |
| Status | Kind for new Markus sites | Being retired (see [Migrating](#migrating-from-the-amplify-reader)) | Unchanged |

## Configuration axes (do not collapse them)

A Papyrus publication is configured along **independent** axes:

| Axis | Values (today) | Notes |
| --- | --- | --- |
| **Theme pack** | `papyrus` \| `threat-intelligence` \| `pilobol-us` | Ops / Shadcn colors. See [site-theme-packs.md](site-theme-packs.md) |
| **Ops chrome** | `app` \| `newsprint` | Newsroom shell. Independent of renderer |
| **Renderer** | `pretext` \| `markus` | Publication / reader output only |
| **Layout** | `newsprint` \| `blog` \| `magazine` | Pretext-internal only |
| **Publication** | title / property | e.g. P.apyr.us, Threat Intelligence, Pilobolus |
| **Hosting** | see `HostingConfig` below | Where built artifacts are served |

Do not fold hosting into renderer choice, theme pack into renderer, or ops
chrome into the reader stack. Do not invent a per-publication Papyrus GitHub
fork (the Threat Intelligence shape: separate product repo + dedicated
`WEB_COMPUTE` app baked into one checkout).

## `HostingConfig` (documented shape)

PPY-eca592 will add this as a sibling of `RendererConfig` on `SiteBrand`. Until
then, treat this file and the templates under `docs/hosting/` as the contract.

```typescript
type HostingConfig =
  | { kind: "amplify-ssr" }      // Amplify WEB_COMPUTE. Next.js. GraphQL at request time.
  | { kind: "amplify-static" }   // Amplify WEB. Build emits HTML/CSS/assets. New copy = new build.
  // Union left open: github-pages, s3-cloudfront, …
```

Do not add a required-but-ignored hosting field on Markus sites before eca592
lands.

A Markus brand that still runs the Shadcn CMS on Amplify SSR (for example the Pilobol.us CMS app) builds with `next build`, but its reader routes (`/articles/[slug]`, `/[year]/[month]/[day]`) are not served by Next.js. Their `generateStaticParams` return `[]` and the pages respond `notFound()`, even when the backend holds published articles; the reader is built separately by `markus-build`.

## Amplify platform mapping

| `HostingConfig.kind` | Amplify platform | Build output | Content at runtime |
| --- | --- | --- | --- |
| `amplify-ssr` | `WEB_COMPUTE` | `.next/` (Next.js SSR/ISR) | AppSync GraphQL, signed Storage URLs |
| `amplify-static` | `WEB` | `web/dist/` (or equivalent) | Static files only; no server |

### Intended pairings

| Hosting | Renderer | Example |
| --- | --- | --- |
| `amplify-ssr` | `pretext` | p.apyr.us, Threat Intelligence |
| `amplify-static` | `markus` | **pilobol.us**, future Markus publications |

These are common pairings, not locks. Ops theme pack and `opsChrome` are chosen
separately — a Markus reader may still use Shadcn `/newsroom`. Full mix table:
[site-stacks.md](site-stacks.md).

Invalid combos can exist in theory (`pretext` + static is a poor fit today).
Document pairings; do not ship a fake static Pretext pipeline.

## Split reader + CMS (Pilobolus, legacy)

This section describes the **Amplify reader** shape that Pilobol.us and Anth.us
ran before they moved to the S3 projection (see
[Migrating from the Amplify reader](#migrating-from-the-amplify-reader)). A site
that still has a reader app, or a new site that opts out of `s3-projection`,
uses it.

Some publications ship **two** Amplify apps:

| App | Repo | Platform | Domain | Serves |
| --- | --- | --- | --- | --- |
| Reader | `AnthusAI/Pilobol.us` | `WEB` | `pilobol.us` | Markus static HTML |
| CMS | `AnthusAI/Papyrus` + `PAPYRUS_SITE_BRAND=pilobol-us` | `WEB_COMPUTE` | `newsroom.pilobol.us` | `/newsroom`, AppSync, corpus S3 |

Threat Intelligence uses one repo + one `WEB_COMPUTE` app for both reader and
CMS. Pilobolus uses the split pattern so the Markus reader can iterate on its
own build while the Papyrus backend evolves independently.

Runbook: [`publications/pilobol_us/docs/bootstrap.md`](../publications/pilobol_us/docs/bootstrap.md).

**Anti-pattern:** importing Pilobolus corpus data into the p.apyr.us app
(`dbsyytcm9drqa`) or expecting `/newsroom` on the static reader app
(`d1od6t7lzbwanr`).

## How a new publication opts in

1. **Choose axes** — theme pack, ops chrome, renderer, layout (if Pretext), publication identity, hosting kind.
2. **Publication repo** — pod/content repo (e.g. `AnthusAI/Pilobol.us`), not a second
   Papyrus product fork.
3. **Build spec** — copy the template for your hosting kind:
   - Static Markus: [`docs/hosting/amplify-static.yml.example`](hosting/amplify-static.yml.example)
   - SSR Pretext: [`docs/hosting/amplify-ssr.yml.example`](hosting/amplify-ssr.yml.example)
     (Papyrus root `amplify.yml` is the live reference).
4. **New Amplify app** — one app per publication; platform `WEB` or `WEB_COMPUTE`
   matching the template. Do not reuse the Papyrus production app (`dbsyytcm9drqa` /
   p.apyr.us) for a Markus pod.
5. **DNS** — Route 53 public hosted zone for the publication domain; comment NS
   records for the registrar; attach the apex in Amplify domain management.
6. **CI invariants** — repo-committed Markdown; `markus convert` **without**
   `--allow-html` for static Markus builds.

Example domain: **pilobol.us** (publication **Pilobolus**, git repo
`AnthusAI/Pilobol.us`). The old spelling `pilobil.us` was a typo — do not create
that zone.

## Static Markus path (amplify-static, legacy reader)

Used by sites that still have an Amplify reader app. A site on the S3
projection has no build: pages are written by the projection Lambda and the
rest of this section does not apply to it.

Typical publication repo layout:

```text
amplify.yml              # WEB platform; no backend phase
web/
  build.py               # markus convert --fragment --no-css; wraps HTML shell
  content/               # Markdown sources (committed)
  css/                   # Site theme over vendored Markus CSS
  dist/                  # Build output (gitignored; CI artifact)
```

Markus install for Amplify CI (not on PyPI today):

```yaml
pip install "git+https://github.com/AnthusAI/Markus@v0.7.0"
```

See the static template for the full `amplify.yml`.

### Real 404s for missing pages

(Amplify reader only. On the S3 projection the same result comes from
CloudFront error responses; see [The 404 page and its headers](#the-404-page-and-its-headers).)

Redirects and the not-found page are **Amplify app config** (`customRules`),
not part of `amplify.yml`. Measured on Amplify `WEB` apps (PPY-fdb5e9):

| `customRules` catch-all `/<*>` -> `/404.html` | Missing page |
|---|---|
| none | HTTP 404 with an **empty body** (Amplify does not serve `404.html` by itself) |
| status `404` | **302 -> `/404.html` (200)**: dead URLs look alive to crawlers. Do not use. |
| status `404-200` | **HTTP 404 with the `404.html` body at the requested URL.** Use this. |

Despite the name, `404-200` is the only setting that gives a true 404 with the
custom page. Keep the catch-all **last**, after any 301 rules. The build must
emit `404.html` at the artifact root. A missing path without a trailing slash,
or ending in `.html`, first gets Amplify's own 301 to the directory-style URL,
then the 404. Verify with a random missing path (expect 404 and the custom
body), for example Anth.us-web `bin/check-404.py <base-url>`.

The `amplify-app-shell` template sets this catch-all (`/<*>` -> `/404.html`,
`404-200`) on every generated reader app, so a `markus-static` reader must emit
`404.html` at its artifact root.

### Optional reader settings (`site.json` `reader`)

All are optional; omitting them leaves the generated reader unchanged
(a single apex domain setting, the single `/<*>` 404-200 rule, no custom
headers, the fixed export-then-build spec).

| Field | Effect |
| --- | --- |
| `domainPrefixes` | Domain sub-domain prefixes on the reader branch, for example `["", "www"]`. Default `[""]` (apex only). Requires `domainName`. |
| `redirects` | `[{ source, target, status }]` app-level rules (`status` is `301` by default; also `302`, `200`, `404`, `404-200`). Emitted before the 404 catch-all, which stays last. Reset-proof, unlike rules applied after deploy. |
| `customHeaders` | `[{ pattern, headers }]` written to the app's `customHeaders`, for example `**/*.html` with a `Cache-Control` value. |
| `preBuildCommands` | Extra reader `preBuild` commands, run after Python provisioning and before the content export (for example a submodule checkout). |
| `skipContentExport` | `true` omits `papyrus ops content export-published` for a reader that builds from its own repo content. |

## SSR Pretext path (amplify-ssr)

Papyrus itself: Next.js + Amplify Gen 2 backend (`ampx pipeline-deploy`),
artifacts under `.next/`, platform `WEB_COMPUTE`. Reader traffic hits AppSync
at request time. **Do not copy this `amplify.yml` onto a Markus static pod.**

Pretext sites (and the staging app) ship `amplify_outputs.json` into the SSR
bundle: the generated build spec copies it to `.next/amplify_outputs.json` AFTER
`npm run build` (the build recreates `.next/`), and the runtime finds it there
when the checkout-root copy is absent. Do not set `PAPYRUS_AMPLIFY_OUTPUTS` in
`.env.production`: `next build` loads that file and reads the path during page
data collection, before the copy exists, which fails the build.

## One-time GitHub App connection per app

The app shell (`@anthusai/papyrus/infra`, driven by the publication's
`infra/site.json`) creates Amplify apps with no repository and no access token.
Amplify only builds from GitHub after the **Amplify GitHub App** is connected
to each app. This is a console step: there is no API for the handshake. It
replaces the old PAT in Secrets Manager (`amplify/github-app-token`); delete
that secret once every app is connected.

Per app (`<siteId>-cms`, then `<siteId>-reader` for static sites):

1. Record the app's state first: `aws amplify get-app --app-id <id>` and note
   `platform`, `iamServiceRoleArn` and `computeRoleArn`.
2. AWS Console, **AWS Amplify**, **All apps**, choose the app.
3. **Hosting** (or the **Connect repository** banner), **Connect repository**.
4. Choose **GitHub**, **Continue**.
5. In the GitHub pop-up, **Install & authorize** the **AWS Amplify** GitHub App
   for the `AnthusAI` organization, with access to only the site's repository.
6. Back in Amplify pick repository `AnthusAI/<repo>` and branch `main`, **Next**.
7. The wizard asks for a service role and build settings. The template already
   set both, so do **only** the GitHub connection: if it offers to create a new
   service role, choose the existing template role (named like
   `amplify-app-shell-<siteId>-AmplifyServiceRole...`) instead. **Save and deploy**.
8. Run `aws amplify get-app --app-id <id>` again and compare (see below).
9. If the stack has `cms.staging` enabled and the `staging` branch is missing,
   add it under **Hosting**, **Branches**, **Connect branch**.

Record the date in the site's runbook.

### Verify and repair after connecting

Connecting a repository to a repo-less app works and keeps the same app id; the
repository, a service role and a first build are set (proven 2026-10-06, the
build succeeded). Two side effects were observed, so always diff `get-app`
before and after:

- **Platform flip.** The console runs framework auto-detection on the repository
  and changed the CMS app's `platform` from `WEB_COMPUTE` to `WEB` when the repo
  was README-only. A real Next.js repository should detect as `WEB_COMPUTE`, but
  verify. Fix:

  ```bash
  aws amplify update-app --app-id <id> --platform WEB_COMPUTE
  ```

  The reader app stays `WEB`.
- **Service role replaced.** The console created a new role
  (`amplifyconsole-backend-role`, `AdministratorAccess-Amplify`) and attached it
  to the app. The CMS app needs the template's role (`AdministratorAccess`, for
  `ampx pipeline-deploy`) and the reader app its least-privilege role. If
  `iamServiceRoleArn` changed, restore the value you recorded before connecting
  (the template's role is also listed by
  `aws cloudformation describe-stack-resources --stack-name amplify-app-shell-<siteId>`):

  ```bash
  aws amplify update-app --app-id <id> --iam-service-role-arn <template service role arn>
  ```

  Re-deploying the app-shell stack also restores it, but only if CloudFormation
  sees drift, so prefer the explicit command. Delete the stray
  `amplifyconsole-backend-role` once nothing uses it.

- **Branches recreated, environment variables lost.** The console flow deleted the
  stack's `main` and `staging` branches and recreated only `main`, with no
  environment variables (observed 2026-10-06 on the Pilobol.us CMS). Without
  `PAPYRUS_COGNITO_DOMAIN_PREFIX` and `PAPYRUS_OAUTH_REDIRECT_URLS` the backend build
  creates no Cognito domain and the CMS login fails with "oauth param not
  configured". `PAPYRUS_OAUTH_REDIRECT_URLS` may list bare origins: the backend adds the
  `<origin>/newsroom` and `<origin>/` callback and logout variants itself, newsroom
  first (no `/newsroom` on a CMS-only host with `newsroomBasePath: ""`), and the
  template validation accepts an origin with or without a path. Check with
  `aws amplify list-branches --app-id <id> --query 'branches[].[branchName,environmentVariables]'`.
  CloudFormation does not see this as drift. Recreate the `staging` branch first
  (**Hosting**, **Branches**, **Connect branch**), then deploy the stack with a change
  to the branch variables so CloudFormation rewrites them on both branches.

Run these with the profile and region from `AGENTS.local.md`. Domains and the
staging branch are optional in `site.json`, so an app can be stood up and proven
on its default `amplifyapp.com` URL first and given domains later (see
[Custom domains and Route 53](#custom-domains-and-route-53)).

### Python 3.12 in Amplify builds

The Amplify AL2023 build image defaults to Python 3.10 (per AWS docs; not yet
verified on a real build), and `papyrus-newsroom` needs 3.12. Generated build
specs that run Python install `uv`, then `uv python install 3.12`,
`uv venv --python 3.12 .venv` and
`uv pip install --python .venv "papyrus-newsroom[markus]==<papyrusVersion>"`.
The uv cache is kept under `.uv-cache/` and listed in the spec's cache paths.

## CI access without keys

GitHub Actions in a publication repo reaches AWS with GitHub OIDC: no AWS
access keys or tokens are stored anywhere. Two pieces:

1. **Account-level provider, once per AWS account** (`GithubOidcProviderStack`
   in `@anthusai/papyrus/infra`). Run `aws iam list-open-id-connect-providers`
   first. If `token.actions.githubusercontent.com` is listed (account
   `335163751677` already has it), do **not** deploy the stack: a second
   provider for the same URL fails, and site roles only reference the provider
   by ARN. If it is missing, a human deploys it once:
   `npx papyrus-infra synth --account-stack github-oidc` then
   `cdk deploy -a cdk.out GithubOidcProviderStack` with `AWS_PROFILE=legacy`.
2. **Per-site role** `<siteId>-github-ci`, created by the app-shell stack when
   `infra/site.json` has a `github` block:
   `{ "owner": "AnthusAI", "repo": "<repo>", "branches": ["main", "staging"], "ciCanDeployInfra": false }`
   (`branches` defaults to `main` and `staging`; no wildcards are accepted).
   The trust policy allows only `repo:<owner>/<repo>:ref:refs/heads/<branch>`
   for those branches with audience `sts.amazonaws.com`, session limit 1 hour.
   Permissions: the same authoring statements as the `<siteId>-papyrus-authoring`
   role (see "Authoring role and the CLI" below: `appsync:GraphQL` on Query and
   Mutation fields, `media/*` and `preview/*` object access in the site's
   storage bucket, `amplify:StartJob/ListJobs/GetJob/ListBranches` on the site's
   apps), `sts:GetCallerIdentity`, and `cloudformation:*` on the
   `amplify-app-shell-<siteId>` stack only when `ciCanDeployInfra` is true.
   There is no SSM or secret access. The role ARN is the `GithubCiRoleArn`
   stack output.

Do not use GitHub environments in these workflows: environment-scoped jobs
emit `repo:<owner>/<repo>:environment:<name>` as the subject, which the role
does not trust.

```yaml
permissions: { id-token: write, contents: read }
steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with: { role-to-assume: arn:aws:iam::335163751677:role/<siteId>-github-ci, aws-region: us-east-1 }
  - run: aws amplify start-job --app-id <id> --branch-name main --job-type RELEASE
```

Prove a role with `scripts/verify-oidc-role.sh <role-arn> <app-id>` from a
throwaway workflow on a listed branch (allowed: `amplify list-jobs`; denied:
`iam list-users`), and confirm a run from an unlisted branch fails at the
assume-role step.

## Which account hosts a site

A site whose product has a dedicated AWS account is hosted in that account, not in `papyrus-production`
(`712236451410`): Apricity in `apricity-production` (873363353715), Auritus in `auritus-production`
(961068435042), Kanbus in `kanbus-production` (494166748521), Cyclotron and Prospectus in
`cyclotron-production`, Chattic.us in `chatticus-production`. Publication bucket, CloudFront, certificate,
pipeline and CodeConnections connection all live there; only DNS validation and alias records may be written
cross-account into the zone's own account. Sites that belong to the Papyrus platform itself (Shipped,
Distinctive, Pilobol.us, Anth.us, Threat Intelligence, p.apyr.us) are the ones hosted in `papyrus-production`. Each site records its account in `infra/site.json` under `aws.accountId`; the app-shell stack deploys there and nowhere else.
A new CodeConnections connection is created PENDING and needs a one-time console approval by a human
(Developer Tools, Settings, Connections, Update pending connection) before its pipeline can run.

## Deploying the app-shell stack from a checkout

`infra/amplify-app-shell` is the CDK app behind `papyrus-infra`'s stack. Install once (`npm ci` there; the `aws-cdk` CLI is a pinned devDependency, so no global `cdk` is needed), then from `infra/amplify-app-shell`:

```
SITE=infra/site.json AWS_PROFILE=<profile> npm run diff
SITE=infra/site.json AWS_PROFILE=<profile> npm run deploy
```

`SITE` is the path to the site's own `infra/site.json` (resolve it from the shell directory, or use an absolute path). The stack deploys to the account and region in that file's `aws` block:

```json
"aws": { "profile": "papyrus-production", "accountId": "712236451410", "region": "us-east-1" }
```

There is no default account and no `CDK_DEFAULT_ACCOUNT` or `CDK_DEFAULT_ENV` override: a `site.json` without `aws.accountId` and `aws.region` fails with `does not say where it deploys`. Point `AWS_PROFILE` at credentials for that account; CDK refuses to deploy if they belong to another one. `TS_NODE_TRANSPILE_ONLY` is not needed: `npm run build` type-checks the app and CI runs it.

## Deploy on merge to main

A merge to `main` always deploys, with no manual step. How depends on whether the site's
repository is public, because GitHub Actions minutes are free for public repositories and not
for private ones.

| Repository | CI | CD (the deploy) |
| --- | --- | --- |
| Public | GitHub Actions runs the repo's tests and build | A green push to `main` makes the same workflow start the Amplify job through GitHub OIDC and wait for it. No keys are stored anywhere. Amplify's own auto-build is **off** on the production branches |
| Private | None in Actions (zero minutes) | All in AWS: Amplify's own repository-connected auto-build, or CodePipeline/CodeBuild fed by CodeConnections |

Public sites get everything from the app shell, so a new site needs no extra infrastructure:

1. **The role.** Unless `site.json` sets `"autoDeploy": false`, the stack creates
   `<siteId>-github-deploy` (output `GithubDeployRoleArn`). Its trust policy is the GitHub OIDC
   provider, audience `sts.amazonaws.com`, subject exactly
   `repo:<owner>/<repo>:ref:refs/heads/main` (the repository comes from `github` or, without
   it, from `repository`; a renamed repository must be updated in `site.json`, because the
   OIDC subject carries the repository's current name). Most of our repositories use GitHub's
   **immutable subject**, `repo:<owner>@<ownerId>/<repo>@<repoId>:ref:refs/heads/main`: check
   with `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`
   (`use_immutable_subject`). Set `github.ownerId` and `github.repoId` (the numeric ids from
   `gh api repos/<owner>/<repo> -q .id` and `.owner.id`) in `site.json` and the roles trust both
   forms; without the ids an immutable-subject repository fails at the assume-role step. Its only permissions are
   `amplify:StartJob` and `amplify:GetJob` on `apps/<appId>/branches/main/jobs/*` of the site's
   app (and the reader app of a `markus-static` site). It is separate from the broader
   `<siteId>-github-ci` role, which stays optional.
2. **Auto-build off.** The same stack sets `enableAutoBuild: false` on the production branches
   so nothing builds twice. Staging branches keep their own setting.
3. **The workflow.** Copy
   [`infra/amplify-app-shell/examples/deploy-on-merge.workflow.yml`](../infra/amplify-app-shell/examples/deploy-on-merge.workflow.yml)
   to `.github/workflows/deploy.yml`, replace its CI steps with the repository's own checks and
   fill in the app id (`CmsAppId`) and the role ARN. Its `deploy` job calls the reusable
   workflow `AnthusAI/Papyrus/.github/workflows/amplify-deploy.yml`, which assumes the role,
   runs `aws amplify start-job --job-type RELEASE --commit-id <the merged sha>` and polls
   `get-job` until it succeeds or fails. The Amplify job therefore records the real commit id,
   and a failed build fails the workflow. Do not put the job in a GitHub environment: the role
   trusts the branch subject only.
4. **The OIDC provider** is account-global. `aws iam list-open-id-connect-providers` must list
   `token.actions.githubusercontent.com` (see [CI access without keys](#ci-access-without-keys));
   create it once with `GithubOidcProviderStack` only when the account lacks it.

Rolling out to an existing site: bump `@anthusai/papyrus` and `papyrusVersion` to the release
that has this feature **in the same change** as the workflow. The production build runs
`papyrus-infra deploy`, so a build on an older pin would redeploy the old template and remove
the role. After the stack has the role, the first merge to `main` is the proof: the workflow
run shows the job id, and `aws amplify list-jobs` shows the merged commit id.

Private sites set `"autoDeploy": false` (no role, Amplify auto-build stays on), or use
CodePipeline. A private site's app-shell stack that was deployed before this setting existed
(for example `prospectus-web-cms`) must get `autoDeploy: false` before its next deploy, or its
auto-build stays off and nothing builds. If a repository-connected Amplify app answers the push webhook but starts no
job, check that the branch has `enableAutoBuild` true, that exactly one Amplify app is
connected to the repository branch, and CloudTrail for the `amplify.amazonaws.com` webhook
events before replacing it with a pipeline.

### Private sites: the LeftBlock receipt gate

Branch protection is not available on our private repositories, so the enforcement point is the
deploy. A private site opts in with a `ci` section in `site.json`:

```json
"autoDeploy": false,
"ci": { "gate": "leftblock-receipt", "statusContext": "leftblock/ci" }
```

The production build then starts with a small shell gate (before `npm ci`) that reads the
`statusContext` commit status for `$AWS_COMMIT_ID` from the GitHub API and exits 1 with
`No LeftBlock CI receipt for <sha>: run `leftblock ci` and push again` unless it is `success`. A
rejected commit costs under a minute of build time. `leftblock ci` (the receipt) posts the status
for the exact commit it tested; merge locally, never with the GitHub merge button, which creates a
commit without a receipt.

- `ci.gate` must be `leftblock-receipt` when `autoDeploy` is false and `actions` when it is true
  (public sites, whose Actions workflow is the gate and whose build spec is unchanged).
- A site without `ci` is unchanged. `requireSignature: true` is not supported yet.
- The stack creates the SecureString `/papyrus/<siteId>/github-status-token` and lets the Amplify
  build service role `ssm:GetParameter` that one parameter. CloudFormation cannot know a GitHub
  token, so after the first deploy replace the generated placeholder once with a fine-grained,
  read-only (commit statuses) token: `aws ssm put-parameter --name /papyrus/<siteId>/github-status-token --type SecureString --overwrite --value ...`.
  The stack adopts it as it is and never overwrites it.

## Which releases need a site bump

Every site bump is a push to `main` and therefore a build of about ten minutes, so seven sites cost about 84 minutes per Papyrus release. Two rules keep that bounded without a numeric cap.

1. **Classify.** The release workflow appends one line to every release's notes, `Affects sites: yes` or `Affects sites: no`, from `procedures/release/classify_release.py classify`. A release affects sites when it changes a path that ships in the npm package or the standard projector: `app/`, `components/`, `lib/`, `renderers/`, `amplify/` (not tests, fixtures or seeds), `packages/`, `infra/amplify-app-shell/`, `scripts/videoml/`, `src/papyrus_content/` and `middleware.ts`. A release that changes only the Python CLI, newsroom libraries, docs or board does not. A release with no marker is treated as affecting sites.
2. **Batch.** A site bumps at most once per planned bump, straight to the newest release, and only when at least one release since its pin affects sites. Save `gh release list -R AnthusAI/Papyrus --json tagName,body,isPrerelease` as JSON (rename `isPrerelease` to `prerelease`), then run `python3 procedures/release/classify_release.py plan-bump --current <pinned version> --releases-json <file>`. It prints `bump_needed`, the `target` version and the site-affecting releases.

Spec: `features_backend/release-classification.feature`.

## Authoring role and the CLI

Every app-shell stack creates the role `<siteId>-papyrus-authoring`
(`PapyrusAuthoringRoleArn` output). The Papyrus CLI never uses a token: each
AppSync request is signed with SigV4 from the standard AWS credential chain, so
automation and humans use whatever credentials they already have (SSO profile,
OIDC role, Amplify build role, any role in the account).

Authorization is IAM only. The data API enables AppSync IAM authorization
(`enableIamAuthorizationMode`), under which access for IAM principals is
decided by IAM policy, not by schema rules. A principal may call the API only if
its own identity policy allows `appsync:GraphQL`. The authoring role carries
that permission, scoped to `Query` and `Mutation` fields of AppSync APIs in the
account and region (not `Subscription`; the API ID does not exist when the stack
is created, so it cannot be named). It also carries `s3:GetObject/PutObject/DeleteObject`
on `media/*` and the preview prefix of the site's `amplify-<cmsAppId>-*`
bucket, `s3:ListBucket` limited to those prefixes, and
`amplify:StartJob/ListJobs/GetJob/ListBranches` on the site's apps. The trust
policy is the account root: a principal can assume it only if its own policy
allows `sts:AssumeRole` on the role (an SSO administrator permission set does).
The GitHub CI role carries the same statements directly, so OIDC jobs need no
second hop.

### Running the CLI locally

Add a profile that assumes the authoring role from your SSO profile in
`~/.aws/config` (the role ARN is the stack output):

```ini
[profile legacy-authoring]
role_arn = arn:aws:iam::335163751677:role/<siteId>-papyrus-authoring
source_profile = legacy
region = us-east-1
```

Then sign in and run any authoring command with that profile:

```bash
aws sso login --profile legacy
export PAPYRUS_GRAPHQL_ENDPOINT=https://<api-id>.appsync-api.us-east-1.amazonaws.com/graphql
AWS_PROFILE=legacy-authoring papyrus ops content inspect
AWS_PROFILE=legacy-authoring papyrus ops content import-markus --content-dir content ...
```

`AWS_PROFILE=legacy papyrus ops content ...` (your SSO administrator profile)
works as well, because administrators already hold `appsync:GraphQL`. `content
inspect` prints the caller identity so you can confirm which role signed.

### Per-site runbook checklist

Copy into the site's runbook and fill in:

- [ ] Amplify GitHub App connected for `<siteId>-cms` (date: ____)
- [ ] Amplify GitHub App connected for `<siteId>-reader`, static sites only (date: ____)
- [ ] OIDC role ARN: `arn:aws:iam::<account>:role/<siteId>-github-ci`
- [ ] Merge-to-main deploy (public repo): `<siteId>-github-deploy` exists, `.github/workflows/deploy.yml` calls the reusable workflow, an empty commit merged to `main` produced an Amplify job with its commit id (date: ____)
- [ ] Secrets live in SSM only (nothing in GitHub secrets or Amplify variables)
- [ ] Old PAT secret (`amplify/github-app-token`) deleted

## Google sign-in

Google is the standard CMS sign-in. `cms.cognitoDomainPrefix` in `infra/site.json`
with `cms.applyCognitoDomainPrefix: true` makes the Cognito hosted-UI domain
predictable; without it Amplify generates the domain (see
[`google-oauth-setup.md`](google-oauth-setup.md)). The template never sets
`PAPYRUS_DISABLE_GOOGLE_OAUTH`. After the first stack deploy, per app:

1. In Google Cloud Console, on the OAuth client, add the origin
   `https://<prefix>.auth.us-east-1.amazoncognito.com` and the redirect URI
   `https://<prefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse`. The same
   client can serve several sites.
2. From the site repository, store the client id and secret as the CMS app's Amplify secrets:

   ```bash
   papyrus site google-secrets set      # prompts: client id (visible), secret (hidden)
   ```

   It reads `infra/site.json`, asserts the AWS account with STS before writing, and prints the exact origin and redirect URI for step 1. For automation: `--client-id <id> --secret-stdin` and pipe the secret in (there is no `--secret` argument, so it cannot reach shell history). Which account, profile and region to use comes from the optional `aws` block of `infra/site.json` (`{"profile": "...", "accountId": "...", "region": "us-east-1"}`) or `--profile`, `--account`, `--region`.
3. Redeploy the CMS `main` branch so the Cognito Google provider picks up the values, then run `papyrus site google-secrets check`: it reports whether both parameters exist (name, last modified, fingerprint) and whether the deployed Cognito provider uses the same client id. Details: [`google-oauth-setup.md`](google-oauth-setup.md).

The command never enables or disables Google OAuth. If the CMS branch sets `PAPYRUS_DISABLE_GOOGLE_OAUTH=1`, the backend ignores the secrets and builds no Google provider; `check` reports the variable's state.

- [ ] Google secrets set on the CMS app (date: ____)

### Per-site Google projects

Give each site its own Google Cloud project and OAuth client rather than sharing one. A shared client works (add every site's Cognito origin and `idpresponse` URI to it), but one consent screen, one set of secrets and one blast radius then cover every newsroom. Per site:

1. Create the project and the OAuth client ([`google-oauth-setup.md`](google-oauth-setup.md) Part A).
2. Choose the **consent screen user type** by who will sign in: **Internal** only when every editor's Google account belongs to the Google Cloud project's own organization. When the editor's Google account is **not** in that organization (a personal Gmail, or another company's Workspace), the consent screen must be **External**; with Internal, Google refuses the sign-in with an `org_internal` error. An External app in Testing needs each editor listed as a test user until the app is published.
3. Pick a distinct `cms.cognitoDomainPrefix` per site; the Cognito hosted-UI domain, `https://<prefix>.auth.us-east-1.amazoncognito.com`, is region-global and the prefix is what you register in Google.
4. Put the client id and secret in the Amplify backend secrets of that site's CMS app only (`papyrus site google-secrets set`; never in `site.json`, Git, or a branch variable).

### Roles are Cognito groups

The newsroom roles are the Cognito groups `admin`, `editor` and `curator`. Signing in with Google creates the user with no group, and a user with no group cannot use the newsroom or read drafts. After the person's first Google sign-in, add them to a group (the `manage-user-role` flow, or the Cognito console, **User pools**, **Groups**). The person then reloads the page, which refreshes the session so the new role is picked up; no sign-out is needed. Guests and signed-in users with no group can read only the published models.

## Revalidation secret (Pretext sites)

A Pretext publish refreshes the live pages immediately: `content-actions` calls
the reader's `POST /api/revalidate` with a shared secret. The secret is an SSM
SecureString that the stack generates (see [Generated secrets](#generated-secrets-ssm-securestring))
and that is never in `site.json`, Git or an Amplify variable (those are wiped by
stack updates or are visible in `get-app`). The template derives the parameter name
`/papyrus/<siteId>/revalidate-secret`, creates it, sets its *name* (not the value) as
branch variable `PAPYRUS_REVALIDATE_SECRET_PARAMETER` on `main`, and grants
`ssm:GetParameter` on exactly that parameter to the app's
SSR compute role. The backend (`amplify/site-backend.ts`, when `revalidateBaseUrl`
is set) passes the same name to `content-actions` and grants it the same read
(`ssm:GetParameter` and `ssm:GetParameters`, because the Lambda reads through boto3
`get_parameters`). Both sides read the parameter at runtime (the route caches it for five
minutes, so rotation takes effect without a redeploy); a missing or unreadable
parameter makes the route answer 401 and the trigger report an error, never
a bypass.

### Reader cache lifetime and edge purge (Pretext sites)

Next sends `s-maxage` equal to a route's `export const revalidate`, and the Amplify CDN in front of the SSR compute honours it. The reader routes used to say 3600, so a page that was unpublished or edited stayed up for up to an hour at the Amplify CDN layer, which only the passage of time can clear (no API purges it). They now say 60 (`lib/reader-cache-lifetime.ts`; `npm run test:reader-cache-lifetime` keeps every route equal to it), and `withPapyrus` sets `expireTime: 120` (Next's `stale-while-revalidate` is `expireTime` minus `revalidate`, a year by default, which lets a shared cache serve a page long past `s-maxage` while it refreshes), so the headers are `s-maxage=60, stale-while-revalidate=60`. That bounds the Amplify CDN layer to about two minutes. Existing sites get this only when they bump their `@anthusai/papyrus` pin.

A site that also puts its own CloudFront distribution in front of the reader names it in `papyrus.config.ts`:

```ts
backend: {
  revalidateBaseUrl: "https://p.example.org",
  revalidateDistributionIds: ["E2QW8WOFWQT0H4"],   // same account as the backend; ids, not ARNs
}
```

After a publish refreshes the reader, `content-actions` invalidates the paths the reader reported as revalidated on each listed distribution (`PAPYRUS_REVALIDATE_DISTRIBUTION_IDS`, `cloudfront:CreateInvalidation` on those distribution ARNs, the same one-call, back-off, wildcard-collapse rule (the reader itself may never send a wildcard) and weekly path-count alarm as the S3 projection). The response gains `edgeInvalidated`; a failure is reported there and never fails the publish.

| Secret | Where it lives | Set by |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Amplify backend secrets (SSM) | human, `papyrus site google-secrets set` |
| Revalidate secret | SSM SecureString `/papyrus/<siteId>/revalidate-secret` | the app-shell stack, generated |
| Prospectus session sealing secret | SSM SecureString `/papyrus/<siteId>/prospectus-session-sealing` | the app-shell stack, generated |
| Reader poll secret (public-reader sites that set `cms.readerRetirementPoll`) | SSM SecureString `/papyrus/<siteId>/reader-poll-secret` | the app-shell stack, generated |

Sites not on the template must set `PAPYRUS_REVALIDATE_SECRET_PARAMETER` on the
branch and grant their compute role and `content-actions` role the read themselves.

### Generated secrets (SSM SecureString)

Per-site secrets that the stack can generate live in SSM Parameter Store as standard
SecureStrings (free, AWS-managed `aws/ssm` key), never in Secrets Manager ($0.40 per
secret per month, which would grow with every site). Use Secrets Manager only where
a service needs it, such as a value CloudFormation must resolve.

CloudFormation cannot create a SecureString, so the `SecureStringParameter` construct
(`infra/amplify-app-shell/lib/secure-string-parameter.ts`) uses a custom resource
Lambda that puts one. The Lambda generates a random 64-character value, never returns
or logs it (it is in no template, output or stack event), creates only (an update
never regenerates it and never overwrites a parameter that already exists, so a
hand-made `revalidate-secret` is adopted as it is), and delete retains it. One Lambda
serves every parameter in a stack, and its role can `ssm:PutParameter` only on the
parameters the stack declares. Readers get `ssm:GetParameter` on that one parameter
ARN and read with decryption; the AWS-managed key needs no KMS grant.

The Prospectus accounts sign-in (`cms.prospectusAccountsApiStageArn`) seals its
cookies with `/papyrus/<siteId>/prospectus-session-sealing`, passed to the runtime as
`PAPYRUS_PROSPECTUS_SESSION_SECRET_PARAMETER` (`lib/prospectus-session.ts` reads it
with decryption and caches it per container for five minutes). Rotating or replacing
it signs everyone out.

A public-reader site that polls Prospectus for retired reader subjects sets `cms.readerRetirementPoll: true` (it needs
`cms.prospectusAccountsApiStageArn`). The stack then also generates `/papyrus/<siteId>/reader-poll-secret`, gives the
compute role `ssm:GetParameter` on it and passes its name as `PAPYRUS_READER_POLL_SECRET_PARAMETER`. The CMS route
`GET /api/reader/retired` answers only a caller that sends that secret in `x-papyrus-reader-poll-secret` (see
[reader-steering.md](reader-steering.md#schedule-and-the-prospectus-retirement-poll)); it answers 503 when the parameter is
not configured. Rotate either secret without echoing it:

```bash
aws ssm put-parameter --region us-east-1 --name "/papyrus/<siteId>/revalidate-secret" \
  --type SecureString --overwrite --value "$(openssl rand -hex 32)"
```

`PAPYRUS_SITE_ORIGIN` (an https origin with no path, such as `https://p.apyr.us`) is the
site's public origin for the Prospectus sign-in `redirect_uri`, redirects, and Origin checks
(`lib/site-origin.ts`). It is needed because `request.nextUrl.origin` is the compute adapter's
internal `https://localhost:3000` on Amplify. The app shell sets it from the site's host; a
hand-written `amplify.yml` must export it (`-e '^PAPYRUS_SITE_ORIGIN='`, as the root
`amplify.yml` and `docs/hosting/amplify-ssr.yml.example` do). It never comes from request
headers. Unset, the routes answer `503 site_origin_not_configured`, except under `next dev`
(SITE_ENV development, NODE_ENV not production) on a loopback host, which uses the request origin.

Sites behind their own edge (an own CloudFront distribution, no Amplify domain association) set `cms.siteOrigin` in `site.json` so the app shell exports their public origin, for example `https://shipped.anth.us`; it is rejected together with `cms.domainName`.

Moving a site off the old Secrets Manager sealing secret (`ProspectusSessionSealingSecret`,
variable `PAPYRUS_PROSPECTUS_SESSION_SECRET_ARN`) is a one-time sign-out: there is no
dual-read. Deploy the stack with the old secret set to `RemovalPolicy.RETAIN` first, then
the stack without it, then delete the retained secret by hand once sign-in works.

## Paths the CMS edge reserves

On a site whose public host serves an S3 projection with the CMS app behind the same CloudFront distribution (`infra/edge/s3-projection-cms.yaml`: Shipped, Distinctive Mark, Data Parade, Threat Intelligence, and p.apyr.us's marketing distribution), these paths go to the CMS app, not the bucket:

| Path | Why |
| --- | --- |
| `/newsroom*` | the newsroom console |
| `/_next/*` | the console's Next.js assets |
| `/api/*` | the console's API routes |
| `/cli/*` | remote CLI sign-in approval pages (`papyrus login --remote`) |
| `/.well-known/papyrus-cli.json` | the CLI sign-in details |

A projected page, a section base or a `homePage` segment that starts with one of these is shadowed by the CMS on those hosts, so pick another segment there. Anth.us is the exception: `anth.us` is pure S3 (the console is a separate host, `newsroom.anth.us`), so its public section can live at `anth.us/newsroom/` with no edge change.

## Custom domains and Route 53

1. Create a **public** hosted zone for the publication domain (e.g. `pilobol.us`).
2. Give the registrar the zone NS records (Kanbus comment for the operator).
3. Create the Amplify app and verify on the default `*.amplifyapp.com` URL first
   (a new stack that must coexist with an older stack for the same `siteId` sets
   `stackName`; leave `hostedZoneId` and every `domainName` out of `site.json`; set
   `cms.staging: false` to skip the staging branch too).
4. Add custom domains: add `hostedZoneId` and the `domainName` fields to
   `site.json`, add the domain origins to `PAPYRUS_OAUTH_REDIRECT_URLS`, and
   re-deploy the stack (or add them in the Amplify console); let Amplify create alias records in the hosted zone.
   A host under a root domain that another Amplify app also holds (for example
   `threat-intelligence.anth.us` beside the Anth.us app) uses `cms.domainName` =
   the root, `cms.domainPrefix` and an explicit `cms.stagingDomainPrefix`; the
   stack emits one domain association for the root with both prefixes. The
   staging host is never derived there. See the app-shell README.
   To redirect the root domain apex to the primary host (for example `apyr.us`
   to `https://p.apyr.us`), add `cms.redirects: [{ "source": "apyr.us", "status": 301 }]`
   (see `examples/p-apyr-us.site.json`): the stack emits an Amplify app rule
   ahead of the 404-200 catch-all and associates the apex with the app. Another
   app that holds the same hosts (the old app) must release them first, and
   the template never writes Route 53 records, so MX stays untouched.
5. Wait for ACM validation and registrar NS propagation before accepting
   `https://<domain>` as done.

## Which account `papyrus-infra` targets

`papyrus-infra synth` and `papyrus-infra deploy` never default to a fixed AWS account. The account is the first of:

1. `--account <id>`
2. `CDK_DEFAULT_ACCOUNT`
3. the account returned by `aws sts get-caller-identity` for the current credentials (the aws CLI must be on `PATH`)

If none of these yields a 12-digit account id, the command exits with `cannot determine the AWS account` and the reason. The region is `--region`, then `AWS_REGION`, `AWS_DEFAULT_REGION`, `CDK_DEFAULT_REGION`, and finally `us-east-1`. Amplify builds set none of the `CDK_DEFAULT_*` variables, so a deploy from a build uses the build role's own account; passing `--account` in the postinstall hook is still allowed and wins.

Before Papyrus 1.19.x the account silently fell back to the legacy account, which made `papyrus-infra deploy` try to assume the legacy CDK deploy role from other accounts.

## Cross-account domains

Lessons from the failed p.apyr.us cutover (the Route 53 zone stayed in the legacy account while the new app lives in the production account):

- An Amplify hostname can belong to only one app across accounts. Creating the association in the new account is refused ("already associated with another Amplify app") while another account's app holds `p.apyr.us` or `apyr.us`.
- Deleting an association deletes its CloudFront distribution and the Amplify-managed records. Re-creating it yields a NEW distribution and a NEW certificate, so the old site is down until the new association is AVAILABLE, and rolling back is a re-creation, not an undo.
- A cross-account association waited 30 minutes in `PENDING_VERIFICATION`, although its validation CNAME was identical to the record already in the zone. The cause is unresolved. Do not retry the delete-first cutover without a diagnostic on a hostname nobody holds, for example a throwaway prefix.
- Connecting a repository in the Amplify console overwrites the app `buildSpec` and branch environment variables. Restore the build spec with `aws amplify update-app --build-spec` and re-apply the branch variables from the stack.
- Plan domain moves so the Route 53 zone lives in the same account as the app whenever possible; that avoids manual validation records and the cross-account refusal.

## AppSync 429 on new accounts (resolver waves)

In a brand-new AWS account the first backend deploy can fail with AppSync
`CreateResolver` 429 (Too Many Requests) while CloudFormation creates every
data model nested stack in parallel. `defineSiteBackend` therefore chains the
model nested stacks in waves: each wave of `backend.resolverWaveSize` stacks
(default 12) waits for the previous wave. It only adds `DependsOn` ordering
between nested stacks; no resource, schema or API changes. Set
`backend: { resolverWaveSize: 0 }` in `papyrus.config.ts` to turn it off.

## Start a new Papyrus site: the two-deploy first backend

CloudFormation creates at most 2,500 resources in one stack operation, nested stacks included, and the limit cannot be
raised. The full Papyrus backend is about 2,700 resources for a minimal site and more with plugins (the Shipped site's
is 3,100), so the first `ampx pipeline-deploy` of a brand-new site fails with "Limit on the number of resources in a
single stack operation exceeded" and rolls back. Existing sites passed it one release at a time; an update only counts
the resources it creates or changes. `resolverWaveSize` does not help: every wave runs inside the same root operation.

A new site therefore deploys its backend twice:

1. **First deploy, bootstrap stage.** Set the Amplify branch variable `PAPYRUS_BOOTSTRAP_STAGE=1`. The data API then
   leaves out the optional model groups in `OPTIONAL_MODEL_GROUPS` (`amplify/data/schema.ts`): editions, knowledge,
   semantic, review, procedures, editorial checks and steering. Nothing else depends on those models, so the schema
   stays valid. A minimal site synthesizes to about 1,700 resources (a site with the `home-page` plugin: 1,678), well
   under the limit. `scripts/test-bootstrap-stage.ts` holds the figure under 2,000. Plugins add their own models (reader-steering plus signup: 2,030), so a site with many plugins has less headroom; check it with `npx tsx scripts/synth-site-backend.mts <dir> '<backend json>'` under `PAPYRUS_BOOTSTRAP_STAGE=1`.
2. **Second deploy, normal.** Remove the variable and deploy again. This is an ordinary update that adds the deferred
   models (about 1,000 resources, created in the one update).

```bash
# Before the first build (the site's Amplify app id and branch):
aws amplify update-branch --app-id <appId> --branch-name main \
  --environment-variables "$(aws amplify get-branch --app-id <appId> --branch-name main \
      --query 'branch.environmentVariables' --output json | jq -c '. + {PAPYRUS_BOOTSTRAP_STAGE:"1"}')"
# Run the build (push to main, or aws amplify start-job). When the backend deploy succeeds, remove the variable:
aws amplify update-branch --app-id <appId> --branch-name main \
  --environment-variables "$(aws amplify get-branch --app-id <appId> --branch-name main \
      --query 'branch.environmentVariables' --output json | jq -c 'del(.PAPYRUS_BOOTSTRAP_STAGE)')"
# Run the build again.
```

`update-branch --environment-variables` replaces the whole map, so merge into the existing variables as above.

With the variable unset the synthesized templates are byte-for-byte what they were before the switch existed (apart from
asset hashes, deploy tokens and the API key expiry that change on every synth), so it cannot affect a live site. Between
the two deploys the newsroom lacks the deferred models; do not point users at it yet. A failed first create can leave the
root stack `amplify-<appId>-<branch>-branch-<hash>` in `ROLLBACK_COMPLETE`; CloudFormation cannot update such a stack,
so delete it (`aws cloudformation delete-stack`) before the first bootstrap build. Sites that cannot set a branch
variable can set `backend.excludeModelGroups: [...]` in `papyrus.config.ts` instead, then remove it for the second deploy.
Known groups: `OPTIONAL_MODEL_GROUPS`; an unknown name fails the build.

## Data API Lambda resolvers and the 500-resource stack limit

CloudFormation fails a stack of more than 500 resources. Amplify puts every Lambda-backed query and mutation of the data
API into one nested stack, `FunctionDirectiveStack`. A field handled with `a.handler.function(fn)` gets its own AppSync
data source, IAM role, IAM policy and two function configurations, so it costs six resources there; Papyrus 5.33.0 had 85
such fields and the build failed with `TooManyResourcesInStack ... FunctionDirectiveStack: 505`.

Handle schema fields with `functionHandler("name", fn)` from `amplify/data/function-handler.ts`, never with
`a.handler.function(fn)`. Every field that calls the same Lambda then shares one data source, role, policy and function
configuration, and a new field costs one resolver. The Lambda receives the same event as before (`typeName`, `fieldName`,
`arguments`, `identity`). `defineSiteData` passes the registered functions to `defineData({ functions })`. The stack is
about 230 resources with every plugin on; `scripts/test-function-directive-stack.ts` synthesizes the real backend and
fails above 450.

Sites need nothing beyond the version bump. The first deploy replaces each per-field data source with the shared one
inside the same nested stack (CloudFormation creates the new ones, repoints the resolvers, then deletes the old ones); the
GraphQL schema and clients are unchanged.

## Backend features and account-global names

`defineSiteBackend(site)` creates four optional features, each behind a flag
(`features` in `papyrus.config.ts` wins over the `PAPYRUS_ENABLE_*` branch
variable): `consoleResponder` (`PAPYRUS_ENABLE_CONSOLE_RESPONDER`), `inboundEmail`
(`PAPYRUS_ENABLE_INBOUND_EMAIL`), `slack` (`PAPYRUS_ENABLE_SLACK`) and
`storageBackups` (`PAPYRUS_ENABLE_STORAGE_BACKUPS`). The app-shell template passes
whatever is in `cms.environment`, so set all four explicitly in `site.json` (see
`examples/p-apyr-us.site.json`). A flag that is off creates none of that feature's
resources. The console responder defaults to ON when nothing is set, so a new site
must say `"false"`. It also needs a container image that this package does not
build, so enabling it needs separate work.

Names that are account-global or region-global are derived in
`amplify/site-backend-names.ts`. Only the app named by `productionAppId` (the
original p.apyr.us app) keeps the historical names; every other site is scoped by
brand id (`defaultBrand`) or by a hash of its stack name:

| Feature | Resource | Scope | Name for a new site |
| --- | --- | --- | --- |
| always | S3 Vectors index | region | `papyrus-knowledge-<brand>` (legacy: `papyrus-knowledge`) |
| inboundEmail | SES receipt rule set | account + region, one ACTIVE per account | `papyrus-site-inbound-<brand>`, created and never activated by CloudFormation |
| inboundEmail | SES receipt rule | inside the rule set | `<brand>-inbound-submissions` |
| inboundEmail | SES domain identity and `_amazonses` TXT | account | not created (verify once by hand); `inboundEmailSes.manageDomainIdentity: true` opts in |
| inboundEmail | SES rule set that another stack owns | account | `inboundEmailSes.existingReceiptRuleSetName` adds only this site's rule to it |
| inboundEmail | EventBridge rules, Lambdas, S3 bucket, IAM roles | stack | generated by CloudFormation (stack-scoped, no fixed names) |
| storageBackups | Backup vault | account | `papyrus-<brand>-<8 hex of sha256(brandId|appId|branch)>-media-vault` (legacy: `papyrus-<appId>-main-media-backup-vault`) |
| storageBackups | Backup plan, rule names, selection | vault or plan | plan-scoped, no collision |
| slack | Secrets (`PAPYRUS_SLACK_*`) | per app | read from `/amplify/<appId>/...`, per-app by construction |
| consoleResponder | Lambda, event source mapping | stack | generated names |

Receipt rules are created only for the `main` branch of a deployed app, never in
a sandbox or on a `staging` branch.

### Coexisting with a live SES rule set (human steps)

SES allows one active receipt rule set per account and region. That limit does not
span accounts: SES can process matching rules in multiple accounts for the same
domain. SES identities are also account-owned, so a verified identity in one account
does not verify it in another. The receiving identity and active set must belong to
the same account as the receiver resources. Nothing here is run by the deploy.

For p.apyr.us, the current site and Monitoring router are in account
`712236451410` (`papyrus-production`). The old active rule set
`papyrus-inbound-p-apyr-us`, its identity and its Amplify media bucket are in
account `335163751677` (`legacy`), under the retired app's storage stack. The old
identity currently reports `Failed`; the production account has no `p.apyr.us`
identity or receipt rule set. Do not treat the old identity or rule set as a
production resource. A new receiver belongs in `papyrus-production`.

Create one retained, inactive set in the receiving account and region with
`infra/email/papyrus-email-receiving-set.yaml`, then add scoped rules through
`papyrus-email-submissions.yaml`. The receiver's `Enabled` and `RouterEnabled`
parameters stay false until configuration and grants have been reviewed. At an
approved cutover, enable the production route and disable the old matching rule;
otherwise the two AWS accounts can both store/process the same message. Keep the
legacy bucket and messages for rollback. Do not delete the legacy stack as part of
the first cutover because its custom resource can alter its own account's active
receipt rule set on deletion.

For domains that have not been verified in the receiving account, publish that
account's SES verification TXT record at `_amazonses.<domain>` after confirming the
publicly authoritative DNS zone. The domain name `apyr.us` has two Route 53 hosted
zones with different assigned name-server sets; the public delegation is not yet
confirmed. Both zones currently contain the SES MX record for us-east-1. Preserve
it unless the receiving region changes. See the account-specific p.apyr.us status
and cutover steps in [email infrastructure](../infra/email/README.md).

Within one account and rule set, receipt rule names must be unique and exact
recipient addresses must not overlap. Reuse an existing set only when it is owned
by that account and the rule order is reviewed.

## S3 projection publication (Markus sites)

A Markus site publishes its pages as static files in an S3 bucket from inside the publish mutation: no build job, no reader app. Set `backend.publication` in `papyrus.config.ts` (the fields are below); a site that does not set it has no projection resources and synthesizes exactly as before.

```ts
backend: {
  publication: {
    kind: "s3-projection",
    projector: "web/projector.py",                 // optional, relative .py path in the site repo
    staticDir: "web/static",                       // optional, relative directory in the site repo
    edgeDistributionArn: "arn:aws:cloudfront::123456789012:distribution/E3UMOOJRMY7FK7", // optional
    distribution: { create: false },               // or { create: true, aliases, certificateArn | acm }
    cache: { htmlSMaxAgeSeconds: 300, invalidation: "targeted" }, // optional; these are the defaults ("off" and 60 s for the no-invalidation fallback)
    retainBucketOnDelete: true,                    // default; false destroys the bucket with the stack
  },
}
```

`edgeDistributionArn` (an existing distribution) and `distribution.create: true` are mutually exclusive. Aliases need `certificateArn` or `acm: { hostedZoneId, hostedZoneName }` (a DNS-validated certificate in us-east-1). `projector` and `staticDir` must be relative and contain no `..`; they are bundled into the content-actions zip as `site_projector.py` and `site_static/`, resolved from the directory the backend is synthesized in (the site repo root).

When set, the backend creates a `s3-projection` stack with a versioned, private, SSL-only, SSE-S3 site bucket (noncurrent versions expire after 90 days), a CloudFront KeyValueStore, a CloudFront Function (cloudfront-js-2.0, viewer-request: KVS redirects, then `/x/` and `/x` to `index.html`), an SQS dead-letter queue, a bucket policy that lets only `cloudfront.amazonaws.com` read objects for the distribution ARN (OAC), and, with `distribution.create`, the distribution itself. The content-actions Lambda gets 2048 MB of memory and least-privilege IAM for the bucket, invalidations, the KVS and the queue.

The environment contract with the Python side:

| Variable | Set when |
| --- | --- |
| `PAPYRUS_PUBLICATION_KIND=s3-projection` | always |
| `PAPYRUS_SITE_BUCKET` | always |
| `PAPYRUS_REDIRECTS_KVS_ARN` | always |
| `PAPYRUS_PROJECTION_DLQ_URL` | always |
| `PAPYRUS_EDGE_DISTRIBUTION_ID` | a distribution is created or `edgeDistributionArn` is given |
| `PAPYRUS_HTML_S_MAXAGE_SECONDS` | `cache.htmlSMaxAgeSeconds` is set |
| `PAPYRUS_EDGE_INVALIDATION=off` | `cache.invalidation` is `"off"` |
| `PAPYRUS_SITE_PUBLIC_URL` | a distribution is created (first alias, else its domain name) |
| `PAPYRUS_SITE_PROJECTOR=site_projector` | `projector` is set |
| `PAPYRUS_SITE_STATIC_DIR=/var/task/site_static` | `staticDir` is set |

Existing sites are unaffected: with `publication` unset no stack, resource, environment variable, policy statement, memory change or bundled file is added.

### Upload-time image renditions

When `<staticDir>/projection.json` has an `images` section, the `s3-projection` stack also creates a `renditions` Lambda (Python 3.12, arm64, 3008 MB, 5 minutes) with an EventBridge rule on `Object Created` under `media/` in the CMS media bucket (the template switches S3 to EventBridge notifications on for that bucket). Uploading `media/<srcPath>` writes, to the site bucket, the same files the full build writes: `assets/responsive/<dir>/<stem>-<width>.<avif|webp|jpg|png>`, `assets/responsive/<dir>/<stem>.meta.json` (written last) and, with `listing_max_width`, a downscaled listing copy at `assets/content/<srcPath>`. A page render reads the `meta.json`; it never opens or encodes an image, and a missing `meta.json` fails the projection with the command that fixes it.

`images` takes the `ImagePipeline` data fields (`gatsby_parity`, `quality`, `formats`, `max_width`, `widths`, `placeholder`, `eager_first`, ...) plus `listing_max_width`. Existing media are back-filled with `papyrus ops content renditions --backfill` (add `--dry-run` first; it skips images that already have a `meta.json`), and one image is requested again with `papyrus ops content renditions --source <srcPath>`. Both read `PAPYRUS_MEDIA_BUCKET_NAME` and `PAPYRUS_RENDITIONS_FUNCTION_NAME` (also settable with `--media-bucket` and `--function-name`).

A site that serves media as they were uploaded (no image pipeline, pages that reference `assets/...` directly) sets `"media": { "originals": true }` in `projection.json` instead of, or besides, `images`. The same function then writes every object created under `media/` to the site bucket at its key without the `media/` prefix (`media/assets/a/b.jpg` becomes `assets/a/b.jpg`), with its content type, whatever its type. Existing media are back-filled with `papyrus ops content renditions --backfill --originals`, which lists every object, not only images, and skips those already in the site bucket.

### Edge caching and invalidation

- **Cache-Control per object.** HTML and every other file a projection can rewrite (`sitemap`, `robots.txt`, unhashed CSS and JS, JSON) get `public, max-age=0, s-maxage=300, stale-while-revalidate=60`: the browser always revalidates, the edge keeps a page for at most five minutes even if a purge is lost. Renditions under `assets/responsive/` (except `.meta.json`), `_next/static/` and file names that end in an eight-or-more-digit hex content hash get `public, max-age=31536000, immutable`.
- **Targeted invalidation, one call per run.** After the writes, the projection makes one invalidation call (each `index.html` page in its `/x/index.html` and `/x/` forms), with exponential back-off when CloudFront throttles. Up to 10 distinct paths are listed exactly. More than 10, which is every full render and every site-wide follow-up, becomes a single `/*`: CloudFront bills a wildcard as one path, while listing a few hundred pages cost about $65 in 20 days. Callers still cannot pass a wildcard themselves; only this size rule chooses it. The first 1,000 paths a month are free, then $0.005 per path.
- **Redirect writes.** A full render reads the KeyValueStore once and writes only redirects whose target changed, 50 keys per `UpdateKeys` call, and new-page redirect checks use one listing instead of a read per path when more than 10 paths are checked.
- **Failure.** A failed purge does not make the item not live; the response says `edgePurged: false` and the function schedules an asynchronous `invalidate` task for the unpurged keys. If that keeps failing, Lambda sends it to the dead letter queue.
- **Fallback.** `cache: { invalidation: "off" }` removes the invalidation call and its IAM statement and shortens the HTML lifetime to 60 seconds (or `htmlSMaxAgeSeconds`).
- **Alarm.** Each invalidation call writes a CloudWatch embedded metric (`Papyrus/Edge` `InvalidatedPaths`, dimension `DistributionId`). The stack alarms when a week sums to 230 paths or more, which is the pace of the 1,000 free paths a month (CloudWatch cannot alarm across more than seven days).

### Serving a projection under a host site's path

A publication whose main website is a separate app (its own build, its own account) can serve the projected articles under a path of that website, for example `https://dataparade.io/posts/`, without the host app being rebuilt for a publish. Papyrus epic PPY-116551; first user Data Parade (PPY-d74fb4).

1. **Base path.** Set `urls.basePath` in `web/projection.json` (`"/posts"`). Every key the projection writes and every URL it generates move under it: pages, listings, tags, feeds, the sitemap, `_data/*.json`, the `.md` twins, `llms.txt`, page actions and the files of the static directory. `404.html` and `robots.txt` stay at the bucket root (the distribution's error response and crawlers read them there). Paths you write (nav links, icons, `seo.defaultImage`, `redirects.exact`, aliases, links in articles) are used as written: write `/posts/assets/logo.png`, not `/assets/logo.png`. Add `"redirects": {"exact": {"/": "/posts/"}}` so the root of the Papyrus host lands on the articles.
2. **Moving an existing site.** The projector owns only keys under the base path, so a full projection (`papyrus ops content project --all`) leaves the old root pages in the bucket, still served. List them with `aws s3 ls s3://<site bucket>/` and remove everything outside `posts/`, `_papyrus/`, `404.html` and `robots.txt` once the new pages are verified; old addresses that people may have linked get `redirects.exact` entries.
3. **Host CDN.** On the host's CloudFront distribution add the Papyrus edge host (the `ApexHost` of `papyrus-edge-<site>`, for example `dataparade.anth.us`) as a custom origin (`https-only`), and one cache behavior `/posts/*` (and `/posts` if the host has no redirect for it) to that origin with the managed `CachingDisabled` cache policy and the `AllViewerExceptHostHeader` origin request policy. The inner distribution keeps doing the work: index rewrites, redirects from the KeyValueStore, Markdown negotiation, caching and the targeted purges, so a publish is visible on the host as soon as it is on the Papyrus host. Nothing crosses accounts except HTTPS between the two distributions; no bucket policy changes.
4. **Canonical host.** Set `site.productionUrl` to the host origin (`https://dataparade.io`) once the route works, so canonical links, Open Graph URLs, feeds, the sitemap and `llms.txt` name the host. Until then the pages name the Papyrus host. This holds for a backend whose edge is its own stack (`edgeDistributionArn`, as Data Parade has): the projection then takes its origin from `productionUrl`. A backend that creates its distribution sets `PAPYRUS_SITE_PUBLIC_URL` to that distribution's alias, so a different `productionUrl` keeps its pages guarded (`noindex`).
5. **Recent posts on the host.** With `publicData` on, the host reads `/posts/_data/latest.json` (title, url, summary, tags, date of the newest items) from the same origin in the browser; no CORS and no host rebuild.
6. **Look.** The `hooks` module supplies the host's header and footer (`masthead`, `footer`) and anything the head needs (`head_extra`, for example a script that follows the host's light/dark switch), and `web/css/site-theme.css` carries the host's tokens.

### Incremental projection, concurrency and repair

Publishing, saving a live item and unpublishing rewrite only the pages that depend on the item.

- **Dependency rule.** A projector declares, for every page that is not an item page, a digest of what the page renders from (`listing_inputs`). The engine compares the digests for the site before the change (the item as last projected, kept in `_papyrus/items/<item>.json` in the bucket) and after it, and renders only the pages whose digest moved. Membership, order, pagination boundaries and every field a card shows are covered because the digest is of the generated page content, not of a hand-kept table. `shared_inputs` is the same for what every item page depends on (navigation, the site's URL map for rewritten links): when it moves, the other item pages are re-rendered as a follow-up that writes only pages whose bytes differ (an asynchronous invocation of the function itself).
- **Write order.** New or edited item: its page, the listing pages that changed (sitemap last), pages that went away (a trailing pagination page), redirects, then the item state. Unpublished item: the listing pages and sitemap first, then the item's pages are deleted, then its redirects. A renamed item (unpublish, change the slug, publish) leaves a redirect from its old address; a page that takes over a redirected address removes the redirect.
- **Concurrency.** Pages are always rendered from the stored data, never from the request. After writing, the projection reads the published `(id, versionNumber)` set again; if another publish moved it, the pages that depend on the difference (and the item itself, if it was edited again) are rendered again, up to three rounds. The item state is written before that re-read, so the last state written belongs to the last pages written. Two editors saving the same item are still rejected by `expectedContentHash`.
- **Failure.** A failed projection never fails the save: the response has `live: false`, and the function invokes itself once more asynchronously (`retryAttempts: 1`, on-failure destination: the dead letter queue). Every step is idempotent: the item state is written last, so a half-finished projection is redone from the old state.
- **Reconcile.** `papyrus ops content project --reconcile [--dry-run] [--json]` compares the published data with the bucket: an item page whose `papyrus-version` is not the published `versionNumber` (or that is missing), the page and state of an item that is no longer published, a listing page whose `papyrus-inputs` is not what the data now yields, a page the projector owns that nothing expects (stale cleanup), and missing or different redirects. It repairs them (or, with `--dry-run`, only reports and exits 1 on drift); a large drift is repaired by `--all`. Theme and code changes are not drift; run `papyrus ops content project --all` after a backend deploy. `--item-pages` re-renders the item pages only. `--only <site-relative prefix>` limits the orphans it considers to that prefix. A reconcile never deletes a plugin's pages unless the plugin is known to be disabled, and a non-dry-run reconcile refuses when the plugin list (from `amplify_outputs.json` `custom.papyrusPlugins`, or `PAPYRUS_PLUGINS`) is unknown or differs from the deployed one; see "Reconcile and plugin pages" in [building-a-papyrus-static-site.md](building-a-papyrus-static-site.md).
- **Deletion guard.** `project --all` and `--reconcile` (and `papyrus knowledge snapshot --reproject`) refuse, before writing any page, to delete the pages of an item that stays published, or more than a tenth of the stored pages (and more than 20). This is what a site configuration that no longer places a section, such as an out-of-date `--static-dir` checkout, looks like. The error lists the pages per top-level path, the published items and the first 50 keys, and exits 2. Fix the configuration, or pass `--allow-deletions` when the deletions are intended. With `--static-dir` in a git checkout that has an upstream, the command warns on stderr when the checkout is behind. The backend's own publish and deploy-render paths have no guard, and `--dry-run` only reports.

### Publish to visible

What an editor can expect from a Save of a live item, as measured on the production sites (PPY-409932, PPY-65d13a, PPY-f1df00):

| Step | Typical time |
| --- | --- |
| The mutation returns `live: true` | about 2 s warm; 8 to 14 s on a cold Lambda start (production Anth.us and Pilobol.us publishes) |
| Targeted invalidation call | 0.1 to 0.25 s |
| Edit start to new page visible at the edge (throwaway test, targeted invalidation) | 1.9 to 3.1 s; twelve edits one second apart converged within about 9 s |
| A new image, upload to visible | about 2 to 4 s (the renditions Lambda) |
| If the purge is lost or `invalidation` is `"off"` | the page lifetime: 300 s by default, 60 s with `cache.invalidation: "off"` |
| Pretext site, publish to visible | up to about two minutes (see [Hosting Pretext, for contrast](#hosting-pretext-for-contrast)) |

Say "seconds", not "instant". Browsers always revalidate HTML (`max-age=0`).

### Operations runbook

Run these with the site's credentials (the authoring role or an SSO profile) and `PAPYRUS_GRAPHQL_ENDPOINT` set, as in [Running the CLI locally](#running-the-cli-locally). Every projection command is idempotent and safe to repeat.

| Task | Command | When |
| --- | --- | --- |
| Re-render every page from the data | `papyrus ops content project --all` | After a backend or theme deploy, after the projector code changes, after a back-fill, to repair large drift |
| Re-render one item | `papyrus ops content project --item <item-id>` (add `--unpublished` for an item that is not live) | After `import-markus`, or to fix one page |
| Re-render all item pages only | `papyrus ops content project --item-pages` | After a change to shared page inputs |
| Re-render listings only | `papyrus ops content project --listings` | Listing code changed |
| Check the bucket against the data | `papyrus ops content project --reconcile --dry-run` | Routine check; exits 1 on drift |
| Repair drift | `papyrus ops content project --reconcile` | After a failed projection, or after the dry run reports drift; add `--allow-deletions` only if it refused and the deletions are intended |
| Render to a local directory instead of S3 | `papyrus ops content project --all --out DIR --static-dir DIR` | Parity checks against another build, local diff before a deploy |
| Make image renditions for existing media | `papyrus ops content renditions --backfill --dry-run`, then `--backfill` | After enabling `images` in `projection.json` |
| Copy media originals to the site bucket | `papyrus ops content renditions --backfill --originals` | Sites with `"media": { "originals": true }` |
| Redo one image | `papyrus ops content renditions --source <srcPath>` | After the pipeline settings change for it |

`project --all` also uploads the site's static files (CSS, scripts, robots, 404 page) and the redirect entries. After a backend deploy that changes the projector or the theme, run `project --all` once; until then pages keep the previous chrome. With `reprojectOnDeploy: true` the deploy does this itself, with no personal credentials (below). A full run of the Anth.us site (230 files and 520 redirects) took 77 seconds.

#### The dead-letter queue and reconcile

A projection that fails never fails the save. The response says `live: false`, the function invokes itself once more asynchronously, and if that also fails Lambda puts the event on the SQS dead-letter queue (its URL is `PAPYRUS_PROJECTION_DLQ_URL` on `content-actions`). A message in the queue means a page may be behind its data. Repair, in this order:

1. Run `papyrus ops content project --reconcile --dry-run` to see what is behind.
2. Run `papyrus ops content project --reconcile` to fix it. Stale pages, missing redirects and pages of unpublished items are all handled.
3. Purge the queue only after reconcile reports no drift. The queue is a signal, not a work list: reconcile reads the data, not the queue.

Routine habit: run the dry run after any deploy that touched `content-actions`. Nothing runs it on a schedule yet.

#### Merge is deploy: the post-deploy render

With `publication.reprojectOnDeploy: true` (the default for the publication a Markus site gets when it sets none; a site that spells `publication` out must set it), the backend deploy renders the whole site itself, so merging to `main` is the only step once the CMS Amplify app builds `main` automatically (branch `enableAutoBuild`, which the app-shell template sets and which the CMS app's `main` branch must keep). Nothing in the path needs a person's AWS access.

1. The deploy runs a custom resource in the site backend. It invokes the content-actions Lambda **synchronously** with the `deploy-render` projection task and waits (the function timeout is 15 minutes; a full Anth.us render took 77 seconds).
2. `deploy-render` runs the same render as `project --all`, then runs `reconcile` as a **dry run**. Orphan pages, stale pages and missing redirects are reported and nothing is deleted: `--all` and the dry run never delete. Repair stays a deliberate `papyrus ops content project --reconcile`.
3. A render that fails raises, the custom resource fails, the stack update fails and the Amplify build goes red with the failure in the build log. A render that succeeds returns its summary (pages written, redirect count and the drift lists, at most 25 keys each) to the Lambda log and the CloudFormation resource data. The run also writes a CloudWatch embedded-metric line, `Papyrus/Projection` `DeployRenderDrift` (dimension `FunctionName`), and the backend creates an alarm that is in ALARM for a day after any run that found drift.

The 404 page is stored by the writer itself with `Content-Type: text/html` and no `Cache-Control`, because CloudFront serves it through the error-response path where no viewer-response function runs. No follow-up script is needed after a render.

#### The 404 page and its headers

Missing pages must return HTTP 404 with the site's own `404.html` body. On the S3 projection:

- S3 answers a request for a missing key with 403, not 404, when the caller has no list permission (the OAC grant is read only), so a pure S3 distribution maps **both** 403 and 404 to `/404.html` with response code 404 (`CustomErrorResponses`). The projector must emit `404.html` as a static file.
- **Distributions with CMS behaviors must not use `CustomErrorResponses`.** They apply to every cache behavior, so the 403 and 404 of the CMS origin on `/api/*` (a same-origin rejection, `/api/reader/*`, `/api/auth/prospectus/*`) would be replaced by the 404 page. Such a distribution serves the 404 page from the default behavior with a Lambda@Edge `origin-response` function instead (`infra/edge/s3-projection-cms.yaml`, explained in `infra/edge/README.md`). Verify with a cross-origin `POST` to `/api/newsletter/subscribe` (the origin's JSON error, not HTML) and a random missing page (404 with the styled body).
- **Header caveat.** On a pure S3 distribution the error page is served through the distribution's error-response path, so headers set by a response-headers policy or a viewer-response function can differ from those of a normal page, and the error response is cached for the error-caching minimum TTL. Do not assume the 404 carries the same `Cache-Control` or security headers as the pages. After any edge change, request a random missing path and one missing `.html` path and compare status, `content-type` and `cache-control` with the previous host. The Anth.us cutover checked exactly this and the 404 headers were unchanged.
- The viewer-request function redirects `/x.html` to `/x/` for pages (except the listed served files such as `/404.html`), and rewrites `/x/` to `/x/index.html`.

#### Own CloudFront in front of the bucket (`papyrus-edge-*`)

Public hosts do not use Amplify custom domains for the static site. Each site has an edge stack `papyrus-edge-<site>` in the production account: a CloudFront distribution with its own ACM certificate and aliases, an S3 origin on the site bucket through an origin access control (OAC) that admits only that distribution, a CloudFront Function with a KeyValueStore for redirects and directory indexes, and the 403/404 error responses above (or, with CMS behaviors on the same host, the origin-response 404 function that replaces them). The site backend can create a distribution itself (`distribution: { create: true, aliases, acm }`) or accept an existing one (`edgeDistributionArn`). Existing sites keep their hand-run edge stacks and only swap the origin.

Why: Amplify domain management ties a hostname to one app in one account, deletes and recreates the CloudFront distribution and certificate when an association is deleted, and can sit in `PENDING_VERIFICATION` with a validation record that already matches (see [Cross-account domains](#cross-account-domains)). Owning the distribution removes the reader app from DNS and certificates; a change is a CloudFormation change set with a one-command rollback. Pretext sites stay on Amplify domains.

### Migrating from the Amplify reader

Order of operations that worked for Pilobol.us and Anth.us (each step reversible until the last):

1. **Project into the bucket without touching live.** Deploy the backend with `backend.publication`, run `papyrus ops content renditions --backfill`, then `project --all`.
2. **Prove parity.** Compare the bucket tree with the reader build from the same data (a full-tree diff, modulo cache-bust tokens). On a test distribution, compare status, redirect chain, `cache-control`, `content-type` and body for a list of live paths, every redirect rule, and the 404 behaviour, against the live site.
3. **Flip the origin** on the existing edge stack with a change set (aliases, certificate and DNS do not move). Poll the hostname every few seconds through the change; the Anth.us flip had zero non-200 in 152 samples.
4. **Stop triggering the reader.** Remove the reader app id from the site config so a publish no longer starts an Amplify build (the build retries were most of the 9.8 s Pilobol.us publish).
5. **Keep the reader app for a quiet week** as the rollback origin, then retire it (the retirement runbook is in the operator's notes; deleting the app is a human step).

Known differences to expect after a flip: the cache-bust token does not cover media, sitemaps are `application/xml`, and content-type may carry a charset.

### Rollback

- **A bad edit.** Restore the previous version of the item in the newsroom and save: that is a normal save and re-projects. S3 versioning keeps earlier copies of each page for 90 days for single-page undelete, but it does not roll back a whole site, and it does not record who changed what.
- **A bad site-code or theme deploy.** Redeploy the previous code, then run `papyrus ops content project --all`. Pages mix old and new chrome for about the length of that run.
- **A bad edge change.** Update the edge stack with the previous template (or the previous change set's template). Aliases and DNS never moved, so this is the whole rollback.
- **Back to the Amplify reader.** While the reader app still exists and has not been deleted, swap the origin back with the edge stack's previous template and re-enable the reader id in the site config. After the reader app is deleted, this path is gone.

### Hosting Pretext, for contrast

A Pretext site is one Amplify `WEB_COMPUTE` app (Next.js), with no S3 site bucket and no projection. The server reads published models over the guest identity pool at request time and Next caches each page for its `revalidate` lifetime. Publishing calls the reader's `/api/revalidate` ([Revalidation secret](#revalidation-secret-pretext-sites)). Pages are therefore never "behind" in the projection sense, there is nothing to reconcile, and the bound on staleness is the Amplify CDN layer, about two minutes after a publish. The Amplify CDN cannot be purged, so a site that needs faster freshness puts its own CloudFront in front and lists it in `backend.revalidateDistributionIds`. The Amplify console traps below apply to Pretext sites and to every CMS app.

### Amplify console traps

- **Connecting GitHub in the console overwrites app state.** It can replace the `buildSpec` and the branch environment variables, replace the service role, flip `platform` from `WEB_COMPUTE` to `WEB`, and delete and recreate the stack's branches, which removes the `staging` branch and all branch variables. Record `get-app` and `list-branches` before and diff after; the repair steps are in [Verify and repair after connecting](#verify-and-repair-after-connecting) (Papyrus#184 documented the cross-account part).
- **Amplify domain APIs.** One hostname belongs to one Amplify app across accounts. Deleting an association deletes its distribution and certificate, and a new association gets new ones, so a delete-first cutover has real downtime and no undo. Associations can stick in `PENDING_VERIFICATION` for 30 minutes or more even with a correct validation record. Prefer not to use them for static sites at all (the `papyrus-edge-*` pattern above).
- **Redirect and 404 rules are app config.** They reset if the app is recreated; keep them in the template (`reader.redirects`) for Amplify readers, and in the edge stack for the projection.

### Projection lease (one projection at a time)

Every projection that writes a site bucket (`project`, `project_all`, `project_listings`, `project_item_pages`, a non-dry-run `reconcile`, so also `papyrus ops content project`, `knowledge snapshot --reproject`, the deploy-time render and publish-time item projections) takes a lease first and gives it back in a `finally`. Dry-run reconciles, `--out` and `--from-dir` projections write nothing live and take none.

- Table: `papyrus-projection-locks` (one per account, created by the cloud knowledge run stack). Partition key `publication` (string) is the site bucket name (`PAPYRUS_SITE_BUCKET` or `--bucket`). Attributes: `owner`, `acquiredAt` (ISO), `expiresAt` (epoch seconds, also the DynamoDB TTL attribute), `purpose`.
- Discovery: env `PAPYRUS_PROJECTION_LOCK_TABLE`, else the SSM String parameter `/papyrus/projection-lock/table-name`. Neither found means no lease and projection runs as before. A parameter that exists but cannot be read (access denied) fails loudly.
- Acquire is a conditional put (no item, or `expiresAt` in the past), so a crashed holder blocks nobody for more than the 30 minute TTL. Release and renew only touch an item the caller owns; long writes renew halfway through the TTL.
- A held lease is retried with exponential backoff and jitter (1, 2, 4, 8, then 15 seconds) for `PAPYRUS_PROJECTION_LOCK_WAIT_SECONDS` (default 120; the scheduled cloud run sets a longer wait). Then the projection raises `ProjectionLeaseHeld`. In the content-actions Lambda that becomes a failed projection task (Lambda retry, then the dead letter queue), and a publish-time projection schedules the same retry.
- `PAPYRUS_PROJECTION_LEASE_PURPOSE` labels the holder (for example `cloud-run projection`).

The error reads: `Projection lease for <bucket> is held by <owner> (<purpose>) until <time>; waited <n>s. Another projection of this publication is running. Retry when it finishes; if its holder crashed, the lease expires by itself. To clear it now: aws dynamodb delete-item --table-name <table> --key '{"publication":{"S":"<bucket>"}}'`.

Inspect: `aws dynamodb get-item --table-name papyrus-projection-locks --key '{"publication":{"S":"<bucket>"}}'`. Clear a stuck lease only after confirming the holder is gone: the same command with `delete-item`.

## Anti-patterns

| Anti-pattern | Why it fails |
| --- | --- |
| Threat Intelligence–style **Papyrus fork** | Second product repo + own `WEB_COMPUTE` app per publication; hosting knowledge lives in folklore |
| **Pod-only README** | Next agent copies Pilobolus by accident; no Papyrus template |
| **Cargo-cult SSR `amplify.yml`** | Markus site runs `npm run build`, `ampx pipeline-deploy`, ships `.next`; build breaks or wrong stack |
| **Shared p.apyr.us Amplify app** | Couples unrelated publications; forbidden for Pilobolus CMS |
| **Expect `/newsroom` on static reader** | Markus `WEB` app has no Next.js server; use the newsroom subdomain on the CMS app |
| **Wrong domain zone** (`pilobil.us`) | Typo domain; certs and links diverge from **pilobol.us** |
| **Commit `web/dist/`** | Stale HTML in git; CI drift |

## Related docs

- Renderer axis: [`docs/pluggable-publishers.md`](pluggable-publishers.md)
- New publication bootstrap: [`docs/new-publication-from-corpus.md`](new-publication-from-corpus.md)
- Agent preflight for AWS: `AGENTS.local.md`, `AGENTS.md` (Site hosting pointer)

## Analytics (Google Analytics 4)

The Markus page shell has one optional site-wide setting for analytics,
`SiteChrome.ga_measurement_id`. Set it in the publication's build code (never
from article content), typically only for production builds:

```python
chrome = SiteChrome(
    site_name="Example",
    ga_measurement_id="G-ABC123DEF4" if os.environ.get("PRODUCTION") else None,
)
```

When set, every page rendered through `render_page` gets Google's standard
gtag.js snippet in `<head>`, after `head_html` and before the stylesheets. The
default `None` emits nothing, so existing publications build byte-identically.
The id is validated against the GA4 pattern (`G-` plus alphanumerics); anything
else raises `ValueError`.

`ga_owner_opt_out=True` additionally emits a tiny script before the snippet:
visit any page with `?notrack=1` once per browser to stop counting that browser
(localStorage flag `<sitename>-no-analytics`, which sets Google's
`ga-disable-<ID>`); `?notrack=0` turns counting back on.

### Consent Mode v2 and the consent banner (opt-in)

`SiteChrome.consent_mode` (requires `ga_measurement_id`; `None` by default, which
leaves pages byte-identical) emits Google Consent Mode v2 defaults before
`gtag('config')`, a first-party banner just before `</body>`, and its stylesheet
in `<head>`. In a projection settings file, give `chrome.consent_mode` a mapping
of `ConsentModeSettings` fields; `{}` takes every default.

```json
{"chrome": {"ga_measurement_id": "G-ABC123DEF4", "consent_mode": {"privacy_policy_url": "/privacy.html"}}}
```

- Visitors in `denied_by_default_regions` (shipped: EEA, GB, CH) start with all four
  signals denied; everywhere else starts with `analytics_storage` granted and the
  three `ad_*` signals denied. Region detection is gtag's, never client-side.
- Accept all grants and Reject all denies all four signals via
  `gtag('consent','update')`. The choice is stored in localStorage under
  `<sitename>-consent` with `policy_version` and `retention_days` (default 183);
  raising `policy_version` re-prompts everyone.
- To let visitors change their choice, place
  `<a href="#" data-papyrus-consent-reopen hidden>Cookie settings</a>` in
  `footer_html` (the script unhides it, so it never shows without JS), or add a footer link whose href is `#cookie-settings` (for the standard front end's `footer.columns`, which cannot carry attributes), or call
  `window.papyrusOpenConsentChoices()`.
- `analytics_only: true` (off by default) keeps `ad_storage`, `ad_user_data` and `ad_personalization` denied after every choice: Accept all grants only `analytics_storage`, and the default banner text says the cookies are not used for advertising. Use it for sites that run no advertising.
- Banner wording (`banner_heading`, `banner_message`, `accept_label`,
  `reject_label`, `banner_region_label`, `privacy_policy_url`,
  `privacy_policy_label`) is plain text, HTML-escaped on output. The shipped
  wording is a draft that the site owner must approve.

### Events and address redaction (on whenever a measurement id is set)

With `ga_measurement_id` set, every page also gets two small inline scripts. Nothing changes for a site without an id.

- **Address redaction.** Before `gtag('config')` the page sets `page_location` and `page_referrer` to the address with
  identity-bearing query parameters (`token`, `email`, `ss`, `user_id`, `handle` and similar names), any value that looks
  like an e-mail address, a `ss1_` subject or a long opaque token, and the `#fragment` removed; the same patterns are replaced
  in the path. Campaign parameters such as `utm_source` are kept.
- **`window.papyrusAnalytics.track(name, params)`** sends only these events, with only these parameters, and drops any value
  that looks like an identity. It can never set `user_id`.

  | Event | Parameters | When |
  | --- | --- | --- |
  | `cta_click` | `cta_text`, `cta_location`, `link_url` (host and path only) | automatically, for a link marked `data-cta-location="<place>"` (`[a-z0-9_-]`, up to 40) and for any link to `anth.us/engage` (place = its `cta` query value); text is the link text or `data-cta-text` |
  | `sign_up` | `method` | the newsletter plugin's confirmed page, once per tab session, only with its token |
  | `generate_lead` | `form_id`, `lead_source`, `solution` | a form with `"conversionEvent": "generate_lead"`, only when its endpoint answers 2xx |
  | `view_promotion`, `select_promotion` | `promotion_id`, `promotion_name`, `creative_name`, `location_id` | reserved for sponsor units; the engine fires neither |

  A link inside an element with `data-promotion-id` never reports `cta_click`: a sponsor unit is a promotion, not a call to
  action. Never report a conversion on submit; report it from the success answer. Contact calls to action should point at
  `https://anth.us/engage/?solution=<Product>&cta=<location>`.
- **Documentation sites.** `DocsSiteConfig.ga_measurement_id` (CLI `--ga-measurement-id`) turns all of this on for the docs
  builder with the shipped consent defaults, a "Cookie settings" footer link, and a banner privacy link to
  `privacy_policy_url` (CLI `--privacy-url`, default `https://anth.us/privacy/`).  Point `contact_url` at `https://anth.us/engage/?solution=<Product>&cta=<location>` and the footer's Contact us link reports `cta_click`. Empty keeps analytics off.

## `SITE_ENV` and `PAPYRUS_CONTENT_SOURCE` (staging for Pretext sites)

Two environment variables select what a deployment serves and how it presents
itself. Both are read by `lib/site-env.ts`.

| Deployment | `SITE_ENV` | `PAPYRUS_CONTENT_SOURCE` |
| --- | --- | --- |
| Production | `production` | unset or `published` |
| Pretext staging | `staging` | `drafts` |
| Static staging (Markus) | `staging` | `published` (with `PAPYRUS_STAGING_PREVIEW=static`) |
| Local development | unset (`development`) | unset or `published` |

- `SITE_ENV=production` on an Amplify branch other than `main` (`AWS_BRANCH`)
  resolves to `staging`, so a mis-configured branch stays guarded.
- `drafts` reads the `Item`, `Edition`, `EditionItem` and `MediaAsset` models
  over the signed-in editor's Cognito session (`userPool`, from request
  cookies), uncached. `published` reads the `Published*` models over the
  identity pool (guest). A signed-in user who is not an editor or admin cannot
  read `PublishedItem` over `userPool`, so the two modes use different auth
  modes by design.
- `PAPYRUS_CONTENT_SOURCE=drafts` is refused unless `SITE_ENV=staging`: the
  server fails when `lib/content-repository.ts` loads. **Production never sets
  `drafts`.**
- `/robots.txt` comes from the package's `app/robots.ts` (`lib/robots-policy.ts`):
  `Disallow: /` for staging and development, `Allow: /` for production (no
  sitemap line; Papyrus ships none), and `Disallow: /` always on a CMS-only
  host whose `rootRoute` is `newsroom`, because that host is an editing UI. A
  site-owned `app/robots.ts` overrides it. Consumers need a package version
  whose route manifest lists `app/robots.ts` (releases after next.37) and a
  `papyrus-app sync`.
- Not production means: `Disallow: /` in `robots.txt`, `noindex` meta and
  `X-Robots-Tag`, a "STAGING" banner, and no analytics (`analyticsAllowed()`).
- On a staging deployment the middleware redirects anonymous visitors to
  `/newsroom` (sign-in), returns 403 to signed-in users outside the `editor`
  and `admin` groups, and AppSync enforces the same rule on the data. The
  staging origin must be in `PAPYRUS_OAUTH_REDIRECT_URLS` for hosted-UI
  sign-in.
- Build time: `drafts` reads need the request's cookies, so `next build` cannot
  enumerate editions or articles. `generateStaticParams` returns no routes
  when the content source is `drafts` (`lib/reader-static-params.ts`); the
  edition and article routes render on demand per request. Production
  (`published`) still prerenders every published edition and article.
- Known gap: Pretext index pages list items through editions; a CMS draft that
  is not in an edition is reachable at `/articles/<slug>` only.

Check a running deployment with
`node scripts/check-staging-guards.mjs <base-url> <staging|production>`.

## Static staging (Markus sites)

A Markus-static site previews its DRAFT build on the CMS app's `staging`
branch. The preview is a prebuilt site stored in the private `preview/` prefix
of the media bucket and served by a gated Next route. Design: `docs/standard-site.md`
section 1.10.

Environment on the staging branch (never on `main`):
`SITE_ENV=staging`, `PAPYRUS_STAGING_PREVIEW=static`,
`PAPYRUS_CONTENT_SOURCE=published` (unused in static mode).

How a request is served:

1. `middleware.ts` applies the same Cognito gate as Pretext staging (anonymous
   goes to `/newsroom`, non-editors get 403). In static mode the gate covers
   every path except `/_next`, `/api`, `/newsroom*`, favicon, icons and
   `robots.txt`, including `.html`, `.css` and image paths.
2. The middleware rewrites the path to `/__preview<path>`
   (`/articles/foo.html` reads `preview/articles/foo.html`). The route folder
   is `app/%5F_preview/[[...path]]` because Next treats a folder starting with
   `_` as private; `%5F` yields the literal `/__preview` URL segment.
3. The route tries `preview/<path>`, `preview/<path>.html`,
   `preview/<path>/index.html` and presigns the first existing object with the
   VIEWER's own Cognito credentials (`getUrl` through the server runner, 60
   seconds). AWS enforces access: `amplify/storage/resource.ts` grants
   `preview/*` read to the `editor` and `admin` groups only. The route then
   streams the object with `Cache-Control: private, no-store` and
   `X-Robots-Tag: noindex, nofollow`.
4. The route returns 404 unless the deployment is staging with
   `PAPYRUS_STAGING_PREVIEW=static`. Production never rewrites.
5. A CMS-only host with the newsroom at the root (`newsroomBasePath ""`) owns
   `/` and every path without a `.html` suffix, so only `.html` paths are
   rewritten to the preview and gated; anonymous requests to them go to the
   newsroom sign-in. A storage 403 from the route (a signed-in user outside
   the `editor` and `admin` groups) returns 403, never 500.

Staging build contract (the generated build spec, `PPY-39f928`, implements it):

```bash
papyrus ops content export-published --drafts --out content-export --clean
python reader/build.py --content content-export --out dist
papyrus ops content upload-preview --dir dist
```

Then the CMS Next build (frontend-only, no `backend:` phase). The build runs as
the Amplify service role; the CLI signs AppSync requests with that role's
credentials (SigV4) and the role writes `preview/*`, which the storage rule
grants to no user. No token is minted.

The static reader build is different: it runs
`papyrus ops content export-published --auth guest --out content-export --clean`
with no AWS credentials of its own (Cognito guest read).

`papyrus ops content upload-preview --dir DIR [--bucket B] [--prefix preview/] [--json]`
syncs DIR to the prefix: new or changed files are uploaded (sha256 in object
metadata, content type from the extension, `Cache-Control: no-store`), keys
under the prefix that are not in DIR are deleted, any prefix other than
`preview/` and an empty DIR are refused.

Limits: responses are proxied through compute, so very large objects may hit
the platform response-size limit; measure on a real site before adding a
redirect to the presigned URL.

## Reader media route (`/api/media/*`)

`/api/media/<path>` serves only `media/` objects. Images are proxied through the compute function because the Next.js image optimizer does not follow redirects. Everything else (videos, audio, other files) answers `307` with a short-lived presigned S3 URL, so S3 serves the bytes and honors `Range`. Proxying large files fails with `413` because the SSR compute response size is capped.
