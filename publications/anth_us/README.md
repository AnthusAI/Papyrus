# Anthus publication (Papyrus)

Site definition for **Anth.us** on Papyrus: brand, theme pack, corpus wiring,
deployment metadata. The Papyrus framework imports from this directory; it does
not embed Anthus branding in generic framework modules.

## This is the *site*, not the editorial identity

Two sibling directories, two different jobs — do not merge them:

| Path | What it is |
| --- | --- |
| `publications/anthus/` | **Editorial identity**: `style-profile.yml`, `editorial-rewrite-skill.yml`, `reference-samples/`. Pre-existing. Untouched by this port. |
| `publications/anth_us/` | **Site definition** (this directory): `brand.ts`, `theme.css`. |

## Status: staging port, not a cutover

The reader deployment is a **staging** port of a live marketing site.
Production `anth.us` stays pointed at the existing Gatsby site
(`AnthusAI/Anth.us`) until the port has been reviewed.

Accordingly, `readerDeployment` on `anthUsBrand` records only the repository.
`domain` and `amplifyAppId` are deliberately unset, and **no DNS, domain
association, or custom-domain configuration exists anywhere in this repo for
Anthus**. Staging runs on the hostname Amplify hands out.

| Surface | Repo | Platform | Domain |
| --- | --- | --- | --- |
| **Reader** (Markus static HTML) | [AnthusAI/Anth.us-Papyrus](https://github.com/AnthusAI/Anth.us-Papyrus) | `WEB` | none yet (Amplify staging hostname) |
| **CMS / newsroom** (Papyrus Next.js) | [AnthusAI/Papyrus](https://github.com/AnthusAI/Papyrus) | `WEB_COMPUTE` | not provisioned |

The reader repo is private while the port is half-finished, so that link will
404 without access. Expected.

## Layout

| Path | Purpose |
| --- | --- |
| `brand.ts` | `anthUsBrand: SiteBrand` — masthead, theme pack, corpus paths, deployment metadata |
| `index.ts` | Re-export |
| `theme.css` | Anthus Shadcn token overrides (`anth-us` pack) |

Token values and their provenance (including which three are *derived* rather
than copied from the live site) are documented on `ANTH_US_THEME_PACK_TOKENS`
in `lib/site-stack.ts`.

## Brand values and where they came from

Everything in `brand.ts` is read off the live Gatsby site, not invented:

| Field | Source |
| --- | --- |
| `appTitle`, `appDescription` | `gatsby-config.mjs` `siteMetadata.title` / `.description` |
| `mastheadTitle` | `src/components/header.js` renders the bare word `Anthus` (Jersey 25, weight 900) — not a dotted-domain wordmark |
| `mastheadSubtitle` | `gatsby-plugin-manifest` `name: "Anth.us AI Solutions"`, and the primary nav item |
| `articleTitleSuffix` | `src/components/seo.js`: `` `${title} | ${defaultTitle}` `` |
| `placeholderByline` | `siteMetadata.author` |
| `textFont` | `src/styles/variables.scss` `--font-sans` (Montserrat stack) |
| `themeTokens` | `src/styles/variables.scss` `:root` |

Two things in the source site's typography are **not** carried into the theme
pack, by the pack's own rules (colors only; Shadcn owns type):

- **Jersey 25** — the display face used for the masthead and `h1`/`h2`. It is
  a Google Font loaded by `gatsby-plugin-google-fonts`. The reader stylesheet
  in the reader repo is the right place for it.
- **Geist Mono** — the code face.

## No dark mode

The source site has no dark mode; its only `prefers-color-scheme: dark` rule
swaps two code-highlight tints. `theme.css` therefore pins
`color-scheme: light` and `ANTH_US_THEME_PACK_TOKENS` has no `dark` palette.
Inventing one would be designing, not porting. If Anthus designs a dark
scheme, add it to both places together.

Related: the live site's footer is a separate package (`anthus-footer`) that
renders dark purple (`#27213a` / `#f7f4ff`) via inline styles regardless of
scheme. A theme pack has no footer slot, so that is a reader-stylesheet
concern.

## Reader build

The reader renders through Papyrus's Markus renderer with both content
capabilities enabled — the Anthus corpus needs them (234 `BlogImage`, 201
`Citation`, 25 `CitationsList` uses):

```python
build_markus_site(
    content_dir=pod / "content",
    out_dir=pod / "dist",
    images=ImagePipeline(emit_layout_class_verbatim=True),
    citations=CitationRendering(),
)
```

`emit_layout_class_verbatim=True` keeps the ported stylesheet's `.full`,
`.centered`, `.right` selectors working. The authoring syntax those
capabilities accept is specified in
[docs/markus-content-markup.md](../../docs/markus-content-markup.md).

## Not wired yet

Declared in `brand.ts` but **not present in the repo**, so newsroom workflows
for this brand will not run until someone creates them:

- `corpora/anth-us-steering.yml`
- `corpora/anth-us-newsroom-sections.yml`
- `corpora/anth-us-analysis-profiles.yml`

Copy the `corpora/pilobol-us-*.yml` set as a starting point.

## Environment (CMS app)

```bash
export PAPYRUS_SITE_BRAND=anth-us
export NEXT_PUBLIC_PAPYRUS_SITE_BRAND=anth-us
```

Brand aliases accepted by `normalizeSiteBrandId`: `anth-us`, `anth.us`,
`anth_us`. Note that the bare alias **`anthus` resolves to
`threat-intelligence`** and was left that way so existing deployments do not
silently change brand. Do not "tidy" that.
