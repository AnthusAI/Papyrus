# Editorial scale

Headline size is an editorial decision recorded in the edition layout plan,
not a CSS value and not a consequence of block order. The plan names a scale;
the solver sizes it against the block it has to fill.

| Scale | Means | Solver size (multi-column) | One column |
| --- | --- | --- | --- |
| `banner` | the single front-page lead | `clamp(w × 0.105, 54px, 112px)` | `clamp(w × 0.13, 42px, 82px)` |
| `feature` | a second front-page story, or a page lead | `clamp(w × 0.052, 34px, 58px)` | `clamp(w × 0.11, 34px, 54px)` |
| `standard` | the default inside-page headline | `clamp(w × 0.07, 27px, 40px)` | `clamp(w × 0.095, 29px, 46px)` |
| `rail` | a narrow sidebar column | `clamp(w × 0.15, 24px, 34px)` | `clamp(w × 0.09, 27px, 42px)` |
| `brief` | briefs, corrections, promos | `clamp(w × 0.055, 18px, 26px)` | `clamp(w × 0.075, 22px, 32px)` |

`banner` and `feature` are display treatments; the rest are text treatments.
The type styles in this system record the ceiling of each range, so a static
specimen and a solved page agree on proportion.

Editorial priority is a separate axis: `primary`, `secondary`, `tertiary`,
`supporting`. It decides reading order in a one-column layout — the primary
story comes first even when a wide layout centres or offsets it — and it does
not change size.

## Furniture vocabulary

Use these words with people and with other agents; they map to real slots:

- **masthead** — the publication nameplate band.
- **kicker** — the small uppercase line above a headline.
- **deck** — the italic standfirst under a headline.
- **byline / dateline** — uppercase attribution, in `ink-muted`.
- **jump line** — `SEE READING ON A3`, on the teaser.
- **continuation heading** — `READING FROM A1`, on the target page.
- **rule** — a horizontal line: `stroke-hairline` for columns and decks,
  `stroke-rule` for section breaks.
- **media inset** — an image that sits inside a column and wraps copy.
- **pull quote** — optional furniture; the solver drops it rather than let it
  collide.
- **local grid** — the block-level grid an article frame composes on.

## What this system does not decide

Column count, page height, cut points, obstacle rectangles, continuation
cursors and furniture selection are all solved before render. If a visual
change alters available copy space, it is a solver contract change first and a
token change second.
