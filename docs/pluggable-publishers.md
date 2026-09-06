# Pluggable publication front ends (Pretext + Markus)

Status: **Design** (with a minimal interface/config spike in `lib/publisher.ts`).
Kanbus: PPY-93a9c0 (initiative) → PPY-92f846 (epic) → PPY-4db888 (this task).
Branch: `cursor/feature/PPY-4db888-pluggable-publishers-markus-8e6b` → PR into `develop`.

## 1. Goal and non-goals

**Goal.** Let a Papyrus pod publish the same standard content through *either* of two
swappable front ends:

1. **Pretext** — the existing client-side newspaper/blog/magazine solver
   (`@chenglou/pretext` + `components/newspaper.tsx` + `components/presentation-shell.tsx`).
2. **Markus** — Anthus-flavored Markdown → static HTML, themed with Markus CSS,
   with per-site CSS layers on top (the path Pilobil.us needs first).

The first consumer is **Pilobil.us**, a local Papyrus pod that is KB-ready but
cannot publish today because Papyrus only ships the Pretext publication type.

**Non-goals.**

- Do **not** rip out Pretext. It stays as one publisher plugin.
- Do **not** invent a second content model that only Markus understands. Both
  publishers consume the same standard `EditionContent` / `PublicationItem` shape.
- Do **not** ship Pilobil.us live in this design. This is the design + a stub.
- Do **not** replace the Amplify/GraphQL CMS. Markus is a *render* path; the
  content source of truth stays where it is (GraphQL, or a local pod content
  directory for static-only pods).

## 2. How the Pretext path actually works today (verified)

Grounded in the current `develop` checkout, not assumption.

### 2.1 Site brand is a compile-time TS registry, not config

`lib/site-brand.ts` defines a closed `SiteBrandId` union and a `SITE_BRANDS`
record resolved once at module load from `NEXT_PUBLIC_PAPYRUS_SITE_BRAND` /
`PAPYRUS_SITE_BRAND`:

```4:79:lib/site-brand.ts
export type SiteBrandId = "papyrus" | "threat-intelligence";
const SITE_BRANDS: Record<SiteBrandId, SiteBrand> = {
  papyrus: { /* ... */ defaultPresentation: "newspaper", /* ... */ },
  "threat-intelligence": threatIntelligenceBrand,
};
export const SITE_BRAND = SITE_BRANDS[resolveSiteBrandId()];
```

`publications/threat_intelligence/brand.ts` exports `threatIntelligenceBrand`
and is imported directly by `lib/site-brand.ts`. A publication package is
therefore **brand + theme.css + seed JSON + optional React components**, registered
by hand in the `SITE_BRANDS` map. There is no plugin loader; adding a brand
means editing `lib/site-brand.ts`.

`papyrus-config.example.yaml` / `.papyrus/config.yaml` is **backend-only**
(steering paths, public site URL, OpenAI). It does **not** drive the reader or
the site brand. `PAPYRUS_DEFAULT_PRESENTATION` does not exist; default
presentation lives on `SITE_BRAND.defaultPresentation`.

### 2.2 Presentation format is a closed enum, branched in one component

`lib/content-types.ts`:

```7:7:lib/content-types.ts
export type EditionPresentationFormat = "newspaper" | "blog" | "magazine";
```

`components/presentation-shell.tsx` is the single renderer router. It hardcodes
three branches and imports TI components unconditionally:

```79:108:components/presentation-shell.tsx
  if (activePresentation === "newspaper") {
    return ( /* <Newspaper ... /> */ );
  }
  return ( /* <BlogPresentation /> | <MagazinePresentation /> */ );
```

```20:20:components/presentation-shell.tsx
import { BlogPageBackground } from "../publications/threat_intelligence/blog-defense/page-background";
```

There is **no publisher plugin interface, no renderer registry, no site-type
strategy enum**. The nearest existing seam is `EditionContent.presentationPlans`
(`lib/content-types.ts:52`), which is **declared but unused** anywhere in the
codebase — a ready-made hook for per-publisher plans.

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
(`amplify/data/resource.ts:1854`). `presentationPlans` / `defaultPresentation`
are **not** separate GraphQL fields — only `layoutPlan` and `metadata` JSON
exist, so per-publisher plans would ride inside `layoutPlan` or `metadata`
without a schema change.

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
Markus publisher is a **Python build step** (Markdown → HTML fragments) plus
**vendored CSS** plus a thin Next.js render shell that mounts the fragments and
layers site CSS on top. It does **not** need Pretext, the client solver, or
`EditionLayoutPlan` geometry.

## 4. Proposed publisher plugin interface

Introduce a **publisher** axis orthogonal to the existing **presentation** axis.

- *Presentation* (`newspaper` | `blog` | `magazine`) stays a Pretext-internal
  concern. It is only meaningful when the publisher is `pretext`.
- *Publisher* (`pretext` | `markus`) decides **which render pipeline** runs and
  **where geometry is owned** (client solver vs. build-time static HTML).

### 4.1 The `Publisher` descriptor (spiked in `lib/publisher.ts`)

```ts
export type PublisherId = "pretext" | "markus";
export type PublisherRuntime = "client-solver" | "static-html";
export type Publisher = {
  id: PublisherId;
  runtime: PublisherRuntime;
  label: string;
  /** True when this publisher needs the Pretext client solver + EditionLayoutPlan. */
  requiresPretext: boolean;
  /** True when this publisher emits static HTML at build time. */
  staticOutput: boolean;
};
export const PUBLISHERS: Record<PublisherId, Publisher> = { /* ... */ };
export function resolvePublisher(id: PublisherId | string | undefined): Publisher;
```

This is a **metadata-only registry** in the spike — it describes the two
publishers but is **not yet wired** into `PresentationShell` or any route. The
design below specifies where wiring lands.

### 4.2 Where the publisher is configured

Add `publisher?: PublisherId` to `SiteBrand` (default `"pretext"`), resolved
exactly like `defaultPresentation`:

- `lib/site-brand.ts` gains `publisher` on `SiteBrand` and a
  `resolvePublisher(SITE_BRAND.publisher)` accessor.
- A publication package (e.g. `publications/pilobil/brand.ts`) sets
  `publisher: "markus"`.
- The build reads it the same way it reads `SITE_BRAND.id` today (compile-time
  TS record + env-selected brand). No new config file format required.

For **local pods** that are static-only and do not run Amplify, the same
`PAPYRUS_SITE_BRAND` env selects a brand whose `publisher` is `"markus"`. The
content source for such a pod is a **pod content directory** (see §5), not
GraphQL.

### 4.3 Where the publisher is consumed (the wiring plan, not in this PR)

`components/presentation-shell.tsx` becomes a **publisher dispatch**:

```ts
const publisher = resolvePublisher(SITE_BRAND.publisher);
if (publisher.runtime === "client-solver") {
  // existing Pretext path: newspaper | blog | magazine branches
} else {
  // static path: render pre-built Markus HTML fragments + layered CSS
}
```

The static branch is **out of scope for this PR** — it is the "what to build
next" itemized in §8. The spike only lands the descriptor + config enum so the
shape is concrete and reviewable.

## 5. Standard pod content structure (one model, two publishers)

Both publishers read the same `EditionContent` / `PublicationItem` shape. The
only difference is **where the bytes come from** and **how they are rendered**.

For a **local static pod** (Pilobil), introduce a `PodContentRepository`
implementing the existing `ContentRepository` interface
(`lib/content-types.ts:92`) that reads a pod directory instead of GraphQL:

```
publications/pilobil/                 # one publication package
  brand.ts                            # SiteBrand with publisher: "markus"
  theme.css                           # site CSS layer (overrides --markus-*)
  content/
    editions/
      2026-09-06.json                 # EditionContent (items + layoutPlan + metadata)
    articles/
      <slug>.md                       # Markus Markdown body for an article item
    assets/
      <asset-id>.(png|jpg|mp4)        # local media; static pod serves these directly
    markus/                           # vendored Markus CSS (markus.css + themes/*.css)
  build/                              # gitignored build output (HTML fragments)
```

Rules:

- `content/editions/<date>.json` is **the same `EditionContent` shape** the
  GraphQL repository returns (`PublicationItem[]` + `EditionLayoutPlan` +
  metadata). For Markus, `layoutPlan` may be a minimal plan (one page, one
  region, one `articleFrame` per item) because Markus does not consume solver
  geometry — but it is still a valid `EditionLayoutPlan` so the same Zod
  validation and the same authoring tools apply.
- `content/articles/<slug>.md` holds the **Markus Markdown body** for an
  article item. The `PublicationItem` for that slug references it by slug; the
  Markus publisher reads the `.md`, runs `markus convert --fragment --no-css`,
  and mounts the resulting `<article class="markus-document">` fragment.
- `content/assets/` is served as-is by the static pod (no signed URLs). The
  `MediaAsset.storagePath` for a pod item points here; the Markus publisher
  rewrites it to the final public path before emitting HTML.
- `markus/` is **vendored** from the installed `markusmd` package
  (`markusmd/static/`) at install time, not hotlinked from the demo GitHub
  Pages URL (that is not a versioned CDN).
- `theme.css` is the **site CSS layer**: it redefines `--markus-*` tokens and
  adds Pilobil-specific rules. Because Markus uses no `@layer`, the site layer
  wins by either redefining tokens on `:root` / `.markus-document` or by
  wrapping vendored Markus CSS in `@layer markus { … }` and leaving the site
  layer unlayered.

This keeps **one content model**. A Markus pod is not a parallel schema; it is
the same `EditionContent` with a different `ContentRepository` and a different
publisher.

## 6. Markus static pipeline

```
                +---------------------------------------------------+
   pod content  | publications/pilobil/content/{editions,articles,assets} |
                +---------------------------------------------------+
                                        |
                                        v
              +--------------------------------------------+
              | PodContentRepository (ContentRepository)     |
              |   reads editions/<date>.json + articles/*.md |
              |   -> EditionContent (PublicationItem[]+plan)  |
              +--------------------------------------------+
                                        |
                                        v
              +--------------------------------------------+
              | MarkusPublisher.build(edition)  (Python)     |
              |   for each article item:                      |
              |     markus convert articles/<slug>.md        |
              |       --fragment --no-css --theme <name>      |
              |       -> build/fragments/<slug>.html          |
              |   resolve asset storagePath -> /assets/...   |
              |   emit build/manifest.json (slug -> fragment)  |
              +--------------------------------------------+
                                        |
                                        v
              +--------------------------------------------+
              | Next.js render shell (publisher=markus)       |
              |   loads build/fragments/<slug>.html           |
              |   mounts <article class="markus-document">     |
              |   loads vendored markus.css + themes/<name>.css |
              |   loads publications/pilobil/theme.css (site) |
              +--------------------------------------------+
                                        |
                                        v
                static HTML site (Pilobil.us)
```

Key points:

1. **Build-time Python step** (`poetry run papyrus publishers markus build
   --edition <date>` or similar) produces HTML fragments per article. This is
   the only place Markus is invoked. It fits the Python-first rule and keeps
   Markus out of the Next.js bundle.
2. **No Pretext, no client solver** on the Markus path. `buildNewspaperLayout`
   and `layoutAllTextLines` are not imported by the Markus render shell.
3. **CSS layering** (cascade order, lowest to highest):
   1. vendored `markus.css` (base `--markus-*` tokens + element styles)
   2. vendored `themes/<name>.css` (theme token overrides)
   3. `publications/pilobil/theme.css` (site layer — Pilobil brand tokens,
      masthead, footer, per-section accents)
4. **Static deploy**: the Markus path produces a site that can be served as
   pure static files (fragments + CSS + assets + index). It does **not** need
   the Amplify SSR `.next` pipeline. A pod can deploy via GitHub Pages, S3 +
   CloudFront, or any static host. (Next.js is still used as the render shell
   during dev/preview, but the *output* of the Markus build is static HTML.)

## 7. Migration / coexistence; how Pilobil opts in

Coexistence is the default posture: Pretext and Markus share the content model
and differ only at the publisher seam. Nothing about the existing `papyrus` or
`threat-intelligence` brands changes.

### 7.1 Phased rollout

**Phase 0 — this PR (design + stub).** Land `lib/publisher.ts` descriptor +
`PublisherId` enum + this doc. No runtime behavior changes. Pretext path
untouched.

**Phase 1 — wire the dispatch + decouple TI imports.** Add `publisher` to
`SiteBrand`; make `PresentationShell` a publisher dispatch (Pretext branch
unchanged, Markus branch returns a placeholder). Make the
`publications/threat_intelligence/*` imports in
`components/presentation-shell.tsx` and `components/article-page.tsx`
brand-conditional so a second publication can load without TI. Add
`PodContentRepository` (reads `publications/<pod>/content/`).

**Phase 2 — Markus build step.** Add `poetry run papyrus publishers markus
build` (Python) that runs `markus convert` per article, vendors Markus CSS,
and emits `build/manifest.json`. Add the Markus render shell (mounts fragments,
loads layered CSS). Add a `publications/pilobil/` skeleton (brand.ts with
`publisher: "markus"`, theme.css, empty content/).

**Phase 3 — Pilobil content + static deploy.** Author Pilobil edition JSON +
article Markdown, run the Markus build, deploy static output. This is where
Pilobil.us actually goes live — out of scope for this design.

### 7.2 How Pilobil opts in (concrete)

1. Create `publications/pilobil/brand.ts` exporting a `SiteBrand` with
   `id: "pilobil"`, `publisher: "markus"`, `defaultPresentation: "newspaper"`
   (presentation is ignored on the Markus path but the field is required).
2. Register it in `lib/site-brand.ts` `SITE_BRANDS` and in
   `normalizeSiteBrandId`.
3. Add `PAPYRUS_SITE_BRAND=pilobil` to the pod's `.env` (local) or deploy env.
4. Add `publications/pilobil/content/editions/<date>.json` +
   `content/articles/<slug>.md` + `content/assets/`.
5. Run `poetry run papyrus publishers markus build --edition <date>` to emit
   `publications/pilobil/build/`.
6. Run/preview with `npm run dev` (Markus render shell mounts fragments); deploy
   the static `build/` output to the chosen static host.

No GraphQL, no Amplify, no signed URLs, no Pretext — by construction.

### 7.3 What stays shared

- `lib/articles.ts`, `lib/publication-items.ts`, `lib/content-types.ts`,
  `lib/layout-plan.ts` (Zod validation), `lib/edition-routes.ts`,
  `lib/edition-sections.ts` — all shared. A Markus pod reuses the same item
  types, the same plan schema (minimal plan), the same route helpers.
- The CLI authoring lane (`poetry run papyrus`) is shared; a future
  `publishers markus` command group joins the existing `content` / `editions`
  groups.
- BDD capabilities (`features/support/capabilities.js`) extend naturally: add a
  `data-publisher` attribute on `<html>` alongside `data-site-brand` so
  Markus-only scenarios can skip and Pretext-only scenarios can skip.

## 8. What to build next (for Ryan)

Ordered, smallest dependency first:

1. **Wire the publisher dispatch.** Add `publisher` to `SiteBrand` +
  `resolvePublisher`; branch `PresentationShell` on `publisher.runtime`. Keep
  the Pretext branch byte-identical. Markus branch returns a "Markus publisher
  not yet implemented" placeholder component. (TS only, no Python.)
2. **Decouple `publications/threat_intelligence/*` imports** in
  `components/presentation-shell.tsx` (`BlogPageBackground`,
  `PictogramFigure`) and `components/article-page.tsx` (`PictogramFigure`).
  Make them brand-conditional or move into the TI publication package's own
  component surface, so a non-TI brand loads cleanly. Verify
  `npm run lint && npm run typecheck && npm run build` and the canonical BDD
  suite still pass.
3. **Add `PodContentRepository`** implementing `ContentRepository`
  (`lib/content-types.ts:92`) reading `publications/<pod>/content/`. Wire it
  into `lib/content-repository.ts` behind a content-source switch (e.g.
  `PAPYRUS_CONTENT_SOURCE=pod` + `PAPYRUS_PUBLICATION=pilobil`). This is the
  cleanest place to honor the existing `PAPYRUS_CONTENT_SOURCE` env that
  `amplify.yml` already greps.
4. **Vendor Markus CSS.** Add a `scripts/vendor-markus-css.mjs` (or Python) that
  copies `markusmd/static/markus.css` + `themes/*.css` into
  `publications/<pod>/markus/` from the installed `markusmd` package. Confirm
  `anthus-markus` installs (try `pip install anthus-markus`; fall back to
  `pip install git+https://github.com/AnthusAI/Markus.git`).
5. **Markus build command.** Add `poetry run papyrus publishers markus build
  --edition <date>` in `src/papyrus_content/` that iterates article items, runs
  `markus convert --fragment --no-css --theme <name>`, rewrites asset paths,
  and writes `build/fragments/<slug>.html` + `build/manifest.json`.
6. **Markus render shell.** A `components/markus-presentation.tsx` that reads
  the manifest, mounts fragments via `dangerouslySetInnerHTML` (fragments are
  build-time, trusted, and validated by `markus validate`), and loads the
  three CSS layers. Wire it as the Markus branch of `PresentationShell`.
7. **Pilobil skeleton.** `publications/pilobil/{brand.ts,theme.css,content/}`
  with one stub edition + one stub article, to prove the path end to end.
8. **Static export target.** Decide whether Markus output is (a) a separate
  static folder built by the Python step and deployed directly, or (b) a
  Next.js `output: 'export'` profile for the Markus brand. (a) is simpler and
  keeps Next.js out of the static deploy; (b) reuses Next routing. Recommend
  (a) for the first Pilobil cut.

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
- **`layoutPlan` for Markus.** Is a minimal one-page plan acceptable, or should
  Markus introduce its own plan preset (e.g. `page.markus`) in
  `lib/layout-plan.ts`? Minimal plan is simpler; a named preset is more
  legible. Recommend a named `page.markus` preset added to `PAGE_PRESETS`.
- **Theme switching.** Does Pilobil need runtime theme switching (the demo's
  `localStorage['markus-theme']` switcher), or one baked theme per pod?
  Recommend one baked theme per pod for v1.
- **Raw HTML in Markdown.** Markus disables raw HTML by default. If Pilobil
  needs embedded HTML, decide whether to pass `--allow-html` (sanitizer
  implications) or stay in the directive vocabulary. Recommend staying in the
  vocabulary.
- **Static deploy shape.** Confirm (a) Python-built static folder vs (b)
  Next.js `output: 'export'`. See §8 item 8.
- **BDD brand gating.** Should `data-publisher` be added to `<html>` in
  `app/layout.tsx` and to `features/support/capabilities.js` so scenarios can
  gate by publisher? Recommend yes, in Phase 1.
- **`presentationPlans` field.** The existing unused
  `EditionContent.presentationPlans` (`lib/content-types.ts:52`) is a natural
  home for per-publisher plan blobs. Decide whether to repurpose it for
  Markus-specific plan data or leave Markus on `layoutPlan` only.

## 10. Out of scope

- Shipping Pilobil.us live (Phase 3).
- Replacing Pretext.
- A second content model.
- A runtime plugin loader / dynamic publisher registration. Publishers are a
  compile-time TS registry, mirroring `SITE_BRANDS`. Dynamic loading is not
  needed for two known publishers.
- Markus `site` command reuse (it is demo-specific).
- A Markus npm package (Markus is Python; no JS surface to consume).

