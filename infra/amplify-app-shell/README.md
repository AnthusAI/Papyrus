# Amplify app-shell CDK

IaC for the Amplify **app shell** of a Papyrus publication CMS. The app shell
is the `AWS::Amplify::App` + branch + custom domain + IAM roles — the
container that the Papyrus backend (`amplify/backend.ts`) deploys into via
`ampx pipeline-deploy`. This is the part that used to be created manually in
the Amplify console; it is now CDK so a new site's CMS app is reproducible.

The Papyrus backend itself is **not** defined here. It deploys from the repo
`amplify.yml` build phase (`npx ampx pipeline-deploy`) once Amplify CI runs a
build on the branch.

## Layout

```text
infra/amplify-app-shell/
  bin/app-shell.ts        # CDK app entry; selects site via -c site=<id>
  lib/amplify-app-shell.ts # AmplifyAppShellStack construct
  sites/pilobol-us.ts     # per-site config (add new sites here)
  cdk.json                # default context: site=pilobol-us
```

## Prerequisites

- CDK bootstrapped in the target account/region (`cdk bootstrap`). Already
  done for `us-east-1` / `335163751677` (bootstrap v32).
- A Secrets Manager secret holding a GitHub access token with `repo` (and
  `admin:repo_hook` for auto-build webhooks) scope, scoped to `AnthusAI/Papyrus`.
  Default secret name: `amplify/github-app-token`. Replace the initial token with
  a dedicated fine-grained PAT.

## Deploy a site

```bash
cd infra/amplify-app-shell
npm install
npm run deploy:pilobol-us     # = cdk deploy -c site=pilobol-us
```

Outputs the new Amplify `appId`. The custom domain DNS records are placed
automatically by Amplify when the Route 53 hosted zone is in the same account.

## Add a new site

1. Add an entry to `SITES` in `sites/pilobol-us.ts` (or a new site file).
2. Set the brand's `readerDeployment` (static reader) and `hosting: amplify-ssr`
   (this CMS) in `publications/<brand>/brand.ts`.
3. `npm run deploy:<site-id>`.
4. Populate secrets on the new app (`ampx console` or SSM) for `OPENAI_API_KEY`
   and the JWT secret, then trigger a backend build.

## What this stack creates

| Resource | Purpose |
| --- | --- |
| `AWS::Amplify::App` | WEB_COMPUTE app connected to `AnthusAI/Papyrus` via PAT |
| `AWS::Amplify::Branch` | `main` with `PAPYRUS_SITE_BRAND=<brand>` env vars |
| `AWS::Amplify::Domain` | `newsroom.<site>.us` on the site's Route 53 zone |
| `IAM::Role` (service) | Backend deploy role (ampx pipeline-deploy) |
| `IAM::Role` (compute) | SSR rendering role for WEB_COMPUTE |

## Related

- [`docs/site-workspace.md`](../../docs/site-workspace.md) — local workspace convention.
- [`docs/site-hosting.md`](../../docs/site-hosting.md) — split reader + CMS hosting.
- [`publications/pilobol_us/docs/bootstrap.md`](../../publications/pilobol_us/docs/bootstrap.md) — Pilobolus runbook.
