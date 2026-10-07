# The standard Papyrus site

Status: **Approved design (2026-10-05); packaging spike done (PPY-82be6c, verdict:
works with changes, section 5).** Phase 3 migration issues reference this doc.
The package skeletons exist (PR #100) but nothing is published. Kanbus: PPY-a0fb61 under epic PPY-1f1489. Facts were
verified against `origin/develop` (7cb1b7e), `AnthusAI/Anth.us-Papyrus@main`,
`AnthusAI/Pilobol.us@main` and `AnthusAI/Threat-Intelligence@main` on
2026-10-05. Existing docs are linked, not repeated:
[site-hosting.md](site-hosting.md), [pluggable-publishers.md](pluggable-publishers.md),
[site-workspace.md](site-workspace.md), [markus-content-markup.md](markus-content-markup.md),
[`infra/amplify-app-shell`](../infra/amplify-app-shell/README.md).

## 0. Decisions this design is bound by

Ryan, 2026-10-05 (epic PPY-1f1489 comments):

1. The staff CMS UI for every site is the Shadcn **newsroom app** (`/newsroom`).
   Public frontends are **pluggable per publication** (Pretext, Markus static, later others).
2. **Same Papyrus software, a separate backend deployment per site**, all
   infrastructure as code. No shared multi-tenant backend.
3. Each publication is **its own repo that depends on a versioned Papyrus**
   (never a fork). Threat Intelligence is de-forked. The p.apyr.us publication
   gets its own repo too, disentangled from the Papyrus repo.
4. p.apyr.us becomes the product site; the information-systems blog moves to
   `p.apyr.us/information`; `papyrus.anth.us` redirects to p.apyr.us.
5. **The model is Pilobol.us's shape** (separate staff CMS app with its own
   backend, plus a public site), **with its gaps fixed** (the reader reads the
   CMS; Papyrus is a versioned dependency; the brand lives in the publication
   repo).
6. **Every site has a staging site from day one**: draft articles shown as if
   published, behind access control.
7. **No long-lived access tokens anywhere**: Amplify GitHub App per repo, GitHub
   OIDC for CI, trusted publishing for packages.
8. CMS article bodies are stored as **Anthus Markus** (the directive format),
   not plain Markdown.
9. Papyrus has a **standard VideoML video pipeline** (TI's moves into Papyrus).
10. Papyrus is **published as packages** (PyPI and npm), released with Semantic
    Release; publication repos depend on it normally. Replaces the earlier
    `papyrus.pin` checkout idea.
11. **Public registries:** public npm and PyPI, npm scope `@anthusai`, PyPI name
    `papyrus-newsroom`. **Check name availability before anything is published.**
    (2026-10-05 read-only check: `@anthusai/papyrus`
    returns 404 on npm and `papyrus-newsroom` is not on PyPI, so the names look
    free; scope ownership is not verifiable that way and must be confirmed at
    first publish.)
12. **`anthus-markus` goes to PyPI first** as a prerequisite, and the `tactus
    file:///` dependency is replaced by the PyPI release. (Spike-verified:
    `anthus-markus` 0.5.1 on PyPI is byte-identical to the `v0.5.1` tag, all 15
    `.py` files; Papyrus can depend on `>=0.5.1`.)
13. **GitHub App handshake:** the one-time Amplify GitHub App console step per
    repo is accepted; Ryan does it, and each site's runbook records it.
14. **Staging previews are limited to `editor` and `admin`** for now. A read-only
    `reviewer` group is a later add-on, not part of this design.
15. **Staging reads the production backend**; there is no second persistent
    backend per site. Backend changes are tried in `ampx sandbox` and the `next`
    prerelease.

## 1. The standard site

### 1.1 Parts

```text
  author (human in /newsroom, or agent via CLI)
        |
        v
  +------------------- per-site backend (exactly one per site) ---------------+
  |  Amplify Gen 2: AppSync + Cognito + S3 + Lambdas   Item -> Published*      |
  +-----------+-----------------------------------------+---------------------+
              | drafts + published (editor/admin)       | published (guest read)
              v                                         v
   STAGING frontend (Cognito-gated)              PRODUCTION frontend (public)
   Pretext SSR  or  Markus build of drafts       Pretext SSR  or  Markus static
```

| Part | Responsibility | Lives in |
| --- | --- | --- |
| Papyrus packages | Generic core: newsroom app, backend definition, CLI, renderers, VideoML, app-shell CDK | Papyrus repo, published to npm and PyPI |
| Publication repo | Brand, theme, content, doctrine, procedures, site infra config, frontend glue, package versions | One repo per site |
| Backend | Data, auth, media, agents for exactly one site | Provisioned from the repo at the Papyrus version it depends on |
| CMS app | Staff UI (`/newsroom`) | Next app built in the publication repo |
| Production / staging frontend | Turns content into pages | Pretext or Markus |

**Pilobol.us is the template, with its gaps fixed.** It already has the right
shape (CDK-provisioned CMS app with its own AppSync/S3, a separate public site,
Markus). The standard changes four things: the reader reads the CMS instead of
Git; Papyrus is a versioned package dependency instead of a floating `main`
checkout (CMS) or a SHA in `amplify.yml` (reader); the brand and publication
identity live in the Pilobol.us repo instead of `publications/pilobol_us` in
Papyrus; and it gains a staging site and deploy-on-push for everything.

### 1.2 Publication repo layout

```text
<publication-repo>/
  package.json  pyproject.toml     # depend on @anthusai/papyrus and papyrus-newsroom (1.3)
  papyrus.config.ts                # defineSite({ brand, frontend, ... }): brand registration (1.9)
  publication/                     # theme.css, brand assets, pictograms, video theme
  app/                             # site-owned routes only (marketing pages, overrides); Papyrus routes are generated (1.4)
  amplify/backend.ts data/resource.ts   # one-line re-exports from @anthusai/papyrus/backend
  corpora/  doctrine/  skills/  procedures/   # steering YAML, editorial identity, site procedures
  reader/                          # static frontends only: Markus build entrypoint, site chrome and CSS
  content/                         # Git Markus ONLY until imported into the CMS (Phase 3), then deleted
  infra/                           # own small app: package.json adds aws-cdk-lib + constructs, uses @anthusai/papyrus/infra; site.json
  renovate.json  .github/workflows/
  project/                         # the site's own Kanbus board
```

Moves **out of the Papyrus repo** into publication repos: `publications/threat_intelligence/`
(except the generic VideoML pipeline, 1.11), `publications/pilobol_us/`,
`publications/pilobolus/`, `publications/anth_us/`, `publications/anthus/`.
Papyrus keeps only the `papyrus` reference brand in core (its theme CSS is
`app/papyrus-theme.css`) and, until Phase 3, registers the TI, Pilobol.us and
Anth.us brands in the repo-root `papyrus.config.ts` only. The package contains
no `publications/*` files: `stage.mjs` fails if staging pulls one in, and
`scripts/test-package-contents.mjs` asserts it. See conflict C1.

### 1.3 Packaging Papyrus (replaces the pin)

Papyrus has two halves, so it ships as **two packages on two registries, built
from one repository** (this one) and **released in lockstep** (one version
number, one Semantic Release run):

| Package | Registry | Contents | Replaces |
| --- | --- | --- | --- |
| `papyrus-newsroom` | PyPI | `papyrus`, `papyrus_content` (CLI, newsroom tooling, Markus renderer, export/import, VideoML), `papyrus_newsroom`, `papyrus_knowledge_query`, `papyrus_web`; Lambda handler code | `PAPYRUS_ROOT` + `sys.path` hacks, SHA clones |
| `@anthusai/papyrus` | npm | Newsroom app routes and components, renderers (Pretext), `lib/`, theme packs, the Amplify backend definition and Lambda handlers (`/backend`), `next` config wrapper, `papyrus-app` bin | Fork / checkout of the Next app |

One npm package with subpath exports, not many: splitting UI, backend, infra and
renderers is not needed by any of the four sites (YAGNI); split later if a
consumer wants a slice.

**Infra lives inside `@anthusai/papyrus`** as the subpath export
`@anthusai/papyrus/infra` (the app-shell CDK constructs, replacing
`infra/amplify-app-shell` as a checkout) plus a `papyrus-infra` bin. npm has no
pip-style extras, so the same effect comes from **optional peer dependencies**:
`aws-cdk-lib` and `constructs` are declared in `peerDependencies` with
`peerDependenciesMeta: { "aws-cdk-lib": { optional: true }, constructs: { optional: true } }`.
The newsroom app install stays light and never pulls CDK. The infra entry
checks for CDK on import and fails with a clear message ("`@anthusai/papyrus/infra`
needs `aws-cdk-lib` and `constructs`: run `npm install aws-cdk-lib constructs`")
instead of a raw module-not-found. The site's `infra/` folder is its own small
app with its own `package.json` that depends on `@anthusai/papyrus` and adds
the CDK packages. Maintenance cost: the peer version ranges
(`aws-cdk-lib`, `constructs`) are a compatibility contract; widen or bump them
deliberately in the Papyrus release that changes the CDK code, and the
release's CI builds the infra entry against the lowest and highest supported
CDK versions. Spike-verified: without the CDK the infra entry fails with the
clear message, and a separate `infra/` app synthesizes the app-shell template.

**Install size (known, accepted for now).** The app install is still heavy:
`node_modules` is 814 MB without the CDK (next 158, `@next/swc` 127, mermaid 90,
lucide 46) and 1.8 GB with the Amplify backend dev dependencies (aws-cdk-lib
151, `@aws-amplify` 575). The `infra/` app is about 990 MB, because every
runtime dependency is a regular dependency of `@anthusai/papyrus`. YAGNI
position: accept it; Amplify builds cache `node_modules`. Slim later (an
infra-only entry or moving heavy dependencies to optional peers) if install time
or cost becomes a real problem.

**Python extras.** Base install = PyYAML, citeproc-py, `limatus`. `limatus` is a
**base** dependency because the `papyrus` CLI imports it at import time
(`papyrus_content/editorial_*.py`) and Ryan plans to integrate it more deeply.
The `markus` extra is `anthus-markus`, Pillow and boto3 (the static Markus reader
build needs base + `markus`; boto3 serves guest S3 media and the guest Cognito
identity lane of `export-published --auth guest`). The `newsroom` extra is boto3, markitdown, tiktoken, tactus.
Reader builds stay light; `pip install "papyrus-newsroom[newsroom]"` is for
operators, agents and Lambda bundling. Dev installs need `poetry install
--all-extras`.

**Python version.** `papyrus-newsroom` requires Python >=3.12, but Amplify's
build image defaults to 3.10 (per AWS docs; not yet verified on a real build).
Any reader build that pip-installs it must provision 3.12 first. Lambda
bundling is unaffected: it installs with `--python-version 3.12
--ignore-requires-python` for the Lambda platform.

**Removing `tactus @ file:///Users/ryan/Projects/Tactus` (done in PR #100).**
`tactus >=0.52,<1` from PyPI (0.52.0) replaces it; the wheel metadata has no
`file:` or `git+` requirement. `limatus` is not pinned to an old release: Papyrus
tracks current Limatus with `limatus >=0.29.0,<1`, the same style as the tactus pin.
Local Tactus development uses a dev-only override
(`[tool.uv.sources]` or a local `pip install -e`), never the published
metadata. PyPI rejects direct-URL dependencies, so **`anthus-markus` must come from
PyPI** (builds install it from `git+https://github.com/AnthusAI/Markus@v0.5.1`
today; `pluggable-publishers.md` records PyPI publication as unverified, but
0.5.1 is listed and verified). Prerequisite per decision 12. `{ include =
"publications" }` and `package-mode = false` were removed from the Python
package in #100; publication code no longer ships in the wheel.

**Public registries.** Assumed public (Papyrus is MIT, tier one is "Fork it"):
public npm and PyPI, GitHub provenance attestations (decision 11).

### 1.4 Building the newsroom app and backend from an npm dependency

The hard part: Next route files and `amplify/backend.ts` are not libraries.

**Newsroom app: options**

| Option | How | For | Against |
| --- | --- | --- | --- |
| **A. Thin Next shell + generated route shims (recommended)** | Publication repo is a normal Next app. `withPapyrus(nextConfig)` sets `transpilePackages`, aliases `papyrus-site` -> `./papyrus.config.ts` and `papyrus-site-theme` -> `./publication/theme.css` (a shipped empty stylesheet when that file is absent), and the Tailwind source globs. `papyrus-app sync` (run by `predev` and `prebuild`, output gitignored) writes one-line shims for Papyrus's routes (`export { default } from "@anthusai/papyrus/app/newsroom/page"`, with the route-segment exports `dynamic`/`revalidate` copied literally) and `middleware.ts`. Site-owned files at the same path win | Repo root is an ordinary Next app (Amplify detection, editors, Renovate); brand is a normal import; upgrading Papyrus is a version bump, with no generated code in git to drift | Route-segment config must be literal (generator handles it); Tailwind/shadcn must scan package files; needs a spike |
| B. Assemble from the package at build | `papyrus-app assemble` unpacks an app template from the package into a build dir and builds there | No shims | Build in a non-root dir (Amplify SSR detection risk); site code is overlaid onto a copy; harder local dev |
| C. Prebuilt app image | Papyrus ships a built app; site supplies runtime config | Nothing to build | Brand and `NEXT_PUBLIC_*` are compile-time; Amplify Hosting builds from source; staging and routes cannot be customized |

**Theme CSS alias (decided in PPY-672ea6).** Papyrus's `app/layout.tsx` imports `papyrus-site-theme` next to `./globals.css`, so the package carries no publication CSS. Verified in a scratch consumer (tarball + `withPapyrus`, own `papyrus.config.ts` registering brand `scratch`): the alias resolves under webpack (`next dev`, `next build`) and turbopack (`next dev --turbopack`), both with `publication/theme.css` present and with it absent (the empty stylesheet). No site-owned `app/layout.tsx` fallback is needed. For the turbopack alias the empty stylesheet must be given as a project-relative file path, not a package specifier. A consumer's `tsconfig.json` maps `papyrus-site`, `papyrus-amplify-outputs` and `papyrus-site-theme` in `paths`, and declares `declare module "*.css";`.

**Backend: options**

| Option | How | Verdict |
| --- | --- | --- |
| **A. `amplify/backend.ts` is `export default defineSiteBackend(site)` imported from `@anthusai/papyrus/backend` (recommended)** | `ampx pipeline-deploy` bundles the repo's `amplify/` with esbuild; imports from `node_modules` resolve, **but the backend entry must ship as compiled JS**: Node refuses to type-strip `.ts` under `node_modules` (`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`) and ampx's tsx does not rescue it. The package build compiles `amplify/**` (not the handlers; esbuild bundles those) and `define-site` to ESM `.js` beside the TS. The data schema, auth, storage and function definitions are Papyrus's; the site passes its config (brand id, Cognito prefix, OAuth redirects, feature flags) as an argument, not by env sniffing at synth time | Recommended |
| B. Copy backend source into the repo | Drift and forks by another name | Rejected |

**Python Lambdas.** Today their `resource.ts` copies `src/...` from the repo
(`projectRoot`). As a package, `resource.ts` bundles by `pip install
papyrus-newsroom==<this exact version> -t <asset>` and copies `handler.py` from
`@anthusai/papyrus/backend/handlers`. The backend asserts that its own npm
version equals the installed Python version (lockstep makes this trivial). The
console-chat-responder container image (`PAPYRUS_CONSOLE_RESPONDER_IMAGE_URI`,
`scripts/build-console-responder-image.sh`) is published at release to a public
registry (GHCR) and referenced by version tag; sites no longer build it locally.

**Lockfiles.** A lockfile updated incrementally (swapping the Papyrus tarball)
failed `npm ci` ("Missing: @opentelemetry/core@2.0.0 from lock file");
regenerating from scratch fixed it. CI runs `npm ci --dry-run` in publication
repos (and in Papyrus), and the Renovate guidance is to regenerate rather than
patch the lock when a Papyrus bump breaks `npm ci`.

### 1.5 Releases and updates

- **Semantic Release** in the Papyrus repo (conventional commits are already in
  use, per `AGENTS.md`). One root `release.config.js`: `commit-analyzer` and
  `release-notes-generator` with the `conventionalcommits` preset;
  `@semantic-release/exec` (`prepareCmd` stamps the version into
  `package.json`s and `pyproject.toml` in the build workspace; versions are
  **not committed back**, so no bot pushes to protected branches); publish
  `@anthusai/papyrus` (npm, trusted publishing with
  provenance) and `papyrus-newsroom` (PyPI Trusted Publishing, via
  `pypa/gh-action-pypi-publish`); `@semantic-release/github` for the release.
- **GitFlow fit:** `branches: ["main", { name: "develop", prerelease: "next" }]`.
  `main` cuts stable versions; `develop` cuts `X.Y.Z-next.N` that sites can
  try (the Pilobol.us spike uses it) before promotion to `main`.
- **Auth for release:** GitHub Actions OIDC to npm and PyPI plus the job's
  ephemeral `GITHUB_TOKEN`. No `NPM_TOKEN`, no `PYPI_TOKEN`.
- **Site updates:** Renovate (GitHub App) in every publication repo with one
  `packageRules` entry grouping `@anthusai/papyrus` (in the app and in
  `infra/`'s own `package.json`) and `papyrus-newsroom` into a single PR (lockstep versions must move
  together; Dependabot cannot group across ecosystems). Merge to `staging` to
  preview, then promote to `main`. Backend-affecting releases (schema, function
  changes) deploy the site's backend, so release notes flag them and the
  promotion PR is the checkpoint.

### 1.6 The per-site backend, repo connection and CI auth

`@anthusai/papyrus/infra` (the CDK constructs, run from the site's own `infra/` app) provisions the container; `ampx pipeline-deploy`
(run by the Amplify build) creates the backend inside it. Today the shell
knows one site, hardcoded (C4). Standard:

- Site config is `infra/site.json` in the publication repo; the CDK code comes
  from the package. Adding a site never edits Papyrus.
- Per site it creates: the **CMS app** (`WEB_COMPUTE`) with branches `main`
  (production, owns the backend) and `staging` (frontend only, 1.10); for static
  frontends a **reader app** (`WEB`) with `main` and a build webhook (for
  rebuild-on-publish); domains and Route 53 records; Amplify service and
  compute IAM roles; read access for the staging build to the backend's
  drafts and preview S3 prefix (1.10); the GitHub OIDC role (below).
- Naming: `<site-id>-cms`, `<site-id>-reader`; stack `amplify-app-shell-<site-id>`;
  `newsroom.<domain>` (CMS), `staging.<domain>` (staging), apex (reader). A site
  under a root domain shared with another app sets `cms.domainName` (root),
  `cms.domainPrefix` and `cms.stagingDomainPrefix` instead (one association,
  explicit staging host). `cms.redirects` (`{source, status}`, 301 or 302)
  redirects the root apex or another host under the root to the primary host
  (`examples/p-apyr-us.site.json`: `apyr.us` to `p.apyr.us`, staging `p-staging`).
  Account `335163751677`, us-east-1.
- Account-global resources (S3 Vectors index, SES rule sets, backup vault) are
  namespaced by brand by rule, replacing the `dbsyytcm9drqa` special cases (C5).
- The CDK generates the Amplify build specs from templates in the package, so
  one repo can feed two apps with different specs and no `amplify.yml` is
  needed. Each calls a repo-local entrypoint.

**No long-lived tokens.**

| Need | Mechanism |
| --- | --- |
| Amplify to pull from the repo | **Amplify GitHub App**, installed per publication repo. The connection handshake is a one-time console step (Amplify offers no API for it; Anth.us-Papyrus documents this). The runbook records it per site. The CDK shell no longer takes an access token or a Secrets Manager PAT |
| CI to call AWS (infra deploy on `infra/` changes, `aws amplify start-job`, content CLI jobs) | **GitHub OIDC**: one account-level `AWS::IAM::OidcProvider`, plus per repo a role whose trust is `repo:AnthusAI/<repo>:ref:refs/heads/<branch>`, least privilege (no AdministratorAccess), created by the shell |
| Amplify builds to reach AWS | The Amplify service role (no keys) |
| Staging build to read drafts | The Amplify build role's credentials sign AppSync requests with SigV4 (IAM). No token, no secret |
| Local CLI and automation to write content | SigV4 with the standard AWS credential chain: an SSO profile that assumes the site's `<siteId>-papyrus-authoring` role, or an OIDC role. No token, no JWT authorizer |
| Publishing Papyrus | npm and PyPI trusted publishing |

Environment variables are per branch; secrets (`OPENAI_API_KEY`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) live in SSM/Amplify secrets per site and
are never shared across sites. **Google is the standard CMS sign-in**: every
site gets the Google provider and a Cognito hosted-UI domain (predictable
when `cms.applyCognitoDomainPrefix` is `true` with `cms.cognitoDomainPrefix` in
`infra/site.json`, set on the branches by the app shell; otherwise generated by Amplify); the two Google secrets are Amplify backend secrets set once in the
console ([`google-oauth-setup.md`](google-oauth-setup.md)). Site variables: `PAPYRUS_SITE_BRAND` (validated
against `papyrus.config.ts`), `PAPYRUS_CONTENT_SOURCE` (`published` or `drafts`),
`PAPYRUS_EDITION_SLUG`, `PAPYRUS_REVALIDATE_SECRET_PARAMETER` (Pretext only, set by the template: the SSM parameter *name* of the revalidation secret, never its value; see [`site-hosting.md`](site-hosting.md#revalidation-secret-pretext-sites)), `PAPYRUS_ENABLE_*` flags,
`PAPYRUS_COGNITO_DOMAIN_PREFIX` (from `cms.cognitoDomainPrefix`), `PAPYRUS_OAUTH_REDIRECT_URLS`, `SITE_ENV`. `PAPYRUS_DISABLE_GOOGLE_OAUTH` is for personal sandboxes only and is rejected in `site.json`.

### 1.7 CMS app and public site topology

The CMS app is always its own Amplify app; the public site is co-hosted in it
only when Pretext (SSR needs the same Next app and AppSync). Static frontends
get their own `WEB` reader app. This is the Pilobol.us split
([site-hosting.md](site-hosting.md#split-reader--cms-pilobolus)).

| Frontend | Apps | Why |
| --- | --- | --- |
| Pretext | 1 `WEB_COMPUTE` (public routes + `/newsroom`) | Reads the backend at request time |
| Markus static | CMS `WEB_COMPUTE` + reader `WEB` | A static host cannot run `/newsroom`; a CMS outage never takes the public site down |

p.apyr.us is its own publication repo with one `WEB_COMPUTE` app: marketing and
pricing as site-owned Next routes (like chattic.us), `/information` in the
Pretext blog layout, `/newsroom` from the package.

#### Mounting the reader under a base path

A publication that owns `/` (marketing pages) sets `readerBasePath` in its brand
in `papyrus.config.ts`, as a string literal:

```ts
brand: { /* ... */ readerBasePath: "/information" }
```

`papyrus-app sync` reads that literal and writes the reader route shims (home,
`/[year]/[month]/[day]` and its page/section/article routes, `/articles/[slug]`,
`/archive`, `/settings`; marked `reader: true` in `routes.manifest.json`) under
`app/information/...` instead of the root. `/newsroom`, `/api`, `/_preview`,
`robots.txt` and `middleware.ts` stay where they are, and a site-owned
`app/page.tsx` is kept as usual. With no `readerBasePath`, sync output is
byte-identical to before. `newsroom`, `api` and `_preview` are rejected as base paths.

- Staging gate: with a base path only the reader (`/information` and below) is
  gated; `/` and other site-owned pages are public, `/newsroom`, `/api` and
  `/robots.txt` stay public as before. Anonymous staging visitors to the reader
  redirect once to `/newsroom`.
- Root route: when a base path is set the reader home at the base path ignores
  `rootRoute` (the publication owns `/`); without one, `rootRoute` behaves as before.
- `papyrus://site/home|archive|settings` carry the prefix; `papyrus://site/path/...`
  stays unprefixed because it holds the literal public path (including `/newsroom`).
- robots: `/robots.txt` is site-wide and unchanged; Papyrus ships no sitemap and
  no canonical link tags, so there is nothing to prefix (date-route canonical
  redirects already carry the prefix).
- OAuth return: the callback lands on `/newsroom` and is unaffected.

### 1.8 One published-content contract

Both frontends consume the **`Published*` projection** (`PublishedItem`,
`PublishedMediaAsset`, `PublishedEdition`, `PublishedEditionItem`, categories),
guest-readable. Pretext SSR reads it live through `ContentRepository`
(exists). Markus static reads a build-time **snapshot** of it:
`papyrus ops content export --out <dir>` (does not exist) writes `manifest.json`
(contract version `papyrus-published/v1`, site, generated-at, index),
`items/<slug>.json`, and a media manifest with final URLs.

Because `body` is `string[]` of flattened paragraphs today, the model needs
(Phase 2 schema change, on both `Item` and `PublishedItem`):

| Field | Why |
| --- | --- |
| `bodyMarkus` (Anthus Markus source: `::image{}`, `[@key]`, `::citations{}`, directives) | The stored article body and source of truth, per [markus-content-markup.md](markus-content-markup.md). Never plain Markdown |
| `bodyIr` (derived Markus document IR, schema-versioned) | Written by Papyrus's save/validate step (the editor needs Markus validation on save anyway), never by hand. Lets the Node/SSR side avoid running Python |
| `aliases` (legacy URL paths) | Source of the 301 rules (Anth.us has 403 in `web/custom-rules.json`) |
| `metadata` JSON (front matter, CSL-JSON citations, image options) | Round-trips what the importer reads |

**How Pretext consumes it:** `lib/markus-projection.ts` /
`lib/markus-to-article.ts` already turn a Markus IR into `body[]`, `pullQuotes[]`
and images, with the rule that directives Pretext cannot express recurse into
their children (nothing dropped). Pretext applies that projection to `bodyIr`
at read time. Authors write one Markus body; the legacy `body[]` field is removed
after a one-time conversion of existing p.apyr.us items (no compatibility shim,
per `AGENTS.md`).

### 1.9 Brand registration

Today `SiteBrandId` is a closed union (`"papyrus" | "threat-intelligence" |
"pilobol-us" | "anth-us"`), `SITE_BRANDS` imports each `publications/*/brand.ts`,
`ThemePackId` is a second closed union, and `normalizeSiteBrandId` has a
hand-written alias table. Every new site is a Papyrus PR.

Standard: `SiteBrandId` and `ThemePackId` become `string` (tokens already
travel on the brand). The publication's `papyrus.config.ts` default-exports
`defineSite({ brand, frontend })`; `withPapyrus()` aliases it as `papyrus-site`,
and `lib/site-brand.ts` imports that. The alias table, `SITE_BRANDS` and the
`?brand=` cookie override (a demo feature incompatible with one compiled-in
brand) are removed. `defineSiteBackend(site)` takes the same object, so
`ampx` never needs the brand graph.

### 1.10 Environments: production + staging, standard from day one

Each site has **production** and **staging**. Staging renders **draft** content
as if published, so editors preview real pages before publishing. One backend
per site stays true: **drafts are authored in the production backend, so the
staging frontend reads the production backend** (a separate staging backend
would not contain the drafts). It is a second *frontend* deployment, built
without a `backend:` phase, from the production backend's `amplify_outputs.json`
(`ampx generate outputs`). Risky backend changes are tried in a developer
`ampx sandbox` and the `next` prerelease, not in a second persistent backend.
(Risk to prove in the spike: Amplify branch deployments against another branch's
backend.)

**Access control: the site's own Cognito.** Groups `editor` and `admin`
already exist and are the only groups that can read `Item`
(`amplify/data/resource.ts`, `contentWriteGroups`). Staging requires a
Cognito session in one of them; no shared passwords. Authorization is enforced
by AppSync, not only by the page gate, so a bypassed gate still reads nothing.
A read-only `reviewer` group is out of scope (decision 14).

**Content source for drafts.** A `previewContentRepository` implements
`ContentRepository` over `Item`/`Edition` (latest version, any status) and runs
the same Item-to-published projection function the publish step uses
(`projectItemToPublished`), so frontends receive the identical contract.
Selected by `PAPYRUS_CONTENT_SOURCE=drafts`.

**Auth lanes for SSR (spike-verified).** A signed-in non-editor cannot read
`PublishedItem` over `userPool`: the rules are guest/`identityPool` plus
editor/admin only. So SSR reads published content with `identityPool` (guest)
always, and uses `userPool` only for drafts (editor/admin).

| | Pretext SSR | Markus static |
| --- | --- | --- |
| Where | `staging` branch of the CMS app, `staging.<domain>` | `staging` branch of the CMS app, `staging.<domain>` |
| Drafts | SSR reads Items live with the editor's own Cognito token | `papyrus ops content export --drafts` at build (build-role SigV4, 1.6), then the site's `reader/` Markus build |
| Gate | Next middleware: Cognito session in `editor`/`admin` else hosted-UI login | Same middleware in front of a catch-all route that serves the built site |
| Freshness | Immediate | Rebuild: "Preview" in `/newsroom` starts the staging job (webhook); minutes, not instant |
| Guards | `SITE_ENV=staging`: noindex meta, `Disallow: /`, staging banner, no analytics | Same, via the shared `SITE_ENV` helper |

**Simplest workable gate for static staging.** Not an Amplify WEB app:
the staging build writes its output to a `preview/` prefix in the site's S3
bucket (build role has write on that prefix only; output can be hundreds of MB,
too big to bundle into a compute function), and a Next catch-all route behind
the Cognito middleware streams objects from that prefix with the compute role.
Alternatives rejected: Amplify branch access control (one shared password,
which Ryan ruled out); CloudFront + Lambda@Edge Cognito gate (new moving parts
outside Amplify); WAF IP allowlists (not per-person).

**`SITE_ENV` and production.** Adopt the Anth.us-Papyrus `web/site_env.py`
pattern as a Papyrus-provided helper (build prints the mode first; guarded
unless `SITE_ENV=production` **and** branch `main`; the build fails if any page
contradicts the mode). `customHttp.yml` stays app-wide and never carries
`X-Robots-Tag`.

**Deploy on push.** Push to `main` deploys production and `staging` deploys
staging, for every app. No manual zips. CI (GitHub Actions) validates: brand
config, `markus validate` on content, `check-guards` for staging and production.

### 1.11 Capabilities Papyrus provides to every site

Beyond the above, the package ships **VideoML video pipeline** as a standard
capability (decision 9): `papyrus videos ...` commands, the script DSL, browser
preview bundle, `article-video` playback component, and the `video-mode` helpers,
moved from TI's pipeline (`publications/threat_intelligence/videoml/*`,
`components/article-video.tsx`, `lib/video-*.ts`, `scripts/videoml/*`).
Brand-specific parts (title-slide and quote-card components, rhythm tokens,
pictogram art) are supplied by the publication through `brand.video`.

## 2. Content flow, end to end

```text
 author in /newsroom (or agent/CLI)
   -> Item (bodyMarkus; bodyIr derived on save)          model EXISTS; bodyMarkus/bodyIr and editing UI MISSING
   -> staging: drafts-as-published, Cognito-gated        MISSING (preview repository, gate, export --drafts)
   -> publish: validate, slug/aliases, projectItemToPublished -> Published*   MISSING (only `content seed-edition`)
   -> Published* (guest-readable)                        EXISTS
   -> production frontend:
        Pretext: SSR + /api/revalidate                   EXISTS
        Markus : export snapshot -> build -> deploy      MISSING (exporter); Markus renderer EXISTS
   -> rebuild-on-publish (Amplify webhook, static)       MISSING
```

| Piece | State | Phase |
| --- | --- | --- |
| Item/Edition model, media, Published* | exists | - |
| **Published packages + Semantic Release** (1.3, 1.5); skeletons and PyPI deps exist (#100), nothing published | partly | 2 (first: everything else consumes it) |
| `@anthusai/papyrus/infra` subpath + optional CDK peers (exists, spike-proven), GitHub OIDC roles, GitHub App runbook | partly | 2 |
| `defineSite`/`withPapyrus`/`papyrus-app`, `defineSiteBackend`; remove built-in `publications/*` brands from the tarball (C1) | spike versions exist | 2 |
| Schema additions (1.8), one-time `body[]` conversion | do not exist | 2 |
| Generic **publish step**, **Markus importer**, **exporter** (published and drafts) | do not exist | 2 |
| **Preview repository**, staging gate, staging branch/export job | do not exist | 2 |
| **Article editing UI** in the newsroom app (Markus editor + validation + preview) | does not exist | 2 |
| **Rebuild-on-publish** webhook | does not exist | 2 |
| VideoML as a Papyrus capability | exists only inside TI's fork | 2 |
| Pretext ISR revalidation | exists | - |

The importer treats the Markus directive and citation vocabulary as lossless
interchange. `ImagePipeline` renditions run at export/build time.

## 3. Per-site gap list

Checklist: (a) depends on versioned Papyrus packages; (b) brand in its own repo;
(c) own backend by IaC; (d) CMS app = newsroom app; (e) frontend consumes the
contract; (f) deploy on push, GitHub App, no stored tokens; (g) staging with
drafts behind Cognito.

| | p.apyr.us | Threat Intelligence | Pilobol.us | Anth.us |
| --- | --- | --- | --- | --- |
| Repo today | the Papyrus repo (`main`) | fork, 81 ahead / 210 behind develop | `Pilobol.us` (reader) + Papyrus `main` (CMS) | `Anth.us-Papyrus` (reader), no CMS |
| (a) packages | n/a: is the product repo | no: fork | reader: SHA clone; CMS: floats on `main` | reader: SHA clone; no CMS |
| (b) brand | in Papyrus | in fork | in Papyrus | in Papyrus |
| (c) backend IaC | hand-made app | hand-made app | **yes** (CDK) | none |
| (e) frontend | Pretext, live | Pretext blog, live | Markus; reads Git, not CMS | Markus; reads Git submodule |
| (f) deploy | push (token-based connection) | last build 2026-08-29 | push; CMS connected by shell PAT | **manual zip; repo not connected** |
| (g) staging | no | no | no | branch exists (`SITE_ENV`), no drafts, public |

### 3.1 p.apyr.us (Phase 4)

1. New repo `AnthusAI/p.apyr.us` on the standard (decision 3); Papyrus repo stops
   deploying anything (its CI becomes tests + release). Reconnect Amplify app
   `dbsyytcm9drqa` to the new repo through the GitHub App without recreating
   the backend (the data stays in AppSync/S3): pause the production branch,
   reconnect, verify, resume.
2. Frontend: one `WEB_COMPUTE` app. Marketing and four-tier pricing as site-owned
   routes; `/information` in the Pretext blog layout; AI/ML blog items convert
   `body[]` to `bodyMarkus`; 301s from today's article paths.
3. `papyrus.anth.us` -> Amplify 301 to `https://p.apyr.us/<path>`, then
   decommission after verification.
4. Replace the `dbsyytcm9drqa` special cases (C5) first; they protect
   production S3 Vectors, backups and SES.

Risks: reconnect must not rebuild the backend; keep old paths alive via
redirects; the product-site rewrite is a content/design task, separate from the
pattern.

### 3.2 Threat Intelligence: de-fork plan

Target: `AnthusAI/Threat-Intelligence` keeps brand, content, procedures; depends
on the packages; Amplify app `d3on1y5vlrxmam` reconnected via the GitHub App.
Classification of the fork's diff against merge-base `95df656` (126 files,
+35k/-19k; 52 are core edits outside `publications/` and `src/stories`):

| Diff | Class | Action |
| --- | --- | --- |
| `publications/threat_intelligence/**`: brand, theme, seed, pictogram art, blog-defense, skills, tests (note: Papyrus `develop` still has an older copy) | **Brand/content: stays in TI** | Becomes `publication/`, `procedures/`, `skills/`. Delete the `develop` copy once TI is on the packages |
| `publications/.../videoml/*` pipeline (`video_pipeline.py`, `videos_commands.py`, `videos_dsl.py`, `preview-bundle`, `browser-bundle`, `seed-video-catalog`), `components/article-video.tsx`, `lib/video-mode.ts`, `lib/video-script.ts`, `scripts/videoml/**`, `public/videoml/**` | **Upstream: standard VideoML capability** (decision 9) | Rework against develop as `papyrus videos` + npm module |
| `ti-title-slide`, `ti-quote-card`, `ti-video-rhythm`, `pictograms/art.tsx` | Brand | Stay; registered through `brand.video` |
| `pictograms/system.tsx`, `registry.ts` | Upstream if generic | Decide per file; default: system upstream, art stays |
| `lib/site-brand.ts`, `lib/ti-body-fonts.ts` | Brand config | Into TI `papyrus.config.ts` (fonts are brand tokens) |
| `amplify/auth/publication-redirects.ts`, `config/auth-redirect-urls.json`, `lib/site-brand-auth.ts`, `amplify/auth/resource.ts`, `amplify/backend.ts` | **Upstream** | Becomes the `defineSiteBackend(site)` auth config (1.6); rework against develop, no cherry-pick |
| `lib/graphql-content-repository.ts`, `cached-content-repository.ts`, `content-repository.ts`, `content-types.ts`, `amplify-server-runtime.ts`, `amplify-client-provider.tsx` | **Upstream, check first** | Develop already reads with guest IAM (`authMode: identityPool`); port only what is missing |
| `lib/blog-feature-solver.ts`, `blog-rhythm.ts`, `components/presentation-header.tsx`, `presentation-shell.tsx`, `article-page.tsx`, `archive-shell.tsx`, `presentation-rhythm-hrule.tsx`, `use-rhythm-overlay.ts`, `lib/newspaper-layout.ts`, `pretext-layout.ts`, `edition-sections.ts`, `app/**` | **Upstream: Pretext `blog` layout** | Largest and riskiest. Generic engine into `renderers/pretext/`; TI header art and obstacles to the brand. Component by component |
| `.storybook/**`, `src/stories/**` | Drop | Scaffold |
| `components/topic-steering-workspace.tsx`, `corpora/papyrus-newsroom-sections.yml`, `src/papyrus_content/{cli,papyrus_config,seed_edition}.py`, `procedures/**`, `features/**`, `scripts/ensure-sandbox-amplify-outputs.mjs`, `package.json` | Mixed | Review individually; most are stale versions of files develop reworked |
| `AGENTS.md`, `README.md`, `.env.example`, `.gitignore` | Rewrite | Standard skeleton |

Method: no 210-commit rebase. Fresh publication-repo history from the standard
skeleton (keep the old repo for continuity), port brand/content, and open one
Papyrus PR per upstream row against current code. Verify by comparing a build on
the packages against live `threat-intelligence.anth.us`.

Risks: the blog-layout upstream is a visual-regression risk (carry TI's
pixel-level tests); the TI backend must keep its data when its repo changes;
the video pipeline move is the second-largest piece after the layout; TI's
board is the separate `TI` Kanbus board.

### 3.3 Pilobol.us (Phase 3; first to migrate, and the spike's site)

1. Move `publications/pilobol_us/` and `publications/pilobolus/` into the repo
   as `papyrus.config.ts`/`publication/`/`corpora/`; the repo depends on the
   packages. CMS app `d11eu9hbs2mipk` builds from the Pilobol.us repo (today it
   floats on Papyrus `main`).
2. `infra/site.json`; GitHub App connection for the CMS and reader apps; drop
   the PAT.
3. Importer loads the 10 articles in `web/content/articles/` and
   `web/content/a-fungus-among-us.md`; preserve slugs, `::image{}` assets under
   `web/content/assets/`, citations, `og-cover` images.
4. Reader reads the exported snapshot; delete `content/` after a rendered-HTML
   diff (Git vs CMS) is identical or explained.
5. Add the `staging` branch with drafts export and the Cognito gate;
   rebuild-on-publish webhook.

Estimate (spike): 4-6 working days for the CMS app, backend and staging gate,
once the Phase 2 pieces exist (excluding the importer/exporter and reader snapshot):
release pipeline and extras fixes 1-1.5, brand/config move 0.5, repo scaffold +
`infra/site.json` + GitHub App + replacing the PAT 1-1.5, CMS app with backend
pipeline verified against production data 1-1.5, staging branch + gate +
`SITE_ENV` guards 1. Biggest risk: attaching the live CMS app `d11eu9hbs2mipk`
to the new repo without rebuilding its backend.

Risks: the build contract changes under a live site (verify the HTML diff
first); a CMS outage at build time must fail the build, not publish an empty
site; narration/effects scripts in `web/build_via_papyrus.py` are reader-only
and stay in `reader/`.

### 3.4 Anth.us (Phase 3)

`anth.us` is **live on the Markus reader as of 2026-10-04** (app
`d2hbn1ig6nqyhy`, branch `main` = production, `staging` = guarded copy). What
remains is making it standard; there is no cutover decision left. Note that its
`AGENTS.md` still says "STAGING, not production" and "no custom domain"; that
text is stale and gets rewritten in this phase.

1. Provision CMS app + backend (`infra/site.json`, `papyrus.config.ts` with brand
   `anth-us`, `newsroom.anth.us`).
2. Connect the repo to the reader app with the GitHub App and retire manual zip
   deploys (also fixes the caveat that `customHttp.yml` does not apply to zip
   deploys). Remove the app-level `X-Robots-Tag` header flagged in its
   `AGENTS.md`.
3. Importer must preserve: ~232 `::image{}` and 197 citation entries (25
   bibliographies); the content-branch dependency (`content/markus-native-markup`
   of `anthus-site-content`); and **URLs and redirects**: 403 entries in
   `web/custom-rules.json`, generated today by `anthus_urls.py`, must come from
   `aliases`, with `_assert_no_shadowed_pages` kept.
4. Page-generation modules (`anthus_pages`, `anthus_page_html`, home/listings/
   tags) stay in `reader/`: they are the frontend, not content.
5. Staging: the existing guarded `staging` branch becomes the Cognito-gated
   drafts site (1.10); today it is public with noindex.

Risks: live SEO (keep `bin/check-guards.py` and `bin/simulate-redirects.py` as
CI gates); Git content stays source of truth until the CMS import is proven
identical, never edited in parallel; `anth.us` is production now, so every step
is verified on staging first.

## 4. Conflicts between current code and the decisions

- **C1. Brands live in Papyrus.** `publications/{threat_intelligence,pilobol_us,anth_us}` and the closed `SiteBrandId`/`ThemePackId` unions contradict "brand in its own repo" and "register without editing Papyrus". Core imports TI-only modules ([pluggable-publishers.md](pluggable-publishers.md) 2.6).
- **C2. The Pilobol.us CMS is Papyrus `main`**, not a repo depending on a versioned Papyrus. `docs/site-hosting.md` and `publications/pilobol_us/docs/bootstrap.md` document that as the pattern; they must be rewritten.
- **C3.** `pluggable-publishers.md` says brands are added by "editing the `SITE_BRANDS` map"; replaced by 1.9. Its no-runtime-plugin-loader rule stays valid.
- **C4. The app shell supports one site**: `bin/app-shell.ts` imports `sites/pilobol-us.ts`, repo hardcoded to Papyrus, single `main` branch, no reader app, a hand-copied build spec, and a **GitHub PAT from Secrets Manager** (`amplify/github-app-token`, `githubTokenSecretName`), which decision 7 forbids.
- **C5. Site logic keyed to the p.apyr.us app id** in `amplify/backend.ts` (lines 41, 69, 179, 299), `amplify/auth/resource.ts`, `functions/console-chat-responder`.
- **C6. The Markus readers do not read the CMS** (Pilobol.us, Anth.us).
- **C7. Anth.us deploys by manual zip.**
- **C8. Packaging blockers** (`tactus @ file:///...`, `package-mode = false`, `private: true` package.json, Lambda bundling copying `src/`): resolved by the spike skeletons in #100 (1.3, 1.4); publishing is still to do.
- **C9. `Item.body` is `string[]`** with no Markus source; reader and staging cannot represent directives, citations or aliases.
- **C10. VideoML lives in TI's fork** (and an older copy in Papyrus's `publications/threat_intelligence`), not as a Papyrus capability.

## 5. The spike (done: PPY-82be6c, PR #100)

**Verdict (2026-10-05): the packaging approach works with changes.** Route-shim
option A (app) and `defineSiteBackend` option A (backend) both hold; the
option B fallback (assemble the app at build) is not needed. Proven on a
scratch copy of the Pilobol.us setup with local packs only (`npm pack` tarball
`0.1.0-next.6`, local wheel `0.1.0.dev6`; nothing published, no production app
touched; scratch AWS resources and repo deleted). The changes it forced are
folded into sections 1.3, 1.4, 1.10 and 4.

Also measured: a sandbox backend deploy takes about 9.5 minutes. PR #101
repaired the inbound-email CI job (it had been red on every run since June) by
installing the `newsroom` extra and typescript; the same PR made `limatus` a
base dependency.

### Acceptance checklist

Prerequisites
- [ ] Name availability re-checked immediately before first publish (`@anthusai/papyrus`, `papyrus-newsroom`); npm scope ownership confirmed. (Needs Ryan.)
- [x] `anthus-markus` on PyPI matches the `v0.5.1` tag; `tactus` and `limatus` resolve from PyPI; no `file://` or `git+` dependency remains in the wheel metadata.

Packages
- [ ] Papyrus `develop` release workflow publishes `X.Y.Z-next.N` of both packages via Semantic Release with OIDC trusted publishing (no `NPM_TOKEN`/`PYPI_TOKEN`). Not done: spike used local packs.
- [ ] Versions are identical across the two packages; the backend's version assertion passes. (Lockstep mapping to PEP 440 used in the spike; assertion untested against real releases.)
- [x] `pip install "papyrus-newsroom[markus]"` in a clean venv builds a static Markus reader (12 Pilobol.us pages; no checkout, no `PAPYRUS_ROOT`). Python 3.12 caveat on Amplify (1.3).

CMS app and backend
- [x] Scratch publication repo has `papyrus.config.ts`, Next shell, and `amplify/backend.ts` using `defineSiteBackend`; `next build` passes. Brand renders without a Papyrus edit.
- [ ] Amplify builds the CMS app from the repo via the GitHub App and `ampx pipeline-deploy` creates the backend. **Not testable without the Amplify GitHub App handshake** (Ryan). Locally simulated and passing: `npm ci`, `ampx generate outputs`, `npm run build` from a clean copy.
- [x] A Python Lambda is bundled by `pip install papyrus-newsroom==<same version>` and invokes (HTTP 200) in a sandbox backend (`ampx sandbox`, not pipeline-deploy). Not done: console-responder container image, SES/Slack/backup features.
- [~] `/newsroom` renders with the brand (HTML only; with `newsroomBasePath: ""` it redirects to `/`). No browser sign-in flow tested.

Staging
- [ ] A `staging` branch builds frontend-only against the production backend's outputs. **Not testable without the GitHub App/Amplify** (branch deployment against another branch's backend); the frontend-only pattern passes locally.
- [x] Guest reads `PublishedItem` through `ContentRepository` and cannot see a draft (404). [ ] Draft visible on staging via the Pretext path and `papyrus ops content export --drafts` (neither exists yet).
- [x] Authorization enforced by AppSync (12/12 checks): editor reads draft `Item`; guest and signed-in non-editor get Unauthorized; staging route redirects anonymous, 403s non-editors, shows the draft with a STAGING banner to editors.
- [ ] noindex, `Disallow: /` and banner guards (`SITE_ENV`) and Markus drafts export: not tested.

CI and updates
- [ ] A GitHub Actions job assumes an AWS role through GitHub OIDC and performs/denies actions as specified.
- [ ] Renovate opens one grouped PR bumping the two Papyrus packages. (Add `npm ci --dry-run` to CI, 1.4.)

Result
- [x] `infra/` app deploys via `@anthusai/papyrus/infra`: synth only (app-shell template: Amplify App/Branch/Domain, 2 roles), nothing deployed; without the CDK the import fails with the clear message and the plain app install pulls no CDK packages (`npm ls aws-cdk-lib constructs` empty).
- [x] Written result on PPY-82be6c and in the body of PR #100: pass/fail per item, option A for both app and backend.
