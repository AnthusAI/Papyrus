# Pluggable publication front ends (Pretext + Markus)

Status: **Partially implemented** on `feature/renderer-architecture`. Renderer
contract + config union landed in PPY-d79ff2 / PPY-eca592; Markus static build
in PPY-88f77b (#60). This doc mixes historical design notes with the current
shape — when they disagree, trust `lib/renderer-config.ts` and
`lib/site-brand.ts`.
Kanbus: PPY-93a9c0 (initiative) → PPY-92f846 (epic).

## 1. Goal and non-goals

**Goal.** Let a Papyrus pod publish the same standard content through *either* of two
swappable front ends:

1. **Pretext** — the existing client-side newspaper/blog/magazine solver
   (`@chenglou/pretext` + `components/newspaper.tsx` + `components/presentation-shell.tsx`).
2. **Markus** — Anthus-flavored Markdown → static HTML, themed with Markus CSS,
   with per-site CSS layers on top (the path Pilobil.us needs first).

The first consumer is **Pilobol.us** (`pilobol.us`, brand id `pilobol-us`), a
local Papyrus pod that is KB-ready but cannot publish through the Pretext
Next.js reader path.

**Non-goals.**

- Do **not** rip out Pretext. It stays as one renderer (`kind: "pretext"`).
- Do **not** invent a second content model that only Markus understands. Both
  renderers consume the same standard `EditionContent` / `PublicationItem` shape
  where applicable; Markus static builds read committed Markdown under
  `web/content/` and do not require a fake `EditionLayoutPlan`.
- Do **not** ship Pilobol.us live in this design. Static build path exists;
  production deploy is a separate issue.
- Do **not** replace the Amplify/GraphQL CMS. Markus is a *render* path; the
  content source of truth stays where it is (GraphQL, or a local pod content
  directory for static-only pods).

## 2. How the Pretext path actually works today (verified)

Grounded in `feature/renderer-architecture` after PPY-eca592, not the pre-union
`develop` shape.

### 2.1 Site brand is a compile-time TS registry with `rendererConfig`

`lib/site-brand.ts` defines a closed `SiteBrandId` union and a `SITE_BRANDS`
record resolved once at module load from `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` /
`PAPYRUS_SITE_BRAND`:

```ts
export type SiteBrandId = "papyrus" | "threat-intelligence" | "pilobol-us";

type RendererConfig =
  | { kind: "pretext"; layout: "newsprint" | "blog" | "magazine"; layoutPlan: EditionLayoutPlan }
  | { kind: "markus"; theme: string };

// Sibling type only — not a required SiteBrand field (PPY-eca592)
type HostingConfig = { kind: "amplify-ssr" } | { kind: "amplify-static" };

const SITE_BRANDS: Record<SiteBrandId, SiteBrand> = {
  papyrus: {
    rendererConfig: { kind: "pretext", layout: "newsprint", layoutPlan: /* empty-edition placeholder */ },
    /* ... */
  },
  "threat-intelligence": {
    rendererConfig: { kind: "pretext", layout: "blog", layoutPlan: /* ... */ },
    /* ... */
  },
  "pilobol-us": {
    rendererConfig: { kind: "markus", theme: "hackerman" },
    /* ... */
  },
};
```

`publications/*/brand.ts` exports per-publication `SiteBrand` records imported
by `lib/site-brand.ts`. There is no plugin loader; adding a brand means editing
the `SITE_BRANDS` map.

`papyrus-config.example.yaml` / `.papyrus/config.yaml` is **backend-only**
(steering paths, public site URL, OpenAI). It does **not** drive the reader or
site brand. Reader layout choice is derived from `SITE_BRAND.rendererConfig`
(pretext branch only). Persisted reader-settings still use the `presentation`
storage key (PPY-61dc8f).

### 2.2 Pretext layout vs renderer dispatch

**Renderer** (`pretext` | `markus`) is selected by `SiteBrand.rendererConfig`.
Dispatch lives at the **app-shell seam** (`lib/site-renderer.ts`,
`app/layout.tsx`, `app/*` routes): `getSiteRenderer()` returns the Pretext
renderer or throws for Markus — Markus never enters React and
`renderers/markus/stubs.tsx` is not wired into Next routes.

**Layout** (`newsprint` | `blog` | `magazine`, `PretextLayout` in
`lib/renderer-config.ts`) is Pretext-internal. `renderers/pretext/presentation-shell.tsx`
switches layouts only; it does not choose the renderer kind.

`EditionContent.presentationPlans` was **deleted** (unused). Per-edition
`EditionContent.layoutPlan` remains the GraphQL Pretext plan; the pretext
`rendererConfig.layoutPlan` on `SiteBrand` is the **empty-edition placeholder**
template (`lib/empty-edition-layout-plan.ts`), not Markus geometry.

### 2.3 Pretext is a client-side dependency

`package.json` pins `"@chenglou/pretext": "^0.0.7"`. The wrapper
`lib/pretext-layout.ts` re-exports `layoutNextLine` / `prepareWithSegments` and
defines the local `TextLine` / `layoutTextLines` / `layoutAllTextLines`.

Pretext runs **in the browser**, after hydration, inside `useMemo` blocks in
`components/newspaper.tsx` (`buildNewspaperLayout`) and
`components/presentation-shell.tsx` (`layoutAllTextLines` for blog/magazine).
There is no server-side or build-time Pretext pass. The solver owns geometry;
React only renders solved objects (`MeasuredLines` at
`components/newspaper.tsx:1536`).

### 2.4 Content boundary is GraphQL-first

`lib/content-repository.ts` routes `?scenario=<id>` to `lib/layout-scenarios.ts`
(test/debug only) and everything else to `graphqlContentRepository`
(`lib/graphql-content-repository.ts`), which loads `Edition` + `EditionItem` +
`MediaAsset` from AppSync, resolves signed media URLs via Amplify Storage
`getUrl`, and normalizes into `EditionContent` (`PublicationItem[]` +
`EditionLayoutPlan`). Reads use `authMode: "identityPool"` (guest IAM).

`Edition.layoutPlan` is `a.json()` on the GraphQL model
(`amplify/data/resource.ts:1854`). Only `layoutPlan` and `metadata` JSON exist
on the edition record — layout is not a separate GraphQL field. Markus static
builds do not consume `Edition.layoutPlan`.

### 2.5 Deploy is SSR, not static export

`amplify.yml` builds `next build` and ships the full `.next` directory
(SSR/ISR). Routes are `force-dynamic` (`/`) or `revalidate=3600` (edition date,
article, archive). There is **no `next export` / static-export target** today.
`PAPYRUS_CONTENT_SOURCE` is referenced only in `amplify.yml` grep; no reader
code consumes it.

### 2.6 What "publication package" means today

`publications/threat_intelligence/` is the only publication package: `brand.ts`
+ `theme.css` + `seed/seed-edition-content.json` + pictograms + blog-defense +
video pipeline. The framework imports from it directly (not brand-conditional),
which is a known coupling this design must loosen for a second publication.

## 3. How Markus is meant to be consumed (verified)

From the AnthusAI/Markus repo (`pyproject.toml`, `cli.py`, `api.py`,
`render.py`, `sitebuild.py`, `themes.py`, `static/markus.css`,
`docs/LANGUAGE.md`, README) and the live demo at
<https://anthusai.github.io/Markus/>:

- **Markus is a Python library + CLI**, not an npm package. `markusmd` Python
  API; `markus` CLI with `convert` / `validate` / `ast` / `preview` / `site`.
- **Flavor:** GFM + a closed registry of colon-fenced semantic directives
  ("Anthus-flavored Markdown"). Strict validation fails loudly on unknown
  directives/attributes — good for CI, means Papyrus must only emit the
  registered vocabulary.
- **CSS theme:** bundled `markus.css` (~27 KB) + 23 `themes/*.css`. Tokens are
  `--markus-*` custom properties (`--markus-ink`, `--markus-paper`,
  `--markus-accent`, `--markus-sans/serif/mono`, …). **No `@layer`** is used
  upstream, so a downstream site can win the cascade by redefining tokens or
  wrapping Markus CSS in `@layer markus { … }`.
- **Static output:** `markus convert article.md -o article.html --fragment
  --no-css --theme <name>` emits a `<article class="markus-document"
  data-theme="…">…</article>` body fragment. `markus site` builds a demo-shaped
  multi-page site (hardcoded nav/titles) — **demo-specific**, not for reuse.
- **No JS runtime** for core rendering; only the demo site chrome (theme
  switcher / copy / source toggle) ships JS. No image/asset pipeline —
  `figure`/`video` take `src` strings, so Papyrus must produce final (signed or
  static) URLs **before** feeding Markus.
- **PyPI:** `anthus-markus` v0.5.0 is declared but **publication UNVERIFIED**
  (PyPI JSON 404 at research time). Plan to install from git until confirmed.

**Implication:** Markus fits Papyrus's Python-first backend rule naturally. A
Markus site is a **Python static build** (`poetry run papyrus renderers markus-build`
→ `web/dist/`) plus vendored Markus CSS plus per-site theme CSS. It does **not**
need Pretext, the client solver, Next.js reader routes, or fake
`EditionLayoutPlan` geometry.

## 4. Renderer config (landed — PPY-eca592)

One field on `SiteBrand` selects the whole site's renderer. Invalid combinations
are unrepresentable via a discriminated union in `lib/renderer-config.ts`:

```ts
export type RendererConfig =
  | { kind: "pretext"; layout: "newsprint" | "blog" | "magazine"; layoutPlan: EditionLayoutPlan }
  | { kind: "markus"; theme: string };

/** Sibling deploy target — type-only; not a required SiteBrand field yet. */
export type HostingConfig =
  | { kind: "amplify-ssr" }
  | { kind: "amplify-static" };
```

Nomenclature (decided on PPY-d79ff2 / PPY-eca592):

- **Renderer** (`pretext` | `markus`) — the swappable system that turns content
  into a site.
- **Layout** (`newsprint` | `blog` | `magazine`) — the look **within** Pretext
  only (`PretextLayout`). Not a concept Markus must understand.
- Do **not** use: `publisher`, `defaultPresentation`, `forcedPresentation`, or
  independent enums whose combinations are invalid (the PR #57 anti-pattern).

### 4.1 The `Renderer` interface (`lib/renderer.ts`)

Real operations retrofitted from existing Pretext call sites (PPY-d79ff2):
`renderEdition`, `renderArticle`, `renderItem`, `stylesheets()`, `supportsLayout()`.
Pretext lives under `renderers/pretext/`. Markus stubs under `renderers/markus/`
satisfy the type but are **not** mounted in Next.js.

### 4.2 Where renderer config is resolved

- `SiteBrand.rendererConfig` on each brand record in `lib/site-brand.ts`.
- Env `PAPYRUS_SITE_BRAND` / `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` selects the brand
  at compile time (same as today).
- Brand mappings: **Papyrus** → pretext / `newsprint`; **Threat Intelligence** →
  pretext / `blog` (locked); **Pilobol.us** (`pilobol-us`) → markus /
  `hackerman`.

### 4.3 Where the renderer is consumed (landed)

**Not** inside `presentation-shell.tsx`. App-shell seam only:

```ts
// lib/site-renderer.ts
export function assertPretextSite(): void;  // throws for kind === "markus"
export function getSiteRenderer(): Renderer; // pretext only; throws for markus
```

- `app/layout.tsx` calls `assertPretextSite()` — Markus brands fail fast in Next.
- Reader `app/*` routes call `getSiteRenderer()` → `pretextRenderer`.
- Markus production path: `poetry run papyrus renderers markus-build` → serve
  `web/dist/` statically. **No Next.js Markus preview.**

## 5. Standard content structure (one model, two renderers)

Both renderers can consume the same `EditionContent` / `PublicationItem` shape
where applicable. Markus static builds read `web/content/` directly.

For a **local static pod** (Pilobol.us), Markus reads committed Markdown under
`web/content/` (see PPY-88f77b). A future `PodContentRepository` may implement
`ContentRepository` for pod-local edition JSON; that is not required for the
static build path today.

```
publications/pilobol_us/              # publication package (brand id: pilobol-us)
  brand.ts                            # SiteBrand with rendererConfig: { kind: "markus", theme: "hackerman" }
  theme.css                           # site CSS layer (overrides --markus-*)
web/
  content/
    articles/
      <slug>.md                       # Markus Markdown sources
  css/
    site-theme.css                    # site theme layer
  dist/                               # gitignored — output of `papyrus renderers markus-build`
```

Rules:

- Pretext editions from GraphQL carry `EditionContent.layoutPlan` per edition.
  Markus static builds **do not** require a fake `EditionLayoutPlan` — they read
  `web/content/articles/*.md` directly.
- `web/content/articles/<slug>.md` holds Markus Markdown; `papyrus renderers
  markus-build` emits static HTML under `web/dist/`.
- Site CSS layers on top of vendored Markus CSS (`web/dist/css/markus-vendor.css`
  + `web/dist/css/site-theme.css`).

## 6. Markus static pipeline (landed — PPY-88f77b)

```
web/content/articles/*.md
        |
        v
poetry run papyrus renderers markus-build --theme <name>
        |
        v
web/dist/          (static HTML + css/markus-vendor.css + css/site-theme.css)
        |
        v
plain static file server (not Next.js)
```

Key points:

1. **Build-time Python step only.** `papyrus renderers markus-build` is the
   Markus entry point. No Next.js route mounts Markus output.
2. **No Pretext, no client solver, no React hydration** on the Markus path.
3. **CSS layering:** vendored Markus CSS → theme CSS → site `site-theme.css`.
4. **Static deploy** is a separate concern (`HostingConfig` type documents
   `amplify-static` vs `amplify-ssr`; wiring is follow-up). Markus output is
   servable as pure static files from `web/dist/`.

## 7. Migration / coexistence; how Pilobol.us opts in

Coexistence is the default posture: Pretext and Markus differ at the
`rendererConfig` seam. Nothing about the existing `papyrus` or
`threat-intelligence` Pretext brands changes.

### 7.1 Phased rollout (updated)

**Done — renderer contract (PPY-d79ff2).** `lib/renderer.ts`, Pretext under
`renderers/pretext/`, TI imports decoupled.

**Done — Markus static build (PPY-88f77b / #60).** `papyrus renderers markus-build`
→ `web/dist/`.

**Done — config union (PPY-eca592).** `SiteBrand.rendererConfig` discriminated
union; `pilobol-us` brand; app-shell dispatch; no Next.js Markus path.

**Next — static hosting.** Wire `HostingConfig` (`amplify-static` for Pilobol.us)
without reintroducing required-but-ignored fields. Separate from renderer config.

**Next — pod content repository.** Optional `PodContentRepository` for local
edition JSON if GraphQL-less pods need it.

### 7.2 How Pilobol.us opts in (concrete)

1. `publications/pilobol_us/brand.ts` is registered in `SITE_BRANDS` as
   `pilobol-us` with `rendererConfig: { kind: "markus", theme: "hackerman" }`.
2. Set `PAPYRUS_SITE_BRAND=pilobol-us` in the pod's deploy env.
3. Author Markdown under `web/content/articles/<slug>.md`.
4. Run `poetry run papyrus renderers markus-build --theme hackerman`.
5. Serve `web/dist/` with a static host. **Do not** run `next dev` / `next build`
   for the Markus site — `assertPretextSite()` rejects Markus brands in Next.

No fake `layoutPlan`, no `defaultPresentation`, no Next.js reader shell.

### 7.3 What stays shared

- `lib/articles.ts`, `lib/publication-items.ts`, `lib/content-types.ts`,
  `lib/layout-plan.ts` (Zod validation), `lib/edition-routes.ts`,
  `lib/edition-sections.ts` — all shared. A Markus pod reuses the same item
  types, the same plan schema (minimal plan), the same route helpers.
- The CLI authoring lane (`poetry run papyrus`) is shared; the Markus static
  build is `papyrus renderers markus-build`.
- BDD capabilities (`features/support/capabilities.js`) expose `data-renderer-kind`
  on `<html>` alongside `data-site-brand` and presentation attributes.

## 8. What to build next (for Ryan)

Ordered, smallest dependency first:

1. **Static hosting for Pilobol.us.** Wire `HostingConfig` (`amplify-static`) in
   CI/deploy without adding a required-but-ignored field on `SiteBrand`. Keep
   Pretext sites on Amplify SSR.
2. **Pod content repository (optional).** `PodContentRepository` for local
   edition JSON if needed; Markus static path already reads `web/content/`.
3. **Pilobol.us content + static deploy.** Author article Markdown, run
   `papyrus renderers markus-build`, deploy `web/dist/`.
4. **BDD gating by renderer.** Extend scenario tags to skip Markus-only or
   Pretext-only cases using `data-renderer-kind`.

## 9. Decisions needed / unknowns

- **Markus install path.** Is `anthus-markus` published to PyPI? If not, is
  installing from `git+https://github.com/AnthusAI/Markus.git` acceptable as the
  canonical path, or should Papyrus vendor Markus source? (Affects
  `pyproject.toml` and the vendor script.)
- **Markdown source of truth.** Does Pilobil author directly in
  `content/articles/<slug>.md` (Markdown-first), or does it author in GraphQL
  `Item` rows and emit Markdown for the Markus build? The design assumes
  Markdown-first for static pods; the GraphQL-first option is viable but adds a
  Markdown emission step. **Decision needed from Ryan/Pilobil.**
- **`layoutPlan` for Markus.** **Decided (PPY-eca592):** Markus does not use
  `EditionLayoutPlan`. Pretext editions keep per-edition `layoutPlan` from
  GraphQL; the pretext `rendererConfig.layoutPlan` on `SiteBrand` is only the
  empty-edition placeholder. Do not invent `page.markus` presets or fake plans.
- **Theme switching.** Does Pilobil need runtime theme switching (the demo's
  `localStorage['markus-theme']` switcher), or one baked theme per pod?
  Recommend one baked theme per pod for v1.
- **Raw HTML in Markdown.** Markus disables raw HTML by default. If Pilobil
  needs embedded HTML, decide whether to pass `--allow-html` (sanitizer
  implications) or stay in the directive vocabulary. Recommend staying in the
  vocabulary.
- **Static deploy shape.** **Decided:** Python-built `web/dist/` served as
  static files (not Next.js `output: 'export'`). `HostingConfig` documents
  `amplify-static` vs `amplify-ssr`; deploy wiring is follow-up.
- **BDD brand gating.** `data-renderer-kind` landed on `<html>` (PPY-eca592).
- **`presentationPlans` field.** **Decided (PPY-eca592):** deleted (unused).
  Renderer-specific config lives on `SiteBrand.rendererConfig`, not edition JSON.

## 10. Out of scope

- Shipping Pilobol.us live (static deploy wiring).
- Replacing Pretext.
- A second content model.
- A Next.js Markus preview or render shell.
- A runtime plugin loader / dynamic renderer registration. Renderers are a
  compile-time TS registry, mirroring `SITE_BRANDS`.
- Markus `site` command reuse (it is demo-specific).
- A Markus npm package (Markus is Python; no JS surface to consume).

