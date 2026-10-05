# The standard Papyrus site

Status: **Phase 1 design, for review.** Nothing here is implemented yet.
Kanbus: PPY-a0fb61 (Phase 1) under epic PPY-1f1489. Facts below were verified
against `origin/develop` (7cb1b7e), `AnthusAI/Anth.us-Papyrus@main`,
`AnthusAI/Pilobol.us@main` and `AnthusAI/Threat-Intelligence@main` on
2026-10-05. Existing docs are linked, not repeated:
[site-hosting.md](site-hosting.md), [pluggable-publishers.md](pluggable-publishers.md),
[site-workspace.md](site-workspace.md), [site-stacks.md](site-stacks.md),
[`infra/amplify-app-shell`](../infra/amplify-app-shell/README.md).

## 0. Decisions this design is bound by

Ryan, 2026-10-05, recorded on the epic:

1. The staff CMS UI for every site is the Shadcn **newsroom app**
   (`/newsroom`, `opsChrome: "app"`). Public frontends are **pluggable per
   publication** (Pretext, Markus static, later others).
2. **Same Papyrus software, a separate backend deployment per site**, all
   infrastructure as code. No shared multi-tenant backend.
3. Each publication lives in **its own repo that depends on a pinned Papyrus**
   (never a fork). Threat Intelligence is de-forked.
4. p.apyr.us becomes the Papyrus **product site**; the information-systems blog
   moves to `p.apyr.us/information`; `papyrus.anth.us` redirects to p.apyr.us.

## 1. The standard site

### 1.1 Parts

```text
  author (human in /newsroom, or agent via CLI)
        |
        v
  +-------------------- per-site backend (one per site) ---------------------+
  |  Amplify Gen 2: AppSync + Cognito + S3 + Lambdas    Item -> Published*     |
  +--------------------------------------+----------------------------------+
                                         |  published-content contract (1.6)
              +--------------------------+--------------------------+
              v                                                     v
   CMS app (always)                                     Public frontend (pluggable)
   Next.js, brand = this site, /newsroom                 Pretext: SSR in the CMS app
   Amplify WEB_COMPUTE                                   Markus:  static, own WEB app
```

| Part | Responsibility | Owner |
| --- | --- | --- |
| Papyrus (this repo) | Generic core: Next app, newsroom UI, Amplify backend definition, CLI, renderers, app-shell CDK, build/deploy templates | Papyrus, versioned |
| Publication repo | Brand, theme, content/procedures/doctrine, frontend config, site infra config, the pin | One repo per site |
| Backend | Data, auth, media, agents for exactly one site | Provisioned from the pin |
| CMS app | Staff UI at `/newsroom` (or `/` on a CMS-only subdomain) | Papyrus code + the site's brand |
| Public frontend | Turns published content into pages | Pretext or Markus (pluggable) |

### 1.2 Publication repo layout

What lives in the publication repo versus Papyrus:

```text
<publication-repo>/
  papyrus.pin              # one line: Papyrus commit SHA (+ tag in a comment)
  publication/             # overlays Papyrus's publication/ dir at build (1.7)
    brand.ts               # default-exports the SiteBrand (id, masthead, theme tokens, renderer, ...)
    theme.css
  corpora/                 # steering, newsroom-sections, analysis-profiles YAML
  doctrine/ skills/ procedures/   # editorial identity and site-specific procedures
  content/                 # Git Markdown ONLY until imported into the CMS (Phase 3), then deleted
  reader/                  # only for static frontends (Markus): build entrypoint + site CSS/chrome
  infra/site.json          # input to the app-shell CDK (1.4)
  bin/                     # assemble-cms, build-reader, bump-papyrus
  project/                 # the site's own Kanbus board
```

Stays in Papyrus: everything generic. Moves **out** of Papyrus into publication
repos: `publications/threat_intelligence/` (brand, pictograms, blog-defense,
videoml, seed, skills), `publications/pilobol_us/`, `publications/anth_us/`,
and the editorial-identity dirs `publications/anthus/` and
`publications/pilobolus/`. Papyrus keeps only `publications/papyrus/` as the
default/reference brand. See conflict C1.

### 1.3 Pinning Papyrus: recommendation

**Recommend the `PAPYRUS_PIN` source-checkout pattern, with the SHA in one file
(`papyrus.pin`)**, not an npm or pip package.

| Option | For | Against |
| --- | --- | --- |
| **Pinned source checkout** (Anth.us-Papyrus, Pilobol.us today) | Already works in two sites; exact-commit reproducibility; Papyrus is a Next app + Amplify backend + Python CLI + CDK, not a library, so a checkout is its natural distribution; zero packaging work | Build must clone it; bumps are manual (mitigated by `bin/bump-papyrus`) |
| npm/pip package | Familiar tooling | Papyrus is `private: true`; `pyproject.toml` has `tactus @ file:///Users/ryan/Projects/Tactus` and is `package-mode = false`, so it cannot be installed from outside this machine; Next routes and `amplify/` are not importable as a library. Large packaging project that none of the four sites needs |
| Git submodule | Pin is visible in the tree | Same clone cost; Amplify needs explicit submodule init; no gain over a pin file |

Rules: pin a SHA, never a branch (Anth.us's `amplify.yml` comment is right);
Papyrus tags releases (`v0.N`) so humans read tags and builds verify the SHA; a
publication bumps deliberately in its own PR, and the build prints the pin
first. The pin file replaces the SHA currently embedded inside both
`amplify.yml` files (Anth.us `c98435f`, Pilobol.us `d664fc7`), so CI, local
scripts and the CDK build spec all read one source. Python deps for the
renderer (Pillow, PyYAML, citeproc-py, Markus `v0.5.1`) come from a
`requirements` file shipped **in Papyrus** at the pin, not repeated per repo
(Anth.us pins them by hand in `amplify.yml` today).

### 1.4 Per-site backend via the app shell

`infra/amplify-app-shell` provisions the container; `ampx pipeline-deploy`
(run by the Amplify build) creates the backend inside it. Today it only knows
one site, hardcoded in `sites/pilobol-us.ts` (see C4). Standard:

- The CDK code stays in Papyrus; the **site config moves to the publication
  repo** (`infra/site.json`), passed in as `cdk deploy -c siteConfig=<path>`
  from a checkout at the pin. Adding a site never edits Papyrus.
- Per site it creates: a **CMS app** (`WEB_COMPUTE`, connected to the
  publication repo) with branches `main` (production) and optionally `staging`
  (Gen 2 gives each branch its own backend, so a staging branch is a separate
  AppSync/S3 for free, at a cost); an optional **reader app** (`WEB`) for
  static frontends; custom domains and Route 53 records; the service and
  compute IAM roles; a build webhook on the reader (for rebuild-on-publish).
- Naming: `<site-id>-cms`, `<site-id>-reader`; stack `amplify-app-shell-<site-id>`;
  domains `newsroom.<domain>` (CMS-only subdomain, `rootRoute: newsroom`) and
  the apex for the reader. Account `335163751677`, us-east-1.
- Account-global resources (S3 Vectors index, SES receipt rule sets, backup
  vault) are namespaced by brand **by rule**. Today `amplify/backend.ts`
  special-cases `dbsyytcm9drqa` (lines 41, 69, 179, 299) and `amplify/auth/resource.ts`
  lists its URLs. Replace with: always namespace by brand, with one explicit
  override variable for the legacy p.apyr.us names. See C5.
- Build spec: generated by the CDK from a Papyrus-owned template at the pin
  (today it is a hand-copied string that can drift from root `amplify.yml`),
  and set at app level. Each app calls a repo-local entrypoint
  (`bin/assemble-cms`, `bin/build-reader`), so the publication repo needs no
  `amplify.yml`. This is also how one repo feeds two Amplify apps with
  different build specs.

Environment variables (branch-level; secrets in SSM / Amplify secrets, never in
`site.json`):

| Variable | Purpose |
| --- | --- |
| `PAPYRUS_SITE_BRAND`, `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` | Must equal `publication/brand.ts` id (validated at build) |
| `PAPYRUS_CONTENT_SOURCE=graphql`, `PAPYRUS_EDITION_SLUG` | Reader content source |
| `PAPYRUS_REVALIDATE_SECRET` | Pretext cache revalidation (`/api/revalidate`) |
| `PAPYRUS_ENABLE_*` (CONSOLE_RESPONDER, SLACK, INBOUND_EMAIL, STORAGE_BACKUPS) | Feature flags; default off except on the production branch |
| `PAPYRUS_COGNITO_DOMAIN_PREFIX`, `PAPYRUS_OAUTH_REDIRECT_URLS` | Per-site auth (replaces hardcoded redirect lists) |
| `SITE_ENV` | `production` on the production branch only (1.8) |
| Secrets: `OPENAI_API_KEY`, `PAPYRUS_JWT_SECRET`, Google OAuth | Per site, never shared across sites |

GitHub access: the shell uses a PAT in Secrets Manager
(`amplify/github-app-token`). Anth.us-Papyrus records that Amplify's legacy
token path is deprecated for new apps and that connecting a repo needs the
console GitHub App handshake; that is why it deploys by manual zip. The shell
did connect `pilobol-us-cms` by PAT, so this works today but is a risk. See Q3.

### 1.5 The CMS app: same Amplify app as the reader, or separate?

**Recommend: the CMS app is always its own app; the reader is co-hosted in it
only when the frontend is Pretext (SSR needs the same Next app and AppSync).
Static frontends (Markus) always get their own `WEB` reader app.** This is the
Pilobol.us precedent ([site-hosting.md](site-hosting.md#split-reader--cms-pilobolus))
and it makes the rule mechanical:

| Frontend | Apps | Why |
| --- | --- | --- |
| Pretext (newsprint/blog) | 1: `WEB_COMPUTE` (reader + `/newsroom`) | Pretext is a Next route set reading `Published*` at request time |
| Markus static | 2: CMS `WEB_COMPUTE` + reader `WEB` | Static host cannot run `/newsroom`; a CMS outage or build never takes the public site down; reader rebuilds are independent |

### 1.6 The frontend contract: one published-content contract

Both frontends consume the same thing: the **`Published*` projection**
(`PublishedItem`, `PublishedMediaAsset`, `PublishedEdition`,
`PublishedEditionItem`, categories) in `amplify/data/resource.ts`, readable by
guest IAM. They differ only in transport:

- **Pretext (SSR):** reads `Published*` live through `ContentRepository`
  (`lib/graphql-content-repository.ts`), with ISR revalidated by
  `/api/revalidate`. Exists today.
- **Markus (static):** a build-time **content snapshot** of the same
  projection. `papyrus content export-published --out <dir>` (does not exist)
  writes `manifest.json` (contract version, site, generated-at, item index),
  `items/<slug>.json` (the `PublishedItem` fields plus the fields below), and a
  media manifest with final URLs (Markus has no asset pipeline; URLs must exist
  before conversion). The Markus build reads the snapshot instead of
  `content/*.md`.

The projection needs **three additions** (Phase 2 schema change) because it
cannot carry what Markus sites have today. `Item.body` and `PublishedItem.body`
are `string[]` of flattened paragraphs; there is no Markdown source:

| Field | Why |
| --- | --- |
| `bodyMarkdown` (Markus-flavored source) | Directives, `::image{}`, `[@key]` citations survive. Pretext derives `body[]` from it via the existing `lib/markus-projection.ts` / `lib/markus-to-article.ts`, so authors write one body |
| `aliases` (legacy URL paths) | Source for the 301 `customRules` (Anth.us has 403 entries in `web/custom-rules.json`) |
| `metadata` JSON (front matter, CSL-JSON citations, image focal/layout options) | Round-trips what the importer reads |

Contract version is explicit (`papyrus-published/v1`); frontends refuse a newer
major version.

### 1.7 Brand registration without editing Papyrus

Today `SiteBrandId` is a closed union in `lib/site-brand.ts`
(`"papyrus" | "threat-intelligence" | "pilobol-us" | "anth-us"`),
`SITE_BRANDS` imports each `publications/*/brand.ts`, `ThemePackId` in
`lib/site-stack.ts` is a second closed union, and `normalizeSiteBrandId` has a
hand-written alias table (including `anthus` meaning Threat Intelligence).
Every new site is a Papyrus PR.

Standard:

1. `SiteBrandId` and `ThemePackId` become `string`. Theme tokens already travel
   on the brand (`themeTokens`), so the pack id is just a label.
2. Papyrus ships a fixed overlay point, `publication/brand.ts` (default
   export: a `SiteBrand`), containing the Papyrus brand. `lib/site-brand.ts`
   imports `../publication/brand` and drops `SITE_BRANDS`, the alias table and
   the `?brand=` cookie override (a demo feature that cannot work with one
   compiled-in brand).
3. `bin/assemble-cms` in the publication repo: check out Papyrus at the pin
   into the build workspace, copy the repo's `publication/` over Papyrus's,
   build there. Amplify then sees an ordinary Papyrus app at the workspace
   root. `PAPYRUS_SITE_BRAND` is only validated against the brand id.
4. Backend-synth settings that vary per site (Cognito prefix, OAuth redirects)
   come from env vars, not from `brand.ts`, so `ampx` does not need the brand
   graph.

**Risk to prove first:** Amplify's `WEB_COMPUTE` Next detection and
`ampx pipeline-deploy` working from an assembled tree. A one-day spike on a
throwaway app (Pilobol.us CMS is the right candidate) must pass before the
rest is built. Fallback: publication repo is a thin Next shell with Papyrus
vendored at the pin.

### 1.8 Deploy on push, and environments

- **Deploy on push:** push to `main` builds production; push to `staging`
  builds staging; for both the CMS app and (static sites) the reader app. No
  manual zip deploys. Content publishes also trigger a reader rebuild (2).
- **Environments:** production + staging, per site, on the same app via two
  branches (Anth.us-Papyrus topology). The `SITE_ENV` guard pattern from
  Anth.us-Papyrus (`web/site_env.py`; see its `AGENTS.md`) is adopted as a
  **Papyrus-provided helper** rather than reimplemented per repo: unset or
  invalid `SITE_ENV` means guarded (noindex meta, `Disallow: /`, staging note,
  no analytics, branch-host canonicals); production requires `SITE_ENV=production`
  **and** branch `main`; the build prints the mode first and fails on any page
  that contradicts it. Pretext SSR sites read the same variable at request time
  for the robots and meta guards. `customHttp.yml` stays app-wide and never
  carries `X-Robots-Tag`.
- **CI per repo:** Amplify builds are the deploy. A GitHub Action on PRs runs
  the brand validation, `markus validate` on content (static sites), and
  `check-guards` for staging and production expectations.

## 2. Content flow, end to end

```text
 author in /newsroom (or agent/CLI)
   -> Item (+ MediaAsset)                        EXISTS (no article-editing UI yet)
   -> publish: validate, assign slug/aliases,
      write PublishedItem/PublishedEdition       MISSING (only `content seed-edition` writes Published*)
   -> Published* (guest-readable)                EXISTS
   -> frontend:
        Pretext: SSR read + /api/revalidate      EXISTS
        Markus : export snapshot -> build         MISSING (exporter); Markus renderer EXISTS (Python, reads Git Markdown)
   -> deploy                                     Pretext: part of Amplify build/ISR EXISTS
                                                 Markus : rebuild-on-publish webhook MISSING
```

| Piece | State | Phase |
| --- | --- | --- |
| Item/Edition model, media, Published* models | exists | - |
| Generic **publish step** (Item -> Published*, with version lineage) | does not exist | 2 |
| **Markdown -> Item importer** (front matter, directives, citations, images, aliases) | does not exist | 2 |
| **Published* -> snapshot exporter** and Markus build reading it | does not exist | 2 |
| **Article editing UI** in the newsroom app (Markdown + preview, media upload) | does not exist | 2 |
| **Rebuild-on-publish** for static readers (Amplify webhook called by the publish step) | does not exist | 2 |
| Schema additions (1.6) | do not exist | 2 |
| Pretext ISR revalidation | exists (`app/api/revalidate`, `reader_revalidation.py`) | - |

The Markdown directive and citation vocabulary is already specified in
[markus-content-markup.md](markus-content-markup.md); the importer must treat
it as the lossless interchange format. `ImagePipeline` renditions run at export
time, not import time.

## 3. Per-site gap list

Standard checklist: (a) repo depends on a pin, no fork; (b) brand in the
publication repo; (c) own backend by IaC; (d) CMS app = newsroom app; (e)
frontend consumes the contract; (f) deploy on push; (g) production + staging
with `SITE_ENV`.

| | p.apyr.us | Threat Intelligence | Pilobol.us | Anth.us |
| --- | --- | --- | --- | --- |
| Repo | Papyrus itself (`main`) | Fork, 81 ahead / 210 behind develop | `Pilobol.us` (reader) + Papyrus `main` (CMS) | `Anth.us-Papyrus` (reader), no CMS |
| (a) pin | n/a: is Papyrus | no: fork | reader yes (`d664fc7`); CMS floats on Papyrus `main` | reader yes (`c98435f`); no CMS |
| (b) brand | in Papyrus | in fork | in Papyrus | in Papyrus |
| (c) backend IaC | hand-made app | hand-made app | **yes** (`pilobol-us-cms`, CDK) | none |
| (d) CMS app | yes | yes | yes | none |
| (e) frontend | Pretext, live | Pretext blog, live | Markus, reads Git Markdown, not the CMS | Markus, reads Git submodule |
| (f) deploy on push | yes | last build 2026-08-29 | reader yes; CMS yes | **no: manual zip, repo not connected** |
| (g) staging | no | no | no | yes (`SITE_ENV`) |

### 3.1 p.apyr.us (Phase 4, plus pin prerequisites)

Becomes the product site; four pricing tiers; `/information` blog;
`papyrus.anth.us` redirect.

1. Decide the repo shape (Q1). Recommended: a new publication repo
   `AnthusAI/p.apyr.us` on the standard, with the Amplify app `dbsyytcm9drqa`
   reconnected to it. This makes Papyrus dogfood its own standard and
   stops a Papyrus release push from being a production deploy.
2. Frontend: one `WEB_COMPUTE` app. Marketing and pricing as Next routes (as
   chattic.us's `Chattic.us-web` is Next), `/information` as the Pretext blog
   layout, `/newsroom` for staff. A static marketing site beside an SSR blog
   would force path-mixing across two apps for no benefit.
3. Move the existing AI/ML blog items to `/information`: re-route
   (`rootRoute` stops being `reader`), add 301s from today's article paths.
4. `papyrus.anth.us`: Amplify redirect (301) to `https://p.apyr.us/<same path>`
   plus decommission its app after verification.
5. Replace the `dbsyytcm9drqa` special cases (C5) before moving, because they
   protect production S3 Vectors, backups and SES.

Risks: reconnecting an existing app's repository must not recreate the
backend (data is in AppSync/S3); do it with the production branch paused;
keep the old paths alive via redirects so inbound links and search ranking
survive.

### 3.2 Threat Intelligence: de-fork plan

Target: `AnthusAI/Threat-Intelligence` keeps brand, content, procedures,
videos; depends on a Papyrus pin; Amplify app `d3on1y5vlrxmam` reconnected.
Classification of the fork's diff against the merge-base `95df656`
(126 files, +35k/-19k; core edits are 52 files outside `publications/` and
`src/stories`):

| Diff | Class | Action |
| --- | --- | --- |
| `publications/threat_intelligence/**` (40 files: brand, theme, pictograms, blog-defense, videoml, seed, skills, tests). Note Papyrus `develop` already contains an older copy | **Brand/content: stays in TI** | Becomes the new `publication/` + `procedures/` of the TI repo. Delete the `develop` copy from Papyrus once TI is on the pin |
| `lib/site-brand.ts`, `lib/ti-body-fonts.ts`, `lib/themed-image.ts` | Brand config | Into TI `brand.ts` (fonts are brand tokens). `themed-image` is generic: upstream if still needed |
| `amplify/auth/publication-redirects.ts`, `config/auth-redirect-urls.json`, `lib/site-brand-auth.ts`, `amplify/auth/resource.ts`, `amplify/backend.ts` ("Parameterize Cognito OAuth redirects by publication brand") | **Upstream** | Generic and wanted: becomes the env-var-driven auth config of 1.4. Rework against develop, not cherry-pick |
| `lib/graphql-content-repository.ts` (+177), `lib/cached-content-repository.ts`, `lib/content-repository.ts`, `lib/content-types.ts`, `lib/amplify-server-runtime.ts`, `components/amplify-client-provider.tsx` ("use Cognito guest IAM for SSR GraphQL reads") | **Upstream, check first** | Develop already reads with guest IAM (`authMode: identityPool`), so the fork's fix may be redundant. Diff against develop, port only what is still missing |
| `lib/blog-feature-solver.ts`, `lib/blog-rhythm.ts`, `components/presentation-header.tsx`, `components/presentation-shell.tsx`, `components/article-page.tsx`, `components/archive-shell.tsx`, `components/presentation-rhythm-hrule.tsx`, `components/use-rhythm-overlay.ts`, `lib/newspaper-layout.ts`, `lib/pretext-layout.ts`, `lib/edition-sections.ts`, `app/**` (blog layout work) | **Upstream, as a Pretext `blog` layout improvement** | Largest and riskiest. Generic blog-layout engine (rhythm, feature solver) goes to Papyrus under `renderers/pretext/`; TI-specific tokens (header art, obstacles) go to the brand. Do component-by-component against develop's `renderers/pretext/` restructure |
| `components/article-video.tsx`, `lib/video-mode.ts`, `lib/video-script.ts`, `scripts/videoml/**`, `public/videoml/**`, `amplify/seed/seed-edition-content.ts` | **Decide per file** | Generic video playback may go upstream; the TI video pipeline (`publications/.../videoml`) stays. Open question Q6 |
| `.storybook/**`, `src/stories/**` (29 files) | Drop | Default Storybook scaffold |
| `components/topic-steering-workspace.tsx`, `corpora/papyrus-newsroom-sections.yml`, `src/papyrus_content/{cli,papyrus_config,seed_edition}.py`, `procedures/**`, `features/**`, `scripts/ensure-sandbox-amplify-outputs.mjs`, `package.json` | Mixed | Review individually; most are stale branches of files develop has since reworked |
| `AGENTS.md`, `README.md`, `.env.example`, `.gitignore` | Rewrite | Replaced by the standard repo skeleton |

Method: do not rebase 210 commits. Start a **fresh repo history** from the
standard skeleton (or branch from the old repo for continuity), port the
brand/content, and for each "upstream" row open a PR into Papyrus
`develop` rewritten against current code. Verify with a TI build at the pin
whose output is compared to the live `threat-intelligence.anth.us` pages.

Risks: the blog-layout upstream is a visual regression risk (TI has pixel-level
tests under `publications/threat_intelligence/tests`; carry them); the TI
backend `d3on1y5vlrxmam` must keep its data when its repo changes (as 3.1);
TI's board is the separate `TI` Kanbus board.

### 3.3 Pilobol.us (Phase 3)

Closest to the standard: split reader + CMS, CDK-provisioned CMS, Markus.

1. Move `publications/pilobol_us/` and `publications/pilobolus/` into the
   `Pilobol.us` repo as `publication/`; CMS app `d11eu9hbs2mipk` builds from
   the pub repo via `bin/assemble-cms` at `papyrus.pin` (today it floats on
   Papyrus `main`).
2. Create `infra/site.json`; adopt the generated build spec (C4).
3. Importer (Phase 2) loads the 10 articles in `web/content/articles/` plus
   `web/content/a-fungus-among-us.md` into Items/Published*. Preserve slugs
   and URLs, `::image{}` and assets under `web/content/assets/`, citations,
   and the `og-cover` images.
4. Reader reads the exported snapshot; delete `content/` after the diff
   (rendered HTML from Git vs from the CMS) is byte-identical or explained.
5. Add `staging` branch and `SITE_ENV` guards (reader today has none).
6. Rebuild-on-publish webhook.

Risks: the build contract changes under a live site (verify the HTML diff
before switching); the reader currently builds with no knowledge of the CMS,
so a CMS outage at build time must fail the build, not publish an empty site;
narration/effects scripts in `web/build_via_papyrus.py` are reader-only and
stay in `reader/`.

### 3.4 Anth.us (Phase 3)

Furthest from the standard: no backend, no connected repo, manual zip deploys.

1. Provision CMS app + backend via the shell (`infra/site.json`, brand
   `anth-us`, `rootRoute: newsroom`, domain `newsroom.anth.us` or similar).
2. Connect the repo and move to deploy-on-push for the reader app
   `d2hbn1ig6nqyhy` (Q3), retiring the zip procedure. `customHttp.yml`
   does not apply to zip deploys, so this also fixes that caveat from its
   `AGENTS.md`. App-level `X-Robots-Tag` must be removed before production
   serves (already recorded there).
3. Importer must preserve: ~232 `::image{}` and 197 citation entries (25
   bibliographies); the content-branch dependency (`content/markus-native-markup`
   of `anthus-site-content`, which must never merge to its `main` while the
   Gatsby build reads it); and **URLs and redirects**: 403 entries in
   `web/custom-rules.json` are generated from the corpus by `anthus_urls.py`
   and must come from `aliases` (1.6), with the build's
   `_assert_no_shadowed_pages` check kept.
4. The page-generation modules (`anthus_pages`, `anthus_page_html`,
   home/listings/tags) stay in `reader/`: they are the frontend, not content.
5. Production cutover is a separate, explicit step by Ryan: the repo notes
   `anth.us` is live on `d1ffh6ny5rvtl`/`d23d9f23lg9obr`. Never mutate these
   from the shell work.

Risks: SEO (redirect parity, canonicals, sitemaps: keep
`bin/check-guards.py` and `bin/simulate-redirects.py` as CI gates); the Git
content stays the source of truth until the CMS import is proven identical,
so the two are never edited in parallel.

## 4. Conflicts between current code and Ryan's decisions

- **C1. Brands live in Papyrus.** `publications/{threat_intelligence,pilobol_us,anth_us}` and the closed `SiteBrandId` union contradict "publication repo owns brand" and "register without editing Papyrus" (1.7). Papyrus core also imports TI-only modules (the doc [pluggable-publishers.md](pluggable-publishers.md) 2.6 notes the coupling).
- **C2. The Pilobol.us CMS is Papyrus `main` itself**, not a repo that depends on a pin (CMS app `d11eu9hbs2mipk` floats). `docs/site-hosting.md` and `publications/pilobol_us/docs/bootstrap.md` describe this as the pattern ("AnthusAI/Papyrus + PAPYRUS_SITE_BRAND"); they conflict with decision 3 and must be rewritten when this design is accepted.
- **C3. pluggable-publishers.md says "no runtime plugin loader; compile-time registry"**, and brand mapping is "editing the `SITE_BRANDS` map". The build-time overlay in 1.7 is compatible with the no-runtime-loader rule but changes the "edit the map" step; update that doc.
- **C4. The app shell supports one site only**: `bin/app-shell.ts` imports `resolveSite` from `sites/pilobol-us.ts`, repo is hardcoded `AnthusAI/Papyrus`, single `main` branch, no reader app, and the build spec is a hand-copied string (will drift from root `amplify.yml`).
- **C5. Site-specific logic keyed to the p.apyr.us app id** in `amplify/backend.ts` and `amplify/auth/resource.ts` and `functions/console-chat-responder`. With one backend per site, per-site behavior must come from config, not the app id.
- **C6. The Markus reader "does NOT read the CMS"** (Pilobol.us, Anth.us). The standard requires both frontends to consume the same published-content contract; Git Markdown becomes a transitional source only.
- **C7. Anth.us deploys by manual zip**, which contradicts "deploy on push".
- **C8. `pyproject.toml` has a `file:///Users/ryan/...` dependency** (tactus), blocking any package-based pin on other machines (and CI). Not a conflict with a decision, but it rules out pip as the pin mechanism.

## 5. Open questions for Ryan

1. **p.apyr.us repo:** new publication repo `AnthusAI/p.apyr.us` (recommended, dogfoods the standard), or keep the product site inside Papyrus `main`?
2. **Staging backends:** should every site's CMS get a `staging` branch with its own backend (cost, and a safe place to test imports), or staging only for readers?
3. **GitHub connection:** is the PAT-in-Secrets-Manager route acceptable long term, or should you do the one-time GitHub App console handshake per publication repo (Anth.us notes the token path is deprecated for new apps)?
4. **Assemble-at-build spike:** approve a one-day spike on the Pilobol.us CMS app to prove 1.7 (Amplify + `ampx` from an assembled tree) before any migration work?
5. **Markdown as stored body:** OK to add `bodyMarkdown` to `Item` and `PublishedItem` (1.6) so authors have one body and Pretext derives its flat paragraphs from it?
6. **Threat Intelligence videos:** is the video pipeline (`videoml`, `produce-video`) TI-specific, staying in its repo, or a Papyrus capability other sites will want?
7. **Anth.us production cutover:** after CMS migration, who flips `anth.us` from `d1ffh6ny5rvtl` to the standard reader app, and when (the repo forbids agents from touching DNS)?
8. **Product repo release model:** with sites pinned to Papyrus SHAs, do you want tagged Papyrus releases (`v0.N`) cut from `develop` (recommended) or SHA-only pins?
