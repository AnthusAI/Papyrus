# Rhythm blog layout and brand slots

A publication opts into the rhythm blog layout and supplies its look from its own repo
(`papyrus.config.ts` and `publication/theme.css`). No Papyrus component is forked or overridden.

## Rhythm blog layout

Set `blogLayout: "rhythm"` on the brand. Default is `"classic"`; classic output is unchanged.

What it renders (blog presentation, edition page and article page):

- `PresentationHeader`: optional eyebrow (`mastheadEyebrow`, first word emphasized), masthead title,
  date, optional tagline (`mastheadTaglineLines`, falling back to `mastheadTagline`), section links.
- A `.presentation-section-header__band` per section and a `PresentationRhythmHRule` between items.
- Featured images floated on the grid by `lib/blog-feature-solver.ts`; every height and gap is a whole
  number of rhythm rows (`lib/blog-rhythm.ts`, default row 16px, copy 18px on a 32px line).
- Article pages with the same header and a solver-owned `article-float-grid`.
- The rhythm overlay on Ctrl+= (`use-rhythm-overlay.ts`), also on the archive page.

The shell sets `--blog-rhythm`, `--blog-row-height`, `--blog-paint-buffer` and `--blog-paint-height` inline.
`app/blog-rhythm.css` holds structure only (every rule is scoped to `.blog-rhythm-shell`). Typography,
colors and header look belong to the publication's `publication/theme.css`, which loads after it.
Optional tokens: `--blog-hrule-foreground`, `--blog-section-rule`, `--blog-section-band-height`,
`--blog-page-padding-x`.

## Brand slots

| `SiteBrand` field | Purpose |
| --- | --- |
| `blogLayout?: "classic" \| "rhythm"` | Selects the layout above. |
| `mastheadEyebrow?: string` | Rhythm layout: line above the title. |
| `mastheadTaglineLines?: { emphasis: string; tail: string }[]` | Rhythm layout: structured tagline. |
| `components.BlogPageBackground` | Header artwork. Now also receives `headerObstacles` (measured header text boxes, in the layer's coordinates) and `rhythm`, so art can keep clear of the text and align to the grid. Obstacle geometry stays in the brand. |
| `components.PictogramFigure` | Existing slot. Rhythm layout also passes `frameWidth` and `frameHeight` (solved image frame). |
| `fonts?: SiteBrandFont[]` | Brand font slot, below. |

## Font slot

```ts
fonts: [
  { family: "Inter", cssVariable: "--font-masthead", fallback: "sans-serif",
    google: { weights: [400, 600, 700, 900] } },
  { family: "Acme Serif", cssVariable: "--font-body", fallback: "Georgia, serif",
    faces: [{ src: "/fonts/acme-serif.woff2", weight: 400 }] },
],
textFont: '"Inter", sans-serif',
```

Each font declares exactly one source: `google` (loaded from the Google Fonts stylesheet API, one
`<link>` for all families, with `preconnect`) or `faces` (self-hosted files, emitted as `@font-face` with
`font-display: swap`). The root layout (`app/layout.tsx`) puts `--font-masthead: "Inter", sans-serif` on
`<html>`, so theme CSS writes `font-family: var(--font-masthead)`. Brands without `fonts` add nothing to
the document. Rendering is the single `resolveBrandFontAssets` function in `lib/brand-fonts.ts`; it
validates the declaration (one source, unique `--custom-property`, at least one weight).

Pretext measures text on a canvas, so set `textFont` to a real family name (not a `var()`). The rhythm
layout re-measures once the declared families finish loading (`use-brand-fonts-ready.ts`).

## Using it from a publication repo

1. `publication/brand.ts` exports the `SiteBrand` (slots, fonts, `blogLayout: "rhythm"`); art components
   import generic pieces from `@anthusai/papyrus/lib/...` and `@anthusai/papyrus/components/...`.
2. `papyrus.config.ts` registers it: `defineSite({ brands: [brand], defaultBrand: brand.id })`.
3. `publication/theme.css` carries the look (found by `withPapyrus()` as `papyrus-site-theme`).

## Tests

- `npm run test:brand-fonts`: font assets and validation.
- `npm run test:rhythm-blog-layout`: server-rendered rhythm markup, no brand names.
- `npm run test:brand-render-snapshots`: edition (blog and magazine), article and item markup for
  `papyrus`, `pilobol-us`, `anth-us` and `threat-intelligence` match snapshots recorded from `develop`
  before this layout existed (`npm run test:brand-render-snapshots -- --update` rewrites them; a diff
  there means an existing brand changed).
- Browser scenarios: `features/blog-rhythm.feature` (tagged `@rhythm-layout`, skipped unless the site
  brand uses the rhythm layout). Run with `PAPYRUS_SITE_BRAND=<brand> npm run dev` and `npm run test:bdd`.
  CI does not run the browser suite today.
