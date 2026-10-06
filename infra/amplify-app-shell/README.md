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
| Reader app `<siteId>-reader` (`WEB`), `markus-static` only | Branch `main`; static build from the published content export |
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
and [`examples/pretext.site.json`](examples/pretext.site.json) (`pretext`).
`cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS` must include
`http://localhost:3001/` plus `https://<cms domain>/` when `cms.domainName` is set
and `https://<staging domain>/` when staging is enabled and has a domain. Without
a domain the stack appends the app's default `https://main.<app>.amplifyapp.com/`
(and `https://staging.<app>.amplifyapp.com/`) to the branch variable itself.

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
