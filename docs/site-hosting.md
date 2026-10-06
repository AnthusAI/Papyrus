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
   records for the registrar; attach apex + `www` in Amplify domain management.
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

## SSR Pretext path (amplify-ssr)

Papyrus itself: Next.js + Amplify Gen 2 backend (`ampx pipeline-deploy`),
artifacts under `.next/`, platform `WEB_COMPUTE`. Reader traffic hits AppSync
at request time. **Do not copy this `amplify.yml` onto a Markus static pod.**

## One-time GitHub App connection per app

The app shell (`@anthusai/papyrus/infra`, driven by the publication's
`infra/site.json`) creates Amplify apps with no repository and no access token.
Amplify only builds from GitHub after the **Amplify GitHub App** is connected
to each app. This is a console step: there is no API for the handshake. It
replaces the old PAT in Secrets Manager (`amplify/github-app-token`); delete
that secret once every app is connected.

Per app (`<siteId>-cms`, then `<siteId>-reader` for static sites):

1. AWS Console, **AWS Amplify**, **All apps**, choose the app.
2. **Hosting** (or the **Connect repository** banner), **Connect repository**.
3. Choose **GitHub**, **Continue**.
4. In the GitHub pop-up, **Install & authorize** the **AWS Amplify** GitHub App
   for the `AnthusAI` organization, with access to only the site's repository.
5. Back in Amplify pick repository `AnthusAI/<repo>` and branch `main`, **Next**.
6. Review the build settings and leave the generated spec, **Save and deploy**.
7. In the CMS app, if CDK did not create it, add the `staging` branch under
   **Hosting**, **Branches**, **Connect branch**.

Record the date in the site's runbook.

### Python 3.12 in Amplify builds

The Amplify AL2023 build image defaults to Python 3.10 (per AWS docs; not yet
verified on a real build), and `papyrus-newsroom` needs 3.12. Generated build
specs that run Python install `uv`, then `uv python install 3.12`,
`uv venv --python 3.12 .venv` and
`uv pip install --python .venv "papyrus-newsroom[markus]==<papyrusVersion>"`.
The uv cache is kept under `.uv-cache/` and listed in the spec's cache paths.

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
- Known gap: Pretext index pages list items through editions; a CMS draft that
  is not in an edition is reachable at `/articles/<slug>` only.

Check a running deployment with
`node scripts/check-staging-guards.mjs <base-url> <staging|production>`.
