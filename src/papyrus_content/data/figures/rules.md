# Figure rules

These rules say how a Papyrus publication draws diagrams, charts and editorial illustrations. They name **roles**, never colors or fonts. Every Papyrus site supplies the values in its own *design system* (a `mapping.json` of roles, the site's color and type tokens, its font files and its worked examples); these rules are the same for all of them and name no brand. Sizes are for a 680px canvas unless the design system says otherwise.

The reader is an educated person with no background in the subject, possibly in their 80s, on a phone, in light or dark mode, and possibly colorblind.

## 0. Light and dark are both mandatory

**Every figure ships in a light picture and a dark picture, always.** A figure with only a light picture is unfinished: a reader in dark mode gets a bright slab or nothing. There is no light-only figure and no "dark later".

- Draw once. The source uses color **roles**, never colors, so one `figure.svg` resolves to both themes and the two pictures always share one geometry and one aspect ratio.
- `papyrus figures render` always writes both files, `<slug>.png` (light) and `<slug>.dark.png` (dark), and measures contrast, fit and legibility in each theme. A problem in either theme fails the figure.
- Look at both pictures before asking for approval, not only the light one. A mark that reads in light can vanish in dark.
- Save both into the Story. `stories save-version` warns when a figure is saved with only a light picture, and a site can refuse it.
- A design system that gives a color token no dark value cannot be used to draw: fix the design system, don't draw light-only.

## Which design system

Draw only with the design system of the site you are working on. Read its roles, canvas sizes, fonts and worked examples before you draw. If the site has no design system, say so: either use the neutral unbranded default, naming it as such in your note to the person (`--neutral-default`), or ask. **Never invent a brand**: no made-up colors, fonts or logos for a site that has not given you any.

## 1. Decide whether to draw

Draw only when a figure helps. Write the acceptance criteria first, in `figure.json`:

- `audience`: who it is for.
- `shows`: what it shows and leaves out.
- `complements`: what it adds to the text beside it.
- `surrounding_text`: the text in the article that conveys the same information.

Do not draw if a sentence or a small table would do, or if the text around it can't carry the same information on its own. A figure never fixes confusing text. Rewrite the text first. If you cannot fill in the four fields above, do not draw.

Each figure answers one question. A person confirms each figure before it is published.

Not every Story or Reference needs a diagram. Consider a relevant, rights-cleared photograph, a source image, an editorial illustration or the site's placeholder as well. A photograph used for context must not imply that it depicts a person, place or event it does not show. Record its creator, source and licence.

## 2. Choose a form

| To show | Use | Layout |
| --- | --- | --- |
| Steps in order | Numbered steps | Top to bottom, a numeral beside each step |
| What happened when | Timeline | Top to bottom, one equal row per time unit, empty units left in |
| What stands between things | Layers | Top to bottom, walls as bars across the canvas |
| A change in amount | Line or bar chart | Direct labels, up to three series |
| A place or a moment | Illustration | Flat side view, 16:9 |

Choose a form for the relationship being explained, not the closest available template. For example, compare alternatives side by side or in aligned rows; show parts within a larger whole using nested fills; show overlap, distribution or relative amounts with a suitable chart; or arrange a labeled view around a single subject. Use numbered steps and arrows only when the order or direction matters. Vary forms across neighboring Stories rather than repeating the same sequence layout.

Phones are portrait, so run time and flow **top to bottom**, with labels to the right of the shape they name. Left-to-right chains don't fit labels at this size. Comparisons and other nonsequential forms need not imply a direction or use arrows.

## 3. The shape vocabulary

Shapes and lines have fixed meanings. Don't use them for anything else, and don't add one without changing this table.

| Shape | Means | Primitive |
| --- | --- | --- |
| Rounded tile | A thing, place, step or event | `<rect rx="12">`, `rx="16"` when it holds other tiles |
| Round head on shoulders | A person | `<use href="#person">` |
| Square head on shoulders | A machine or AI agent | `<use href="#machine">` |
| Page with a cut corner | Files or private data | `<use href="#file">` |
| Disc | The outside world, the internet | `<use href="#globe">` |
| Row of identical tiles | Many alike | Repeat the tile |
| Inverted tile | The one thing to look at | See section 5 |
| Bar with a break | A wall and its gap | `<rect height="16">` either side of a break of at least 64px |
| Ring | Look closely here | `<circle fill="none" stroke-width="6">`; it never crosses a letter |
| Numeral | Order of steps | `t-numeral` |
| Stamp | Not a record of fact | Tile in `{hatch}` with `t-stamp` text; in an illustration, `{inset}` |

| Line | Means |
| --- | --- |
| Solid with arrowhead | This leads to that |
| Solid without arrowhead | These are connected; or a time rail or axis |
| Dashed with arrowhead | Unseen, or not yet real. Always say which in a label or the caption |
| Thick solid, no arrowhead | Fixed: a chart series that does not change |

Connectors are straight and run horizontally or vertically. Only chart series may curve or slant. Draw connectors before the shapes they join, and keep labels off them.

## 4. Lines and containers

- **Containers separate by fill.** Never outline a tile, draw a divider, or use a gridline. Layer `{ground}`, then `{inset}`, then tiles.
- **Lines exist only where they carry meaning**: a flow, a time rail, an axis, a wall, a data series, a ring.
- **Minimum weight is 4px** (2px on a phone). Connectors and rails are 6px, chart series 8px, fixed-value series 12px, walls 16px.
- Lines use `{ink}` or `{ink-muted}` at full strength. There's no opacity anywhere.
- Dashes are `stroke-dasharray="22 14"`. A third chart series uses `"1 18"` with `stroke-linecap="round"`.

## 5. The focal mark

The focal mark is an **inverted tile**: `{focal}` fill with `{on-focal}` for everything on it, plus `data-focal="true"`. It works by lightness, so it survives colorblindness and needs no extra hue. Each figure has **at most one**. If two things seem focal, the figure has no point yet, or it's two figures.

In a chart, the focal mark is the label tile of the series the figure is about. In an illustration, it is the single subject in `{focal}`, with `data-focal="true"` on its group.

No other hue is ever added. `{brand}` belongs to the publication's own furniture, so it never appears in a diagram or chart.

## 6. Who made what

| Fill | Mark and text | Use when |
| --- | --- | --- |
| `{machine-fill}` | `{machine-mark}`, `{on-machine}` | The thing was made, found or done by a machine: an agent, a model, an automated post |
| `{human-fill}` | `{human-mark}`, `{on-human}` | The thing was chosen or done by people: a person, a decision, an approval |
| `{inset}` or `{ground}` | `{ink}`, `{ink-muted}` | Neither: places, data, the internet, ideas, walls, axes, dates |

- Neutral is the default. Use a tint only when who acted is part of the point.
- Machine and human tints are nearly the same lightness, so **the tint alone says nothing**. Each tinted tile also carries the `#machine` or `#person` glyph, or a word that says who.
- If people and machines share a figure and the labels don't make clear who acted, add a key.
- Illustrations are exempt: their tints are paint, not provenance (section 11).

## 7. Telling series apart

Never use color to tell things apart. Use these, in this order:

1. **Direct labels** on a tile beside the series. No legend if labels fit.
2. **Line style**: thick solid, then dashed, then dotted.
3. **Pattern** on bars and areas: solid `{ink-muted}`, `url(#hatch-pattern)`, `url(#dots-pattern)`.
4. **Shape** at the end of a line: arrowhead, or a 24px circle or square.

At most three series. A key is a row at the bottom of the canvas with no border; it explains shapes and never adds new information.

## 8. Words and type

Set type only with these classes. Each is a role in the mapping. Sizes scale with canvas width.

| Class | Use | Size | Phone size |
| --- | --- | --- | --- |
| `t-numeral` | Step numbers | 56 | 28 |
| `t-head` | Dates, column heads | 36, uppercase | 18 |
| `t-statement` | Names, one-line steps | 30, heavy | 15 |
| `t-label` | Everything else; the smallest type | 26 | 13 |
| `t-stamp` | Stamps | 26, uppercase, tracked | 13 |

- **Nothing is smaller than 13px on a 343px phone.** There's no exception for ticks, sources or keys. A label that won't fit gets cut or moved, never shrunk.
- A label is about 25 characters, 30 at most. Split longer text over two `<text>` lines, 32px apart.
- Write sentence case, in plain words a lay reader knows. Spell out abbreviations.
- Text sits on one solid fill. Don't let text cross an edge, a line or a pattern.
- A figure carries no title, caption or credit inside it. These go in the `::image{}` line. The exception is a stamp.
- No italics, no serif, no monospace, no vertical text.

## 9. Density

| Limit | Value |
| --- | --- |
| Questions answered | 1 |
| Named things (repeated tiles count once) | 9 |
| Labels | 14 |
| Connectors | 6 |
| Focal marks | 1 |
| Chart series | 3 |
| Bars | 6 |
| Steps | 4 |
| Height of a 680px figure | 1100px, one phone screen |

**Split into two figures** when any limit is passed, when a reader must scroll to see all of it, or when the caption needs "and" to say what it shows. Splitting beats shrinking. Before finishing, try removing each shape, line and label. If the figure still works, leave it out.

## 10. Forecasts and invented scenarios

A forecast or invented scenario must never look like data.

- Set `labelled_as` to one of:
  - `forecast`: carries the stamp `FORECAST, NOT DATA`.
  - `invented`: an invented example that could be mistaken for data (numbers, a map, a chart). Carries the stamp `INVENTED EXAMPLE`.
  - `invented-scene`: carries the stamp `INVENTED SCENE`.
  - `framed`: an invented step-by-step or illustration that sits inside a story already marked as imagined, with no numbers and nothing that reads as a measurement. It carries no stamp. The story's own note title (for example "an imagined scenario") and its plain caption say so. A figure that shows data is never `framed`.
  - `none`: the figure is real or general and is not invented.

  A stamp is put first, at the top-left.
- A forecast chart sits on `url(#hatch-pattern)` and has **no numbers, tick marks, gridlines, units or data points**. Its axes are words, such as "Today" and "Five years out". Whatever is projected is dashed.
- The caption and alt text say the same thing in words.
- Only real measurements get numbers, and they name a source in the credit.

## 11. Illustrations

An illustration is for a place or a moment, not an explanation. It shares its language with the site's placeholder art when it has any: flat shapes, large discs, generous corners.

- **Canvas**: 960×540 (16:9), full bleed, no rounded ground.
- **View**: flat side elevation. No perspective, no ground shadow, no gradient, no texture, no outlines.
- **Shapes**: rectangles with corners of at least 12px, discs and simple curves. People are silhouettes with no faces; use the person glyph's proportions.
- **One large disc** cropped by the canvas edge, when the composition has room for one.
- **Palette**: `{ground}`, `{inset}`, `{machine-fill}`, `{human-fill}`, `{brand}`, and `{focal}` with `{on-focal}` on the subject only. No more than six. Here the fills are paint and say nothing about provenance. Don't put machine or human glyphs in an illustration.
- **Subject**: exactly one in `{focal}`, in the lower third.
- **Words**: only what a real sign would say, in `t-head`, plus the stamp if invented.
- It never depicts a real person, a real place or a real brand. No generated imagery unless an editor asks for it.

## 12. Alt text, credit and caption

- `alt`: what it shows, then why it's there. Say what the reader would get from looking, including which element is focal and any stamp. Don't narrate geometry.
- `caption`: one sentence.
- `credit`: `Drafted by AI. Approved by {approved_by}.`, plus `Source: <name>.` for facts or `Illustrative; no data.` for a forecast. The approved name is filled in when a person confirms.
- `<title>` and `<desc>` in the SVG source hold the short name and one sentence.

## 13. Output

- **Format**: PNG at twice the canvas size, exported from Chromium with the fonts embedded in the page. Text is pixels, so nothing depends on a web font at display time.
- **Two files, both mandatory (section 0)**: `<slug>.png` (light) and `<slug>.dark.png` (dark), from one source, so the shapes and ratio always match.
- Figures are static.
- Outside a figure's rounded ground, corners are transparent.
- Don't use GIF or SVG. An `<img>` SVG can't reach a web font, and mail and feed readers often refuse SVG.

## 14. Before you hand it over

1. The acceptance criteria were written first and the figure meets them.
2. `surrounding_text` holds the same information as the picture.
3. The tool reports `ok` with no problems, in light and in dark. Read its notes.
4. View both pictures, light and dark, at 343px wide. Can you read every word in each? Do they make sense with color removed?
5. One focal mark or none.
6. Forecast, or invented and could pass for data? Stamped. Invented but framed by the story, with no data on it? Labelled `framed`, and the story's note and caption say so.
7. Ask a person to confirm, then fill in `approved_by`.
