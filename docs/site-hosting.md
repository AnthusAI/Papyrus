# Site hosting options

Status: **Config types live on `SiteBrand`** (`renderer`, `hosting`, `themePack`,
`opsChrome` in `lib/site-brand.ts`). This file remains the hosting runbook.
Markus/static build wiring is still a later child — config is not a renderer.

Kanbus: PPY-17fcfc. First proof: [Pilobol.us](https://github.com/AnthusAI/Pilobol.us)
on **pilobol.us** (Amplify platform `WEB`).

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

## Split reader + CMS (Pilobolus)

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
   records for the registrar; attach apex + `www` in Amplify domain management.
6. **CI invariants** — repo-committed Markdown; `markus convert` **without**
   `--allow-html` for static Markus builds.

Example domain: **pilobol.us** (publication **Pilobolus**, git repo
`AnthusAI/Pilobol.us`). The old spelling `pilobil.us` was a typo — do not create
that zone.

## Static Markus path (amplify-static)

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
pip install "git+https://github.com/AnthusAI/Markus@v0.5.0"
```

See the static template for the full `amplify.yml`.

### Real 404s for missing pages

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
body), for example Anth.us-Papyrus `bin/check-404.py <base-url>`.

The `amplify-app-shell` template sets this catch-all (`/<*>` -> `/404.html`,
`404-200`) on every generated reader app, so a `markus-static` reader must emit
`404.html` at its artifact root.

## SSR Pretext path (amplify-ssr)

Papyrus itself: Next.js + Amplify Gen 2 backend (`ampx pipeline-deploy`),
artifacts under `.next/`, platform `WEB_COMPUTE`. Reader traffic hits AppSync
at request time. **Do not copy this `amplify.yml` onto a Markus static pod.**

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
  configured". Check with
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
- [ ] OIDC role ARN: `arn:aws:iam::335163751677:role/<siteId>-github-ci`
- [ ] Secrets live in SSM only (nothing in GitHub secrets or Amplify variables)
- [ ] Old PAT secret (`amplify/github-app-token`) deleted

## Google sign-in

Google is the standard CMS sign-in. `cms.cognitoDomainPrefix` in `infra/site.json`
is required and becomes the stable Cognito hosted-UI domain; the template never
sets `PAPYRUS_DISABLE_GOOGLE_OAUTH`. After the first stack deploy, per app:

1. In Google Cloud Console, on the OAuth client, add the origin
   `https://<prefix>.auth.us-east-1.amazoncognito.com` and the redirect URI
   `https://<prefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse`. The same
   client can serve several sites.
2. In the Amplify console, **Hosting**, **Secrets**, set `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET` for branch `main`.
3. Redeploy the CMS `main` branch. Details: [`google-oauth-setup.md`](google-oauth-setup.md).

- [ ] Google secrets set on the CMS app (date: ____)

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
   Set `reader.includeWww: true` to also serve `www.<reader.domainName>` from
   the reader app (apex and `www` both map to the reader branch).
5. Wait for ACM validation and registrar NS propagation before accepting
   `https://<domain>` as done.

## Anti-patterns

| Anti-pattern | Why it fails |
| --- | --- |
| Threat Intelligence–style **Papyrus fork** | Second product repo + own `WEB_COMPUTE` app per publication; hosting knowledge lives in folklore |
| **Pod-only README** | Next agent copies Pilobolus by accident; no Papyrus template |
| **Cargo-cult SSR `amplify.yml`** | Markus site runs `npm run build`, `ampx pipeline-deploy`, ships `.next`; build breaks or wrong stack |
| **Shared p.apyr.us Amplify app** | Couples unrelated publications; forbidden for Pilobolus CMS |
| **Expect `/newsroom` on static reader** | Markus `WEB` app has no Next.js server; use desk subdomain on CMS app |
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
`ga-disable-<ID>`); `?notrack=0` turns counting back on. There is no other
consent handling.

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
- Not production means: `Disallow: /` in `robots.txt`, `noindex` meta and
  `X-Robots-Tag`, a "STAGING" banner, and no analytics (`analyticsAllowed()`).
- On a staging deployment the middleware redirects anonymous visitors to
  `/newsroom` (sign-in), returns 403 to signed-in users outside the `editor`
  and `admin` groups, and AppSync enforces the same rule on the data. The
  staging origin must be in `PAPYRUS_OAUTH_REDIRECT_URLS` for hosted-UI
  sign-in.
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
