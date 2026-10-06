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
| CMS app `<siteId>-cms` (`WEB_COMPUTE`) | Branch `main` (production, owns the backend) and `staging` (frontend only, reads the production backend) |
| Reader app `<siteId>-reader` (`WEB`), `markus-static` only | Branch `main`; static build from the published content export |
| Domains | CMS `newsroom.<domain>` to `main`, `staging.<domain>` to `staging`, reader apex |
| CMS service role | `AdministratorAccess` (needed by `ampx pipeline-deploy`; documented risk) |
| Compute role | SSR rendering role for the CMS app |
| Reader service role | Least privilege: `ssm:GetParameter(s)` on the CMS app's `/amplify/<cmsAppId>/*` and `/amplify/shared/<cmsAppId>/*`, `s3:GetObject` on `amplify-*/media/*` |

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
and [`examples/pretext.site.json`](examples/pretext.site.json) (`pretext`).
`cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS` must include
`https://<cms domain>/`, `https://<staging domain>/` and `http://localhost:3001/`.

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
