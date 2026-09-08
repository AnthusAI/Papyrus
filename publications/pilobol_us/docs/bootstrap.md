# Pilobolus CMS Bootstrap

Pilobolus ships as **two Amplify apps**: a static Markus reader on
[pilobol.us](https://pilobol.us) and a Papyrus **WEB_COMPUTE** CMS for
`/newsroom`. This runbook covers the CMS app only. The reader is documented in
[AnthusAI/Pilobol.us](https://github.com/AnthusAI/Pilobol.us).

## Architecture

```text
pilobol.us (WEB, d1od6t7lzbwanr)     newsroom.pilobol.us (WEB_COMPUTE, pilobol-us-cms)
├── AnthusAI/Pilobol.us              ├── AnthusAI/Papyrus
├── Markus static HTML               ├── Next.js + Amplify Gen 2 backend
└── No /newsroom                     └── /newsroom + own AppSync + S3 bucket
```

Do **not** point Pilobolus corpus import at the shared p.apyr.us backend
(`dbsyytcm9drqa`). That stack holds unrelated AI/ML publication data.

## Configuration files

| File | Purpose |
| --- | --- |
| `corpora/pilobol-us-steering.yml` | Corpus keys, S3 prefixes, classifiers |
| `corpora/pilobol-us-newsroom-sections.yml` | Desk definitions (Field Notes, Strangler Control, …) |
| `corpora/pilobol-us-analysis-profiles.yml` | Biblicus re-index profiles for Pilobolus |
| `publications/pilobol_us/brand.ts` | `PAPYRUS_SITE_BRAND=pilobol-us` runtime config |

After the CMS app deploys, replace `<pilobol-us-cms-media-bucket>` in
`pilobol-us-steering.yml` with the bucket from that app's `amplify_outputs.json`
(`storage.bucket_name`). For sandbox rehearsal, generate a run-local steering
file instead:

```bash
PYTHONPATH=src python -m papyrus.cli ops categories sandbox-steering-config \
  --config corpora/pilobol-us-steering.yml \
  --output .papyrus-runs/pilobol-us-cms/sandbox-steering.yml
```

## 1. Create the CMS Amplify app

Create a **new** Amplify app (console or authenticated CLI):

- **Name:** `pilobol-us-cms`
- **Repository:** `https://github.com/AnthusAI/Papyrus`
- **Platform:** `WEB_COMPUTE`
- **Build spec:** root `amplify.yml` (same as p.apyr.us / Threat Intelligence)
- **Branch:** `main` (or your deploy branch)
- **IAM role:** reuse an existing SSR logging role (e.g. Threat Intelligence app)

### Branch environment variables

Set on the CMS branch (mirror Threat Intelligence `d3on1y5vlrxmam` / `main`):

```bash
PAPYRUS_SITE_BRAND=pilobol-us
NEXT_PUBLIC_PAPYRUS_SITE_BRAND=pilobol-us
PAPYRUS_CONTENT_SOURCE=graphql
PAPYRUS_EDITION_SLUG=current
PAPYRUS_ENABLE_CONSOLE_RESPONDER=false
PAPYRUS_ENABLE_SLACK=false
PAPYRUS_REVALIDATE_SECRET=<generate>
```

Trigger the first deploy. Note the new `appId`, AppSync endpoint, media bucket,
and JWT SSM parameter path from `amplify_outputs.json` / CloudFormation outputs.

Record them here after first deploy:

```text
appId:           <fill after deploy>
defaultDomain:   <appId>.amplifyapp.com
GraphQL:         <from amplify_outputs.json data.url>
Media bucket:    <storage.bucket_name>
JWT SSM param:   /amplify/<appId>/main-branch-<hash>/PAPYRUS_JWT_SECRET
```

## 2. DNS

Hosted zone: `pilobol.us` (`Z09961547QX1VHIXOBD7`). Apex + `www` belong to the
**static reader** (`d1od6t7lzbwanr`). Attach the CMS on a subdomain:

1. Verify the CMS on `https://<appId>.amplifyapp.com/newsroom` first.
2. In Amplify → Domain management → add `newsroom.pilobol.us`.
3. Let Amplify create the alias record in Route 53.

## 3. Operator environment

```bash
PAPYRUS_SITE_BRAND=pilobol-us
NEXT_PUBLIC_PAPYRUS_SITE_BRAND=pilobol-us
PAPYRUS_GRAPHQL_ENDPOINT=<from amplify_outputs.json>
PAPYRUS_JWT_SECRET_SSM_PARAM=/amplify/<appId>/main-branch-<hash>/PAPYRUS_JWT_SECRET
```

Mint a CLI JWT:

```bash
PYTHONPATH=src python -m papyrus.cli auth refresh-jwt --write-env .env
```

## 4. Materialize newsroom config

```bash
STEERING=.papyrus-runs/pilobol-us-cms/sandbox-steering.yml  # or updated pilobol-us-steering.yml

PYTHONPATH=src python -m papyrus.cli sections import \
  --config corpora/pilobol-us-newsroom-sections.yml
PYTHONPATH=src python -m papyrus.cli ops categories import-config --config "$STEERING"
```

## 5. Corpus accession and reference registration

Canonical layout:

```text
corpora/pilobol-us/
  metadata/
    config.json
    catalog.json
  imports/
```

Sync accession to the CMS bucket:

```bash
PYTHONPATH=src python -m papyrus.cli ops corpora sync-to-cloud \
  --config "$STEERING" \
  --corpus-key pilobol-us
```

Register accepted references (ingestion rationale stays on `Reference.metadata` by default):

```bash
PYTHONPATH=src python -m papyrus.cli references prepare-catalog \
  --config "$STEERING" \
  --corpus-key pilobol-us \
  --catalog corpora/pilobol-us/metadata/catalog.json \
  --output .papyrus-runs/pilobol-us-cms/prepared-catalog.json

PYTHONPATH=src python -m papyrus.cli references create-from-catalog \
  --config "$STEERING" \
  --corpus-key pilobol-us \
  --catalog .papyrus-runs/pilobol-us-cms/prepared-catalog.json \
  --status accepted
```

## 6. Verify

- `https://newsroom.pilobol.us/newsroom` loads Pilobolus theme (`pilobol-us` pack).
- GraphQL shows Pilobolus corpora only (not p.apyr.us AI/ML data).
- Reference list matches the accepted catalog count.
- `https://pilobol.us/newsroom` still 404s on the static reader (expected until
  you deliberately add a redirect or link out to the desk URL).

## Newsroom sections

| id | title |
| --- | --- |
| `field-notes` | Field Notes |
| `strangler-control` | Strangler Control |
| `mycelial-signals` | Mycelial Signals |
| `source-intake` | Source Intake |

## Local development

Point `.env` at the Pilobolus CMS sandbox or deployed backend, not p.apyr.us
production, unless you intentionally share a stack:

```bash
PAPYRUS_SITE_BRAND=pilobol-us
npm run dev
# http://localhost:3010/newsroom
```

Demo mode without a backend: `/newsroom?demo=1` (fake GraphQL profile in
`lib/newsroom-demo-profile.ts`).

See also: [`docs/new-publication-from-corpus.md`](../../../docs/new-publication-from-corpus.md),
[`docs/site-hosting.md`](../../../docs/site-hosting.md),
[`skills/publication-bootstrap/SKILL.md`](../../../skills/publication-bootstrap/SKILL.md).
