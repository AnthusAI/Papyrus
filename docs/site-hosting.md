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
   records for the registrar; attach the apex in Amplify domain management.
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
with `cms.applyCognitoDomainPrefix: true` makes the Cognito hosted-UI domain
predictable; without it Amplify generates the domain (see
[`google-oauth-setup.md`](google-oauth-setup.md)). The template never sets
`PAPYRUS_DISABLE_GOOGLE_OAUTH`. After the first stack deploy, per app:

1. In Google Cloud Console, on the OAuth client, add the origin
   `https://<prefix>.auth.us-east-1.amazoncognito.com` and the redirect URI
   `https://<prefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse`. The same
   client can serve several sites.
2. In the Amplify console, **Hosting**, **Secrets**, set `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET` for branch `main`.
3. Redeploy the CMS `main` branch. Details: [`google-oauth-setup.md`](google-oauth-setup.md).

- [ ] Google secrets set on the CMS app (date: ____)

## Revalidation secret (Pretext sites)

A Pretext publish refreshes the live pages immediately: `content-actions` calls
the reader's `POST /api/revalidate` with a shared secret. The secret is an SSM
SecureString that a human creates once and that is never in `site.json`, Git or
an Amplify variable (those are wiped by stack updates or are visible in
`get-app`). The template derives the parameter name `/papyrus/<siteId>/revalidate-secret`,
sets its *name* (not the value) as branch variable `PAPYRUS_REVALIDATE_SECRET_PARAMETER`
on `main`, and grants `ssm:GetParameter` on exactly that parameter to the app's
SSR compute role. The backend (`amplify/site-backend.ts`, when `revalidateBaseUrl`
is set) passes the same name to `content-actions` and grants it the same single
read. Both sides read the parameter at runtime (the route caches it for five
minutes, so rotation takes effect without a redeploy); a missing or unreadable
parameter makes the route answer 401 and the trigger report an error, never
a bypass.

| Secret | Where it lives | Set by |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Amplify backend secrets | human, console |
| `PAPYRUS_REVALIDATE_SECRET` value | SSM SecureString `/papyrus/<siteId>/revalidate-secret` | human, once (below) |

One-time step after the first stack deploy (never echo the value):

```bash
AWS_PROFILE=legacy aws ssm put-parameter --region us-east-1 \
  --name "/papyrus/<siteId>/revalidate-secret" --type SecureString \
  --value "$(openssl rand -hex 32)"
```

Rotate by re-running it with `--overwrite`. The new value is live within five
minutes. Migration from the old mechanism: `PAPYRUS_REVALIDATE_SECRET` as a branch
variable, `readerCache.revalidateSecret` in `.papyrus/config.yaml` and the
`secret("PAPYRUS_REVALIDATE_SECRET")` backend secret are no longer read. Delete
them, create the SSM parameter, and redeploy; do not reuse the old value.
Sites not on the template must set `PAPYRUS_REVALIDATE_SECRET_PARAMETER` on the
branch and grant their compute role and `content-actions` role the read themselves.

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
| inboundEmail | SES receipt rule set | region, one ACTIVE | `papyrus-site-inbound-<brand>`, created and never activated by CloudFormation |
| inboundEmail | SES receipt rule | inside the rule set | `<brand>-inbound-submissions` |
| inboundEmail | SES domain identity and `_amazonses` TXT | account | not created (verify once by hand); `inboundEmailSes.manageDomainIdentity: true` opts in |
| inboundEmail | SES rule set that another stack owns | account | `inboundEmailSes.existingReceiptRuleSetName` adds only this site's rule to it |
| inboundEmail | EventBridge rules, Lambdas, S3 bucket, IAM roles | stack | generated by CloudFormation (stack-scoped, no fixed names) |
| storageBackups | Backup vault | account | `papyrus-<brand>-<8 hex of stack-name hash>-media-vault` (legacy: `papyrus-<appId>-main-media-backup-vault`) |
| storageBackups | Backup plan, rule names, selection | vault or plan | plan-scoped, no collision |
| slack | Secrets (`PAPYRUS_SLACK_*`) | per app | read from `/amplify/<appId>/...`, per-app by construction |
| consoleResponder | Lambda, event source mapping | stack | generated names |

Receipt rules are created only for the `main` branch of a deployed app, never in
a sandbox or on a `staging` branch.

### Coexisting with a live SES rule set (human steps)

SES allows one active receipt rule set per region, and mail for `p.apyr.us` can
reach only one backend. The old backend's active set is
`papyrus-inbound-p-apyr-us`; the new site creates its own set and leaves the
old one active. Run these with `AWS_PROFILE=legacy` (account 335163751677,
`us-east-1`). Nothing here is run by the deploy.

Before the first deploy with `inboundEmail: true`, check that the domain
identity exists (the old backend already verified `p.apyr.us`; reuse it):

```bash
aws ses get-identity-verification-attributes --identities p.apyr.us --region us-east-1
aws ses describe-active-receipt-rule-set --region us-east-1
```

A domain no other backend verified needs a one-time `aws ses verify-domain-identity --domain <domain> --region us-east-1`,
the returned token as a TXT record `_amazonses.<domain>`, and an MX record
`10 inbound-smtp.us-east-1.amazonaws.com` for the mail host.

After the deploy, the new rule set exists but is inactive. Confirm and review it:

```bash
aws ses list-receipt-rule-sets --region us-east-1
aws ses describe-receipt-rule-set --rule-set-name papyrus-site-inbound-<brand> --region us-east-1
```

At cutover, the single switch (atomic; mail goes to the new media bucket from the next message):

```bash
aws ses set-active-receipt-rule-set --rule-set-name papyrus-site-inbound-<brand> --region us-east-1
```

Rollback is the same command with `papyrus-inbound-p-apyr-us`. Do not delete the
old rule set while it is the rollback. Do not let the old stack's CloudFormation
delete run after the switch without first re-activating a rule set: its custom
resource deactivates ALL rules on delete (`setActiveReceiptRuleSet` with no name).

To share one rule set instead, set `inboundEmailSes.existingReceiptRuleSetName`
to the live set; the new site then adds only its own rule, named
`<brand>-inbound-submissions`. Two rules in one set cannot share a recipient
(`submissions@p.apyr.us` would be claimed twice), so this suits sites with
different recipient domains.

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
