# Pilobolus publication (Papyrus)

Publication-specific brand, theme, and corpus config for **Pilobol.us** live here.
The Papyrus framework imports from this directory; it does not embed Pilobolus
branding in generic framework modules.

## Two deployments (both required)

Pilobolus intentionally splits **reader** and **CMS**:

| Surface | Repo | Amplify app | Platform | Domain |
| --- | --- | --- | --- | --- |
| **Reader** (Markus static HTML) | [AnthusAI/Pilobol.us](https://github.com/AnthusAI/Pilobol.us) | `d1od6t7lzbwanr` | `WEB` | [pilobol.us](https://pilobol.us) |
| **CMS / newsroom** (Papyrus Next.js) | [AnthusAI/Papyrus](https://github.com/AnthusAI/Papyrus) | *create `pilobol-us-cms`* | `WEB_COMPUTE` | `newsroom.pilobol.us` |

The static reader does **not** serve `/newsroom`. Editorial work happens on the
dedicated Papyrus app with its own AppSync backend and S3 corpus bucket. Do **not**
reuse the p.apyr.us production app (`dbsyytcm9drqa`).

`readerDeployment` on `pilobolUsBrand` documents the static reader; `hosting:
{ kind: "amplify-ssr" }` describes this Papyrus checkout.

## Layout

| Path | Purpose |
| --- | --- |
| `brand.ts` | Site brand (masthead, theme pack, corpus paths, deployment metadata) |
| `theme.css` | Pilobolus Shadcn token overrides (`pilobol-us` pack) |
| `docs/bootstrap.md` | CMS Amplify app setup, corpus import, sandbox rehearsal |

Corpus configs live at repo root: `corpora/pilobol-us-*.yml`. Source materials
accrue under `corpora/pilobol-us/` (canonical accession layout).

## Environment (CMS app)

```bash
export PAPYRUS_SITE_BRAND=pilobol-us
export NEXT_PUBLIC_PAPYRUS_SITE_BRAND=pilobol-us
export PAPYRUS_CONTENT_SOURCE=graphql
export PAPYRUS_EDITION_SLUG=current
```

See [docs/bootstrap.md](docs/bootstrap.md) for Amplify branch env vars, JWT mint,
and reference registration.
