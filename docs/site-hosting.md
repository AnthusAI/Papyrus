# Site hosting options

Status: **Documented pattern** (types land in `SiteBrand` via PPY-eca592; this file
is the source of truth until then).

Kanbus: PPY-17fcfc. First proof: [Pilobol.us](https://github.com/AnthusAI/Pilobol.us)
on **pilobol.us** (Amplify platform `WEB`).

## Configuration axes (do not collapse them)

A Papyrus publication is configured along **independent** axes:

| Axis | Values (today) | Notes |
| --- | --- | --- |
| **Renderer** | `pretext` \| `markus` | Swappable render path |
| **Layout** | `newsprint` \| `blog` \| `magazine` | Pretext-internal only |
| **Publication** | title / property | e.g. P.apyr.us, Threat Intelligence, Pilobol.us |
| **Hosting** | see `HostingConfig` below | Where built artifacts are served |

Do not fold hosting into renderer choice, and do not invent a per-publication
Papyrus GitHub fork (the Threat Intelligence shape: separate product repo +
dedicated `WEB_COMPUTE` app baked into one checkout).

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

Invalid combos can exist in theory (`pretext` + static is a poor fit today).
Document pairings; do not ship a fake static Pretext pipeline.

## How a new publication opts in

1. **Choose axes** — renderer, layout (if Pretext), publication identity, hosting kind.
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

Example domain: **pilobol.us** (publication **Pilobol.us**, git repo
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

## SSR Pretext path (amplify-ssr)

Papyrus itself: Next.js + Amplify Gen 2 backend (`ampx pipeline-deploy`),
artifacts under `.next/`, platform `WEB_COMPUTE`. Reader traffic hits AppSync
at request time. **Do not copy this `amplify.yml` onto a Markus static pod.**

## Custom domains and Route 53

1. Create a **public** hosted zone for the publication domain (e.g. `pilobol.us`).
2. Give the registrar the zone NS records (Kanbus comment for the operator).
3. Create the Amplify app and verify on the default `*.amplifyapp.com` URL first.
4. Add custom domains in Amplify; let Amplify create alias records in the hosted zone.
5. Wait for ACM validation and registrar NS propagation before accepting
   `https://<domain>` as done.

## Anti-patterns

| Anti-pattern | Why it fails |
| --- | --- |
| Threat Intelligence–style **Papyrus fork** | Second product repo + own `WEB_COMPUTE` app per publication; hosting knowledge lives in folklore |
| **Pod-only README** | Next agent copies Pilobol by accident; no Papyrus template |
| **Cargo-cult SSR `amplify.yml`** | Markus site runs `npm run build`, `ampx pipeline-deploy`, ships `.next`; build breaks or wrong stack |
| **Shared p.apyr.us Amplify app** | Couples unrelated publications; forbidden for Markus pods |
| **Wrong domain zone** (`pilobil.us`) | Typo domain; certs and links diverge from **pilobol.us** |
| **Commit `web/dist/`** | Stale HTML in git; CI drift |

## Related docs

- Renderer axis: [`docs/pluggable-publishers.md`](pluggable-publishers.md)
- New publication bootstrap: [`docs/new-publication-from-corpus.md`](new-publication-from-corpus.md)
- Agent preflight for AWS: `AGENTS.local.md`, `AGENTS.md` (Site hosting pointer)
