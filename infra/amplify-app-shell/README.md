# Amplify app-shell CDK

IaC for the Amplify **app shell** of a Papyrus publication. The code ships in
the npm package as `@anthusai/papyrus/infra`; each publication supplies its own
`infra/site.json`, so adding a site never edits Papyrus. This directory is the
source of that code (`lib/`), plus example site files and a local CDK entry
point for developing it.

The Papyrus backend (AppSync, Storage, Lambda) is **not** defined here. It is
created inside the CMS app by `ampx pipeline-deploy` during the production
build.

## What a site gets

| Resource | Purpose |
| --- | --- |
| CMS app `<siteId>-cms` (`WEB_COMPUTE`) | Branch `main` (production, owns the backend) and, unless `cms.staging` is `false`, `staging` (frontend only, reads the production backend) |
| Reader app `<siteId>-reader` (`WEB`), `markus-static` only | Branch `main`; static build from the published content export; catch-all rule `/<*>` -> `/404.html` with status `404-200` (real 404 with the site's `404.html`) |
| Domains (optional) | CMS `newsroom.<domain>` to `main`, `staging.<domain>` to `staging`, reader apex. Omit `cms.domainName` / `reader.domainName` / `hostedZoneId` to create no `AWS::Amplify::Domain` and use the default `amplifyapp.com` URLs |
| CMS service role | `AdministratorAccess` (needed by `ampx pipeline-deploy`; documented risk) |
| Compute role | SSR rendering role for the CMS app |
| Authoring role `<siteId>-papyrus-authoring` | What the Papyrus CLI signs AppSync requests (SigV4) with: `appsync:GraphQL` on Query/Mutation fields, `media/*` and preview object access in the site's storage bucket, Amplify jobs on the site's apps. Trust is the account root. No token exists. See [Authoring role and the CLI](../../docs/site-hosting.md#authoring-role-and-the-cli) |
| GitHub CI role `<siteId>-github-ci` (when `github` is set) | Assumed by GitHub Actions through OIDC for the listed branches only; the same statements as the authoring role, optional `cloudformation:*` on this stack (`ciCanDeployInfra`). See [CI access without keys](../../docs/site-hosting.md#ci-access-without-keys) |
| Reader service role | Least privilege: `s3:GetObject` on `amplify-*/media/*` |

No repository and no access token are configured. Apps are manual-deploy until
Amplify's GitHub App is connected once per app in the console (see
[`docs/site-hosting.md`](../../docs/site-hosting.md#one-time-github-app-connection-per-app)).

Build specs are generated from the site config (`lib/build-specs.ts`) and set
on the apps and on the `staging` branch; no `amplify.yml` is needed. Every spec
uses `npm ci`; specs that run Python provision 3.12 with `uv` because the
Amplify build image defaults to Python 3.10 and `papyrus-newsroom` needs 3.12.

## `infra/site.json`

Schema and validation: `lib/site-config.ts` (`parseSiteConfig`). Examples:
[`examples/pilobol-us.site.json`](examples/pilobol-us.site.json) (`markus-static`)
[`examples/pretext.site.json`](examples/pretext.site.json) (`pretext`) and
[`examples/threat-intelligence.site.json`](examples/threat-intelligence.site.json)
(`pretext`, host under a shared root domain).
`cms.cognitoDomainPrefix` is required: the Cognito hosted-UI domain
(`https://<prefix>.auth.<region>.amazoncognito.com`) that Google sign-in needs. The
stack sets it as `PAPYRUS_COGNITO_DOMAIN_PREFIX` on the CMS branches. It is only
used when `cms.applyCognitoDomainPrefix` is `true` (`PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX`);
otherwise Amplify keeps its generated domain, so existing live pools do not
change (see `docs/google-oauth-setup.md`). Google is always on:
`PAPYRUS_DISABLE_GOOGLE_OAUTH`, `PAPYRUS_COGNITO_DOMAIN_PREFIX` and
`PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX` are rejected in `cms.environment`. The secrets `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET` are Amplify backend secrets set in the console, see
[`docs/google-oauth-setup.md`](../../docs/google-oauth-setup.md).
`cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS` must include
`http://localhost:3001/` plus `https://<cms domain>/` when `cms.domainName` is set
and `https://<staging domain>/` when staging is enabled and has a domain. Without
a domain the stack appends the app's default `https://main.<app>.amplifyapp.com/`
(and `https://staging.<app>.amplifyapp.com/`) to the branch variable itself.

Host under a shared root domain: when the root domain (for example `anth.us`) is
also associated with another Amplify app, set `cms.domainName` to the ROOT domain,
`cms.domainPrefix` to the host's label and `cms.stagingDomainPrefix` to an explicit
staging label. [`examples/threat-intelligence.site.json`](examples/threat-intelligence.site.json)
serves `https://threat-intelligence.anth.us/` with staging at
`https://threat-intelligence-staging.anth.us/`. The stack then emits ONE
`AWS::Amplify::Domain` for the root with two sub-domain settings (`main` to the
prefix, `staging` to the staging prefix), because Amplify keys an association by
root domain and an app can hold only one per domain. The staging host is never
derived here (`staging.<zone>` would collide with the other app) and
`cms.stagingDomainName` is rejected next to `cms.domainPrefix`; OAuth redirect
URLs must include both full hosts. Sites that do not set the prefix fields are
unchanged: `cms.domainName` is the full host with an empty prefix and the staging
host is `staging.<zone>` unless `cms.stagingDomainName` is set. Whether Amplify lets
a second app claim a prefix on a root another app already holds is proven with a
real deploy, not by synth (see the Threat Intelligence cutover).

Redirect the root domain apex (and optionally other hosts under the root) to the
primary host: `cms.redirects: [{ "source": "apyr.us", "status": 301 }]` (status
301 or 302, default 301; requires `cms.domainPrefix`).
[`examples/p-apyr-us.site.json`](examples/p-apyr-us.site.json) serves
`https://p.apyr.us/` (staging `https://p-staging.apyr.us/`) and redirects `apyr.us`.
The stack puts one Amplify app custom rule per entry (`https://<source>` to
`https://<primary host>`) ahead of the `/<*>` 404-200 catch-all, and adds a
`main` sub-domain setting for the source's prefix (empty for the apex) to the same
root `AWS::Amplify::Domain`; the app must be associated with the apex for the rule
to run. The template creates no Route 53 records, so existing MX records (such as
`p.apyr.us` inbound email) are never touched. Synth cannot prove path/query
preservation, the apex plus prefix coexisting in one association, or taking the
hosts over from the old app: verify at cutover.

Domain-free and staging-free setup: omit `hostedZoneId`, `cms.domainName`,
`cms.stagingDomainName` and `reader.domainName` (a zone id is only accepted
alongside a domain), and set `cms.staging` to `false` to skip the staging branch
(the default `github.branches` then drops `staging`). Add the domains later and
re-deploy the stack.

Optional `stackName` (default `amplify-app-shell-<siteId>`) names the CloudFormation
stack, so a new stack for the same `siteId` can coexist with an older one until the
older stack is deleted. Existing sites that omit it synthesize identically.

The generated reader build runs `papyrus ops content export-published --auth guest`
(Cognito identity pool guest, no credentials, no SSM token; boto3 comes with the
`markus` extra), so the reader role has no SSM access. Put
`PAPYRUS_GRAPHQL_ENDPOINT`, `PAPYRUS_IDENTITY_POOL_ID`, `PAPYRUS_MEDIA_BUCKET` and
`AWS_REGION` in `reader.environment` (or ship `amplify_outputs.json`).

The generated staging build shares the production backend: it writes `amplify_outputs.json`
with `ampx generate outputs --branch main` (the "No backend environment association
found" line in the staging log is expected) and runs the `papyrus` commands with
`PAPYRUS_ROOT="$PWD"`, because a pip-installed `papyrus` otherwise looks for
`amplify_outputs.json` inside its virtual environment.

The optional `github` block (`owner`, `repo`, `branches` default `["main","staging"]`,
`ciCanDeployInfra` default `false`) must match `repository` and rejects wildcards.
The account-global OIDC provider is a separate stack:
`papyrus-infra synth --account-stack github-oidc` (deploy once per account, and
only if `aws iam list-open-id-connect-providers` shows none).

## Use from a publication repo

```bash
cd infra
npm install @anthusai/papyrus aws-cdk-lib constructs
npx papyrus-infra synth --site site.json
npx papyrus-infra print-buildspec --site site.json --app cms-production   # or cms-staging, reader
```

`synth` prints `synthesized amplify-app-shell-<siteId>` and writes `cdk.out/`.
Deploying (`cdk deploy`) is a separate, reviewed step.

## Develop this code

```bash
cd infra/amplify-app-shell
npm ci
npm run build                                   # tsc --noEmit
SITE=examples/pilobol-us.site.json npm run synth
cd ../.. && npx tsx scripts/test-infra-site-config.ts && node scripts/test-infra-synth.mjs
```

## Related

- [`docs/standard-site.md`](../../docs/standard-site.md) sections 1.6 and 1.10.
- [`docs/site-hosting.md`](../../docs/site-hosting.md) hosting options and the GitHub App connection.
- [`publications/pilobol_us/docs/bootstrap.md`](../../publications/pilobol_us/docs/bootstrap.md) Pilobolus runbook.
