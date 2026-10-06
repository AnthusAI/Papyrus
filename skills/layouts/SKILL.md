# Layout Authoring Skill

Use this skill when editing Papyrus edition layouts, adding pages for content,
or explaining how a page should be composed with the current layout-plan
language.

The audience is a coding agent working on publication content. Most layout work
should be done by editing an edition's cloud `layoutPlan` in GraphQL. Only
change TypeScript when the existing layout vocabulary cannot describe the
intended page.

Papyrus layouts are solved layouts, not browser-flow layouts. The edition plan
stores editorial intent. The TypeScript solver turns that intent into concrete
page columns, block boxes, media rectangles, pull-quote obstacles, Pretext text
lines, exact cursors, and page heights. React only renders the solved result.

Use the canonical Papyrus newspaper vocabulary in user-facing notes, status
updates, and implementation summaries. If a user says "make the headline
bigger," translate that into a concrete scale such as `feature headline` or
`banner headline`. If a user says "put the image on the right," describe the
implementation as a `media inset` placed on the block's `local grid`. Repeating
these terms keeps content editing conversations precise and makes follow-up
requests easier for the next agent to implement.

## Files To Read First

- GraphQL `Edition.layoutPlan`: the editable edition plan.
- `docs/layout-system.md`: the current design-system rules for vertical rhythm,
  mastheads, responsive recipes, composition, continuations, furniture,
  captions, footer, and archive behavior.
- `lib/layout-plan.ts`: the Zod contract for valid layout JSON. Use this when
  the JSON shape is unclear.
- `lib/publication-items.ts`: the normalized item model used by layout blocks.

Read `lib/newspaper-layout.ts` only when changing how layouts are solved.
Read `components/newspaper.tsx` only when solved output needs different
rendering.

Do not put test fixtures in production content records; BDD edge cases belong
in `lib/layout-scenarios.ts`.

## CLI Setup And Use

Use the content CLI to inspect and sync the cloud GraphQL edition. Do not edit
cloud content blind.

Local CLI configuration belongs in `.env`. That file is gitignored by
`.gitignore`; do not commit it. Keep `.env.example` as the committed template.

Required `.env` values for authoring:

```bash
PAPYRUS_GRAPHQL_ENDPOINT=https://...
PAPYRUS_EDITION_SLUG=current
```

Authenticate with `AWS_PROFILE` set to a profile for the site's authoring role.

The endpoint can come from `amplify_outputs.json` when that file exists, or
from the AppSync API in AWS. Requests are signed with SigV4 from your AWS
credentials; it is not a Cognito login session. If credentials are missing or
expired (`aws sso login`), the CLI cannot inspect or sync cloud content.

Basic CLI checks:

```bash
poetry run papyrus ops content inspect
poetry run papyrus ops content list articles
poetry run papyrus ops content diff edition current
```

Sync only after reviewing the diff:

```bash
poetry run papyrus ops content sync edition current
```

Use the CLI workflow this way:

1. Run `poetry run papyrus ops content diff edition current`.
2. Confirm the diff changes only the intended records.
3. Run `poetry run papyrus ops content sync edition current`.
4. Verify the deployed site or GraphQL-backed local app.

If the task is only to inspect the live layout, do not sync. Query or diff
first.

## What You Are Authoring

You are not authoring CSS boxes. You are authoring a newspaper plan:

- which pages exist;
- which items appear on each page;
- which articles start or continue;
- which page a teaser jumps to;
- which regions share the page;
- which blocks use wide or narrow local column grids;
- which images, pull quotes, promos, ads, or rails are required or optional.

The solver owns the actual rectangles, line breaks, chosen image sizes, omitted
optional furniture, and page height.

## Mental Model

The layout hierarchy is:

```text
Edition.layoutPlan
  pages[]
    regions[]
      blocks[]
        local grid
        optional media / pull quote furniture
        optional article-frame composition slots
        Pretext text flow
```

Use this model when authoring:

- A page chooses a broad preset and responsive page grid.
- A region allocates an area of that page.
- A block places one content item or a small furniture cluster inside a region.
- `articleFrame` blocks may consume or resume article text with exact cursors.
- Media and pull quotes are solver-owned furniture. If they affect copy space,
  they must be in the layout plan before Pretext runs.

## Current Design Invariants

Read `docs/layout-system.md` for the full contract. The critical authoring rules
are:

- Everything that affects measured copy must be solver-owned before Pretext
  runs.
- The shared vertical rhythm is `19px` normally and `18px` on narrow layouts.
- Front-page nameplates are five rhythm rows; the normal front masthead adds a
  one-row metadata strip for six rows total.
- Archive uses a five-row `ARCHIVE` nameplate only; `Previous editions` is not a
  visible masthead row.
- Front-page `responsiveLayouts` should be keyed by solver column count, not by
  device names.
- `editorialPriority` controls collapsed reading order; it is separate from
  `role` and `typography.headlineScale`.
- Captions, pull quotes, and image packages reserve complete rhythm rows and
  leave one blank rhythm row before following copy.
- Height policy is explicit: use `region.size.shrinkToContent`,
  `articleFrame.size.defaultRows`, and `articleFrame.size.shrinkToContent` only
  when the default fill behavior is wrong.

## Page Setup Checklist

For every new page:

1. Pick a `pageNumber`.
2. Pick a page `presetId`.
3. Set the page grid, usually `{ "columns": { "min": 1, "preferred": 6, "max": 6 } }`.
4. Add one or more `regions`.
5. Add blocks inside each region.
6. Reference content by stable `itemId` slug.
7. For article continuations, use the same `flowKey` as the teaser and set
   `startCursor: "current"`.
8. For front-page teasers that should continue, add
   `cutPolicy.jumpTargetPage`.
9. Add media/pull quotes as optional unless the page cannot work without them.
10. Run validation/build checks before committing.

Minimal page:

```json
{
  "id": "page-4",
  "pageNumber": 4,
  "presetId": "page.regionStack",
  "grid": { "columns": { "min": 1, "preferred": 6, "max": 6 } },
  "regions": [
    {
      "id": "page-4-main",
      "type": "fullPage",
      "blocks": [
        {
          "id": "some-article-page-4",
          "type": "articleFrame",
          "presetId": "article.standard",
          "itemId": "some-article",
          "flowKey": "some-article",
          "startCursor": "beginning"
        }
      ]
    }
  ]
}
```

## Current Layout Vocabulary

Page presets:

- `front.mosaic`: front page with teaser blocks and planned cutpoints.
- `page.regionStack`: vertical stack of one or more editorial regions.
- `page.railMain`: rail plus main content page.
- `page.full`: one full-page region.

Region types:

- `fullPage`: one region using the page body.
- `stack`: one band in a top/bottom page.
- `split`: a side-by-side region pattern.
- `railMain`: a rail/main structure.
- `strip`: a short horizontal strip region.

Block types:

- `articleFrame`: article-like text flow, including teasers and continuations.
- `itemFrame`: non-article item card/frame.
- `mediaCluster`: triptych or mosaic media cluster for one item.
- `itemStack`: corrections, briefs, masthead-style rail items.
- `promoStrip`: horizontal strip of linked items.
- `adBlock`: image ad or region ad placeholder.
- `rule`: simple separator.
- `masthead`: masthead/chrome block.

Article frame presets:

- `front.teaser`: front-page excerpt with optional planned jump and optional
  slot composition for newspaper-style title/copy/media arrangements.
- `article.standard`: headline/deck plus text columns, no required furniture.
- `article.mediaInset`: article text flowing around media/pull-quote obstacles.
- `article.mediaPrelude`: media cluster before headline/copy.

Headline scales:

- `banner`: largest publication/page display headline.
- `feature`: dominant story in a region, such as a four-column front feature.
- `standard`: normal article or continuation headline.
- `rail`: narrow side-column front-page story.
- `brief`: small teaser, promo, or compact item headline.

Use these names in conversation, code review, and layout notes. Say `feature
headline` instead of "big headline," `rail headline` instead of "side headline,"
and `brief headline` instead of "small headline."

Use `typography.headlineScale` to name the headline treatment explicitly:

```json
{
  "type": "articleFrame",
  "presetId": "front.teaser",
  "role": "feature",
  "typography": { "headlineScale": "feature" }
}
```

`role` describes the block's editorial job in the layout. `headlineScale`
describes the headline typography. Keep both when they matter. A center story
can be a `feature` role with a `feature` headline; side stories can be `rail`
roles with `rail` headlines; dense strips should use `brief` headlines.

Editorial priorities:

- `primary`: the lead story in a sequential or collapsed layout.
- `secondary`: important supporting stories, often rails beside the primary.
- `tertiary`: normal supporting articles.
- `supporting`: low-priority promos, briefs, or furniture-like content.

Use `editorialPriority` when wide-screen placement and mobile reading order
need to differ. A center feature can be visually centered on desktop and still
be the `primary story` that appears first in one-column front-page layouts.

```json
{
  "type": "articleFrame",
  "presetId": "front.teaser",
  "role": "feature",
  "editorialPriority": "primary",
  "typography": { "headlineScale": "feature" }
}
```

Media cluster presets:

- `media.triptych`: up to three images above or beside editorial content.
- `media.mosaic`: dominant image plus supporting images under one caption.

Ad presets:

- `ad.fullPage`
- `ad.region`

## Responsive Grids

The solver supports page column counts `6, 5, 4, 3, 2, 1`. It chooses the
largest count that preserves readable column width and forces one column on
mobile.

Use span policies everywhere a width should adapt:

```json
{ "min": 1, "preferred": 4, "max": 4 }
```

Rules of thumb:

- Use `preferred: 6` for broad article bodies that should use the whole page.
- Use `preferred: 4` for a strong center feature inside a six-column page.
- Use `preferred: 1` for rails, narrow teasers, and side notes.
- Keep `min` realistic. If `min: 4`, the block cannot preserve that shape on
  tablet/mobile and may become invalid or collapse poorly.
- For mobile-friendly features, use `min: 1` and a `collapse` policy on media.

## Media Placement

Media placement is responsive intent, not solved geometry:

```json
{
  "required": true,
  "assetRole": "lead",
  "placement": {
    "anchor": "right",
    "span": { "min": 1, "preferred": 2, "max": 2 },
    "vertical": "top",
    "collapse": "inline",
    "crop": "preserve",
    "wrapsText": true
  }
}
```

Anchors:

- `left`: start at the left edge of the local grid.
- `right`: end at the right edge of the local grid.
- `center`: center inside the local grid.
- `outer` / `inner`: reserved for alternating page-side semantics.
- `inline`: collapse into the text flow on narrow layouts.

Use `columnStart` when editorial intent needs an exact local-grid target. It is
1-based because editors talk about “column 1” and “columns 3-4”, not zero-based
arrays.

```json
{
  "columnStart": 3,
  "span": { "min": 1, "preferred": 2, "max": 2 },
  "vertical": "top",
  "collapse": "inline",
  "crop": "preserve",
  "wrapsText": true
}
```

Only use `columnStart` when the exact columns matter. Use `anchor: "right"` for
the common “rightmost N columns” case.

Vertical placement:

- `top`
- `upperThird`
- `middle`
- `lowerThird`

Collapse policy:

- `inline`: use an inline/mobile-friendly placement.
- `fullWidth`: span all available columns when the preferred span cannot fit.
- `omit`: drop optional furniture when it cannot fit.

Crop policy:

- `preserve`: prefer the asset aspect ratio.
- `cropAllowed`: allow the solver/renderer to crop for a stronger editorial
  rectangle.

Use `required: true` only when the page design cannot work without media.
Optional media should be allowed to disappear if it collides, creates dead
columns, or makes copy fit worse.

Important front-page rule: if a `front.teaser` needs an image beside copy or a
deck/byline limited to only some columns, use `articleFrame.composition`. A bare
`media` array on a front teaser is only for the simple prelude-style image path
and should not be used for precise editorial column layouts.

## Pull Quotes

Pull quotes are display furniture. They do not consume the article cursor.

```json
{
  "required": false,
  "placements": [
    {
      "anchor": "right",
      "span": { "min": 1, "preferred": 1, "max": 2 },
      "vertical": "middle",
      "collapse": "omit",
      "crop": "preserve",
      "wrapsText": true
    }
  ]
}
```

Prefer optional pull quotes. A clean page without a pull quote is better than a
crowded page with overlapping furniture.

## Article Frame Slot Composition

Use `articleFrame.composition` when a story needs newspaper-style control over
which chrome spans which columns. This is the right tool for front features like:

- label/headline spanning the full feature width;
- deck and byline only over the copy columns;
- image in the rightmost two of four local columns;
- body copy flowing around deck, byline, image, or pull quote obstacles;
- responsive collapse rules for three-, two-, and one-column layouts.

Example: four-column feature, full-width headline, copy on the left two columns,
image on the right two columns:

```json
{
  "id": "front-agent-procedure-patterns",
  "type": "articleFrame",
  "presetId": "front.teaser",
  "role": "feature",
  "typography": { "headlineScale": "feature" },
  "itemId": "agent-procedure-patterns",
  "flowKey": "agent-procedure-patterns",
  "startCursor": "beginning",
  "span": { "min": 1, "preferred": 4, "max": 4 },
  "localGrid": { "columns": { "min": 1, "preferred": 4, "max": 4 } },
  "composition": {
    "title": [
      {
        "slot": "label",
        "placement": {
          "columnStart": 1,
          "span": { "min": 1, "preferred": 4, "max": 4 },
          "vertical": "top",
          "collapse": "inline",
          "crop": "preserve",
          "wrapsText": false
        }
      },
      {
        "slot": "headline",
        "placement": {
          "columnStart": 1,
          "span": { "min": 1, "preferred": 4, "max": 4 },
          "vertical": "top",
          "collapse": "inline",
          "crop": "preserve",
          "wrapsText": false
        }
      }
    ],
    "lead": [
      {
        "slot": "deck",
        "placement": {
          "columnStart": 1,
          "span": { "min": 1, "preferred": 2, "max": 2 },
          "vertical": "top",
          "collapse": "inline",
          "crop": "preserve",
          "wrapsText": true
        }
      },
      {
        "slot": "byline",
        "placement": {
          "columnStart": 1,
          "span": { "min": 1, "preferred": 2, "max": 2 },
          "vertical": "top",
          "collapse": "inline",
          "crop": "preserve",
          "wrapsText": true
        }
      },
      {
        "slot": "media",
        "mediaIndex": 0,
        "placement": {
          "anchor": "right",
          "span": { "min": 1, "preferred": 2, "max": 2 },
          "vertical": "top",
          "collapse": "inline",
          "crop": "preserve",
          "wrapsText": true
        }
      }
    ]
  },
  "media": [
    {
      "required": true,
      "assetRole": "lead",
      "placement": {
        "anchor": "right",
        "span": { "min": 1, "preferred": 2, "max": 2 },
        "vertical": "top",
        "collapse": "inline",
        "crop": "preserve",
        "wrapsText": true
      }
    }
  ]
}
```

Slot rules:

- `title` slots reserve vertical chrome above the body field.
- `lead` slots sit inside the body field and become Pretext obstacles.
- `deck`, `byline`, `media`, and `pullQuote` in `lead` do not consume article
  text. They only reserve solved display space.
- Use `crop: "preserve"` when aspect ratio matters.
- On mobile, spans collapse through the normal placement `collapse` policy, so
  this four-column pattern becomes a one-column stack without needing a second
  mobile-only layout.

## Article Flow And Continuations

Use `flowKey` to connect excerpts and continuations for the same article.

Front-page teaser:

```json
{
  "id": "front-agent-procedure-patterns",
  "type": "articleFrame",
  "presetId": "front.teaser",
  "itemId": "agent-procedure-patterns",
  "flowKey": "agent-procedure-patterns",
  "startCursor": "beginning",
  "span": { "min": 1, "preferred": 4, "max": 4 },
  "cutPolicy": { "maxBodyLines": 22, "jumpTargetPage": 2 }
}
```

Continuation:

```json
{
  "id": "agent-procedure-patterns-page-2",
  "type": "articleFrame",
  "presetId": "article.mediaInset",
  "itemId": "agent-procedure-patterns",
  "flowKey": "agent-procedure-patterns",
  "startCursor": "current",
  "localGrid": {
    "columns": { "min": 2, "preferred": 6, "max": 6 }
  }
}
```

Rules:

- The first block for an article normally uses `startCursor: "beginning"`.
- Continuation blocks use `startCursor: "current"`.
- Keep `flowKey` stable across all blocks that should share cursor handoff.
- Put `jumpTargetPage` on the teaser block, not on the continuation block.
- Never store solved cursors, line positions, page heights, or selected media
  rectangles in JSON.

## Common Patterns

### Front Page: Left Rail, Composed Center Feature, Right Rail

Use three top-row `articleFrame` blocks whose spans add to six. Put explicit
roles and headline scales on the rails and feature. For media-led center
features, use `composition`, not a bare full-width front media prelude.

```json
[
  {
    "id": "front-left-rail",
    "type": "articleFrame",
    "presetId": "front.teaser",
    "role": "rail",
    "typography": { "headlineScale": "rail" },
    "itemId": "schools-reading-lab",
    "flowKey": "schools-reading-lab",
    "startCursor": "beginning",
    "span": { "min": 1, "preferred": 1, "max": 1 }
  },
  {
    "id": "front-center-feature",
    "type": "articleFrame",
    "presetId": "front.teaser",
    "itemId": "agent-procedure-patterns",
    "flowKey": "agent-procedure-patterns",
    "startCursor": "beginning",
    "role": "feature",
    "typography": { "headlineScale": "feature" },
    "span": { "min": 1, "preferred": 4, "max": 4 },
    "localGrid": { "columns": { "min": 1, "preferred": 4, "max": 4 } },
    "composition": {
      "title": [
        {
          "slot": "label",
          "placement": {
            "columnStart": 1,
            "span": { "min": 1, "preferred": 4, "max": 4 },
            "vertical": "top",
            "collapse": "inline",
            "crop": "preserve",
            "wrapsText": false
          }
        },
        {
          "slot": "headline",
          "placement": {
            "columnStart": 1,
            "span": { "min": 1, "preferred": 4, "max": 4 },
            "vertical": "top",
            "collapse": "inline",
            "crop": "preserve",
            "wrapsText": false
          }
        }
      ],
      "lead": [
        {
          "slot": "deck",
          "placement": {
            "columnStart": 1,
            "span": { "min": 1, "preferred": 2, "max": 2 },
            "vertical": "top",
            "collapse": "inline",
            "crop": "preserve",
            "wrapsText": true
          }
        },
        {
          "slot": "byline",
          "placement": {
            "columnStart": 1,
            "span": { "min": 1, "preferred": 2, "max": 2 },
            "vertical": "top",
            "collapse": "inline",
            "crop": "preserve",
            "wrapsText": true
          }
        },
        {
          "slot": "media",
          "mediaIndex": 0,
          "placement": {
            "anchor": "right",
            "span": { "min": 1, "preferred": 2, "max": 2 },
            "vertical": "top",
            "collapse": "inline",
            "crop": "preserve",
            "wrapsText": true
          }
        }
      ]
    },
    "media": [
      {
        "required": true,
        "assetRole": "lead",
        "placement": {
          "anchor": "right",
          "span": { "min": 1, "preferred": 2, "max": 2 },
          "vertical": "top",
          "collapse": "inline",
          "crop": "preserve",
          "wrapsText": true
        }
      }
    ],
    "cutPolicy": { "maxBodyLines": 22, "jumpTargetPage": 2 }
  },
  {
    "id": "front-right-rail",
    "type": "articleFrame",
    "presetId": "front.teaser",
    "role": "rail",
    "typography": { "headlineScale": "rail" },
    "itemId": "market-hall",
    "flowKey": "market-hall",
    "startCursor": "beginning",
    "span": { "min": 1, "preferred": 1, "max": 1 }
  }
]
```

### Front-Page Headline Scale

Front-page headline scale must be controlled by canonical editorial tokens, not
by accidental array position or raw CSS size.

In a rail / feature / rail layout, the two one-column rails should use matching
`rail` headlines. The four-column center feature should use a `feature`
headline and visually outrank the rails. A common bug is making the first block
in the array a left rail and then letting the solver treat index `0` as the lead
story. That makes the left rail headline larger than the right rail headline
even though both are one-column side stories.

When authoring front-page blocks, set explicit `role` and
`typography.headlineScale`. For media-led center features, combine
`role: "feature"`, `typography.headlineScale: "feature"`, and the
`composition` pattern above.

```json
[
  {
    "id": "front-left-rail",
    "type": "articleFrame",
    "presetId": "front.teaser",
    "role": "rail",
    "typography": { "headlineScale": "rail" },
    "itemId": "schools-reading-lab",
    "flowKey": "schools-reading-lab",
    "startCursor": "beginning",
    "span": { "min": 1, "preferred": 1, "max": 1 }
  },
  {
    "id": "front-center-feature",
    "type": "articleFrame",
    "presetId": "front.teaser",
    "role": "feature",
    "typography": { "headlineScale": "feature" },
    "itemId": "agent-procedure-patterns",
    "flowKey": "agent-procedure-patterns",
    "startCursor": "beginning",
    "span": { "min": 1, "preferred": 4, "max": 4 },
    "localGrid": { "columns": { "min": 1, "preferred": 4, "max": 4 } }
  },
  {
    "id": "front-right-rail",
    "type": "articleFrame",
    "presetId": "front.teaser",
    "role": "rail",
    "typography": { "headlineScale": "rail" },
    "itemId": "market-hall",
    "flowKey": "market-hall",
    "startCursor": "beginning",
    "span": { "min": 1, "preferred": 1, "max": 1 }
  }
]
```

If `typography.headlineScale` is not currently honored by the solver, fix the
solver before trying to work around this in content. The expected rule is:

- `headlineScale: "banner"` gets a `banner headline`.
- `headlineScale: "feature"` gets a `feature headline`.
- `headlineScale: "standard"` gets a `standard headline`.
- `headlineScale: "rail"` gets a `rail headline`.
- `headlineScale: "brief"` gets a `brief headline`.
- One-column side stories in the same row should usually use matching `rail`
  headlines.
- Do not infer lead typography from `index === 0`.

For the current GraphQL edition, inspect the live `Edition.layoutPlan` before
changing it. Use `poetry run papyrus ops content diff edition current` before
syncing.

### Shared Continuation Page

Use `page.regionStack` with two `stack` regions:

```json
{
  "id": "page-3",
  "pageNumber": 3,
  "presetId": "page.regionStack",
  "grid": { "columns": { "min": 1, "preferred": 6, "max": 6 } },
  "regions": [
    {
      "id": "top-tail",
      "type": "stack",
      "role": "top",
      "size": { "ratio": 0.5 },
      "blocks": [
        {
          "id": "schools-reading-lab-page-3",
          "type": "articleFrame",
          "presetId": "article.mediaInset",
          "itemId": "schools-reading-lab",
          "flowKey": "schools-reading-lab",
          "startCursor": "current",
          "localGrid": { "columns": { "min": 4, "preferred": 6, "max": 6 } }
        }
      ]
    },
    {
      "id": "bottom-tail",
      "type": "stack",
      "role": "bottom",
      "size": { "ratio": 0.5 },
      "blocks": [
        {
          "id": "market-hall-page-3",
          "type": "articleFrame",
          "presetId": "article.mediaInset",
          "itemId": "market-hall",
          "flowKey": "market-hall",
          "startCursor": "current"
        }
      ]
    }
  ]
}
```

### Four-Column Article Inside A Six-Column Page

Set the page grid to six, but the article block local grid to four:

```json
"grid": { "columns": { "min": 1, "preferred": 6, "max": 6 } }
```

```json
"localGrid": { "columns": { "min": 2, "preferred": 4, "max": 4 } }
```

Use this for an article that should feel narrower than the full broadsheet
width while still living inside a six-column page system.

## Authoring Workflow

1. Identify the publication items by slug.
2. Decide page preset, region structure, and block order.
3. Assign spans that make sense at six columns first.
4. Add local grids when a block should have a different column system than the
   page.
5. Add media and pull-quote specs only when they are part of the editorial
   design.
6. Add `requires` for hard content constraints such as item type, minimum words,
   maximum words, minimum images, or image role.
7. Validate with `npm run typecheck`.
8. Run `npm run build`.
9. If changing behavior, add or update BDD scenarios and run `npm run test:bdd`
   against a running app.

## Hard Rules

- Do not add DOM measurement loops or CSS line clamps to solve newspaper copy.
- Do not make React choose layout variants.
- Do not store solved geometry in `layoutPlan`.
- Do not silently ignore missing required articles or media.
- Do not make every block required. Optional furniture is how the solver avoids
  crowded or awkward pages.
- Do not use fixed pixel layout in JSON. Use spans, anchors, region ratios,
  presets, and semantic requirements.
- Preserve exact cursor handoff: no duplicated or skipped article text.

## When To Change TypeScript

Change `Edition.layoutPlan` in GraphQL when the existing vocabulary can
describe the page.

Change `lib/layout-plan.ts` and `lib/newspaper-layout.ts` when you need a new
reusable layout concept, such as a new page preset, region type, block type,
media cluster preset, scoring rule, or obstacle behavior.

When adding a new JSON field:

- Add it to the Zod schema in `lib/layout-plan.ts`.
- Normalize/validate it before the solver sees it.
- Use it in the solver, not in React effects.
- Add BDD coverage when it changes visible layout behavior.
