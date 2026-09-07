# Cursor Cloud Agent: Ryan sandbox backend

Use this runbook when a **Cursor Cloud Agent** (not the Grok Bot box or a local Mac
with `AWS_PROFILE=Ryan`) needs to target the shared **Ryan Amplify sandbox** for
Papyrus authoring and corpus work.

Stack: `amplify-papyrus-ryan-sandbox-adcd88a186`  
AppSync host: `nkqutx` (`us-east-1_WD8fuTRVk` user pool)  
JWT SSM path: `/amplify/papyrus/ryan-sandbox-adcd88a186/PAPYRUS_JWT_SECRET`

`amplify_outputs.json` is gitignored. Do **not** commit it or `.env` (JWTs).

## Required Cursor environment secrets

Attach these to the Papyrus Cloud Agent environment (Dashboard → Environment →
Secrets). Values must allow read access to the Ryan sandbox stack in `us-east-1`.

| Secret | Purpose |
|--------|---------|
| `AWS_ACCESS_KEY_ID` | Credential for `aws` / `ampx` / boto3 |
| `AWS_SECRET_ACCESS_KEY` | Paired secret key |
| `AWS_REGION` | Set to `us-east-1` |

Optional (only if not minting JWTs from SSM):

| Secret | Purpose |
|--------|---------|
| `PAPYRUS_JWT_SECRET` | Direct signing secret for `auth refresh-jwt` when SSM is unavailable |

Already useful but **not** a substitute for AWS:

| Secret | Purpose |
|--------|---------|
| `PAPYRUS_GRAPHQL_ENDPOINT` | Sandbox AppSync URL (may be pre-seeded) |
| `PAPYRUS_GRAPHQL_JWT` | Short-lived authoring token — expires; refresh requires AWS or `PAPYRUS_JWT_SECRET` |

Verify credentials after attaching secrets:

```bash
aws sts get-caller-identity
aws configure get region   # expect us-east-1
```

## Sandbox outputs (replace any demo stub)

Remove or ignore `.papyrus-production-workspace` in this checkout so
`npm run outputs:sandbox` targets the Ryan stack instead of production.

```bash
export AWS_REGION=us-east-1
export PAPYRUS_SANDBOX_AMPLIFY_STACK=amplify-papyrus-ryan-sandbox-adcd88a186
npm run outputs:sandbox
```

Confirm the generated file is real sandbox output:

```bash
node -e "const o=require('./amplify_outputs.json'); console.log('demoStub', '_papyrusDemoStub' in o); console.log('graphql', o.data?.url); console.log('bucket', o.storage?.bucket_name)"
```

Expect `demoStub false`, GraphQL URL containing `nkqutx`, and a non-empty
`storage.bucket_name`.

## Mint authoring JWT into `.env` only

Never print or commit the JWT. Write into local `.env` only:

```bash
cp -n .env.example .env
export AWS_REGION=us-east-1
export PAPYRUS_JWT_SECRET_SSM_PARAM=/amplify/papyrus/ryan-sandbox-adcd88a186/PAPYRUS_JWT_SECRET
npm run auth:refresh-jwt -- --write-env .env
```

Smoke-check (no secret output):

```bash
PYTHONPATH=src python3 -m papyrus_content content inspect
```

## Pilobol.us steering `s3Prefix`

After `amplify_outputs.json` exists, rewrite corpus prefixes from the sandbox
bucket (in-place update of the tracked steering file):

```bash
PYTHONPATH=src python3 -m papyrus_content categories sandbox-steering-config \
  --config corpora/pilobol-us-steering.yml \
  --output corpora/pilobol-us-steering.yml
```

Commit the updated `corpora/pilobol-us-steering.yml` (bucket name is not secret).

## Corpus sync and catalog (pilobol-us)

Source accession lives in [AnthusAI/Pilobol.us](https://github.com/AnthusAI/Pilobol.us)
(PR #3: `corpora/pilobol-us/metadata/catalog.json`, 22 import items). Copy or
submodule that tree into `corpora/pilobol-us/` before sync.

```bash
# 1. Materialize steering config in GraphQL
PYTHONPATH=src python3 -m papyrus_content categories import-config \
  --config corpora/pilobol-us-steering.yml

# 2. Push accession to sandbox S3 (dry-run first)
PYTHONPATH=src python3 -m papyrus_content corpora sync-to-cloud \
  --config corpora/pilobol-us-steering.yml \
  --corpus-key pilobol-us \
  --dry-run

PYTHONPATH=src python3 -m papyrus_content corpora sync-to-cloud \
  --config corpora/pilobol-us-steering.yml \
  --corpus-key pilobol-us

# 3. Register references from catalog
PYTHONPATH=src python3 -m papyrus_content batch register-catalog \
  --config corpora/pilobol-us-steering.yml \
  --corpus-key pilobol-us
```

Worker readiness check:

```bash
PYTHONPATH=src python3 -m papyrus_content corpora worker-bootstrap \
  --config corpora/pilobol-us-steering.yml \
  --json
```

## Related docs

- `docs/aws-sandbox-personal.md` — standing up a **new personal** sandbox (do not
  reuse Ryan's stack from a personal account).
- `docs/newsroom-worker-bootstrap.md` — S3 ↔ local corpus sync semantics.
- `skills/category-steering/SKILL.md` — JWT and steering import workflow.
