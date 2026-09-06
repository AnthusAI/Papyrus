# Personal Amplify sandbox (PPY-6b4094)

Runnable runbook for standing up a **personal** Amplify Gen 2 sandbox in AWS account
`335163751677` (default credential chain, `us-east-1`). Use a git worktree — never the
primary `~/Projects/Papyrus` clone for sandbox work.

## Safety

Never run `ampx pipeline-deploy`. Never modify:

| Resource | ID |
|----------|-----|
| Production Amplify app (p.apyr.us) | `dbsyytcm9drqa` |
| Pilobol.us static app | `d1od6t7lzbwanr` |
| Pilobol.us hosted zone | `Z09961547QX1VHIXOBD7` |

Do **not** use `AWS_PROFILE=Ryan` or Ryan's existing sandbox stack
(`amplify-papyrus-ryan-sandbox-adcd88a186`).

## Prerequisites

```bash
aws sts get-caller-identity   # must be 335163751677
aws configure get region        # must be us-east-1
node -v && npm -v               # Node 20+ recommended
```

`AGENTS.local.md` is optional; when missing, use the default AWS credential chain and
`AWS_REGION=us-east-1`.

## Worktree

```bash
cd ~/Projects/Papyrus
git fetch origin develop
git worktree add -b cursor/chore/PPY-6b4094-sandbox-baseline-3af6 \
  ~/Projects/Papyrus-worktrees/PPY-6b4094-sandbox \
  origin/develop
cd ~/Projects/Papyrus-worktrees/PPY-6b4094-sandbox
npm ci
cp .env.example .env
```

## Sandbox identifier

Amplify limits `--identifier` to **fewer than 15 characters** (`[a-zA-Z0-9-]`).
`ppy-6b4094-sandbox` is rejected; use **`ppy-6b4094`** (10 chars).

## Required secrets (before first deploy)

Google OAuth is enabled by default in `amplify/auth/resource.ts`. For a personal sandbox
without Google credentials, disable it and pre-seed required backend secrets:

```bash
export AWS_REGION=us-east-1

# Disable Google OAuth for sandbox synth/deploy
export PAPYRUS_DISABLE_GOOGLE_OAUTH=1

# Required by graphql-jwt-authorizer and knowledge-query Lambda
printf 'your-sandbox-jwt-secret\n' | npx ampx sandbox secret set PAPYRUS_JWT_SECRET --identifier ppy-6b4094
printf 'sk-placeholder\n'           | npx ampx sandbox secret set OPENAI_API_KEY --identifier ppy-6b4094
```

If deploy fails on `GOOGLE_CLIENT_ID`, either set real Google OAuth secrets or redeploy with
`PAPYRUS_DISABLE_GOOGLE_OAUTH=1`.

## Deploy

```bash
export AWS_REGION=us-east-1
export PAPYRUS_DISABLE_GOOGLE_OAUTH=1

npx ampx sandbox --once --identifier ppy-6b4094
```

First deploy builds Lambda container images and takes ~8–15 minutes.

### If deploy ends in ROLLBACK_COMPLETE

Delete the wedged stack, fix secrets/env, redeploy:

```bash
npx ampx sandbox delete --identifier ppy-6b4094 -y
```

### Generate `amplify_outputs.json`

`ampx sandbox --once` may finish deploy but fail to write outputs (`Could not load
credentials`) if the subprocess loses the credential chain. Regenerate manually:

```bash
npx ampx generate outputs \
  --stack amplify-papyrus-ppy6b4094-sandbox-e7c1507645 \
  --format json \
  --out-dir .
```

Set in `.env`:

```bash
PAPYRUS_SANDBOX_AMPLIFY_STACK=amplify-papyrus-ppy6b4094-sandbox-e7c1507645
PAPYRUS_GRAPHQL_ENDPOINT=https://7bn4apchg5gbnbbigy6dhdoeuy.appsync-api.us-east-1.amazonaws.com/graphql
```

## Teardown inventory (PPY-6b4094 sandbox)

| Field | Value |
|-------|-------|
| AWS account | `335163751677` |
| Region | `us-east-1` |
| Sandbox identifier | `ppy-6b4094` |
| CloudFormation stack | `amplify-papyrus-ppy6b4094-sandbox-e7c1507645` |
| AppSync GraphQL URL | `https://7bn4apchg5gbnbbigy6dhdoeuy.appsync-api.us-east-1.amazonaws.com/graphql` |
| Cognito user pool | `us-east-1_FN5FuCkzg` |
| S3 media bucket | `amplify-papyrus-ppy6b4094-papyrusmediabucket0dab24-falkyyqrxrl3` |
| Created | 2026-09-06 |
| Delete command | `npx ampx sandbox delete --identifier ppy-6b4094 -y` |

## Seed

```bash
export AWS_REGION=us-east-1
npm run seed:amplify -- --identifier ppy-6b4094
```

Uses `.env` seed defaults (`PAPYRUS_SEED_USERNAME`, `PAPYRUS_SEED_PASSWORD`,
`PAPYRUS_SEED_EMAIL`). Profile `threat-intelligence` by default.

Verify (requires `poetry` / `papyrus` CLI if installed):

```bash
poetry run papyrus ops content list articles
```

## Build (requires live AppSync)

`next build` calls `listPublishedEditions` / `listArticleSlugs` at build time. Without a
reachable backend, build fails with `TypeError: Cannot convert undefined or null to object`.

```bash
export AWS_REGION=us-east-1
export PAPYRUS_SANDBOX_AMPLIFY_STACK=amplify-papyrus-ppy6b4094-sandbox-e7c1507645
npm run build
```

**PPY-6b4094 result:** build passed after seed (18 static pages generated).

## BDD baseline

BDD needs a running dev server. Canonical newspaper profile:

```bash
# Terminal A — bypass ensure-sandbox if outputs are already correct:
export PAPYRUS_SITE_BRAND=papyrus
export NEXT_PUBLIC_PAPYRUS_SITE_BRAND=papyrus
npx next dev --hostname 127.0.0.1 -p 3001

# Terminal B
export PAPYRUS_BASE_URL=http://127.0.0.1:3001
npm run test:bdd:canonical
```

**PPY-6b4094 baseline** (sandbox seeded, canonical brand, 2026-09-06):

| Metric | Count |
|--------|------:|
| Scenarios | 117 |
| Passed | 8 |
| Failed | 34 |
| Undefined | 27 |
| Skipped | 48 |
| Steps passed | 99 |

Most failures are newsroom/knowledge-overview scenarios against an empty steering corpus,
not layout regressions. Operator-cli scenarios are largely **undefined** (missing step defs).

## Rough edges discovered

1. **Identifier length** — `ppy-6b4094-sandbox` rejected; max 14 chars.
2. **Google OAuth secrets** — deploy fails without `GOOGLE_CLIENT_ID` unless
   `PAPYRUS_DISABLE_GOOGLE_OAUTH=1`.
3. **Pre-deploy secrets** — `PAPYRUS_JWT_SECRET` and `OPENAI_API_KEY` must exist before
   first successful deploy.
4. **Outputs generation** — `ampx sandbox --once` may not write `amplify_outputs.json`;
   run `ampx generate outputs --stack <name>` manually.
5. **`ensure-sandbox-amplify-outputs.mjs`** — hardcoded Ryan sandbox hosts and defaulted
   `AWS_PROFILE=Ryan`; personal sandboxes were misclassified and regeneration failed on
   machines without that profile. Fixed in this branch to use the default credential chain
   and keep any non-production outputs.
6. **`npm run build` requires AppSync** — pre-existing on `develop`; not a renderer bug.
7. **`poetry` not on PATH** — seed/CLI verify via `poetry run papyrus` skipped when Poetry
   is not installed; `npm run seed:amplify` still works.
8. **BDD vs empty newsroom data** — many newsroom scenarios expect knowledge/section
   steering data beyond fixture seed content.

## JWT authoring (optional)

Mint CLI JWTs against sandbox SSM (after deploy):

```bash
# SSM path pattern: /amplify/papyrus/<sandbox-hash>/PAPYRUS_JWT_SECRET
poetry run papyrus auth refresh-jwt --write-env .env
```
