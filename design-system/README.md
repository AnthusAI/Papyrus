# Papyrus

The shared design language for Papyrus publications — the reader surfaces
(newspaper, blog, magazine) and the newsroom console behind them. One set of
semantic tokens, one set of primitives, re-skinned per site instead of
re-built per site.

Papyrus already runs two sites from this foundation: **Papyrus** itself (slate
ramp, Playfair display) and **Threat Intelligence** (sand ramp, tomato alarm).
Both map the *same* semantic names to different ramps. That mapping is the
whole theming contract — see **Brands and forks**.

## Principles

**The solver owns geometry; the system owns appearance.** Page grids, column
widths, line positions, cut points and furniture rectangles are decided in
`lib/newspaper-layout.ts` before anything renders. Tokens may change how a
line *looks*; they must never change how many lines fit. Nothing in this
system reads the DOM, clamps lines in CSS, or balances columns in the browser.

**Three registers, one vocabulary.** *Paper* is reader-facing: square corners,
rules instead of shadows, serif copy, uppercase furniture. *Chrome* is the
console: rounded corners, borders, sans copy, hover and focus states. *Feed* is
the newsroom card surface: no borders at all, tone steps instead, its own
smaller radius scale — see **The feed register**. A component states which
register it belongs to, and never mixes them in one element.

**Emphasis is ink weight, not colour.** There is no brand hue. Hierarchy comes
from `ink-strong` / `ink` / `ink-muted`, from display size, and from rules.
`danger` is the one hue of the reader and chrome registers, and it only ever
means a destructive or alarm state. The feed register adds one hue pair for
machine-versus-human verdicts (`verdict-match`, `verdict-miss`), never used for
emphasis and never the only signal — see **The feed register**.

**Name the step, don't nudge the value.** A bigger headline is
`headlineScale: "feature"`, not a font-size override. A quieter label is
`ink-muted`, not an opacity tweak. Requests that arrive as "make it bigger"
get translated into a token name before anything is edited.

## Content fundamentals

Furniture copy is editorial, and it is terse, uppercase and consistent:

| Slot | Pattern | Example |
| --- | --- | --- |
| Section label | one or two words, uppercase | `ANALYSIS` |
| Byline | `BY` + name, uppercase | `BY A STAFF WRITER` |
| Jump line | `SEE <SLUG> ON <PAGE>` | `SEE READING ON A3` |
| Continuation heading | `<SLUG> FROM <PAGE>` | `READING FROM A1` |
| Meta row | values separated by `·` | `ANALYSIS · 4 MIN` |

An item with no short slug reads `SEE MORE ON A2` and `FROM A1`. Labels are
never sentence case, never end in punctuation, and never wrap to a third line.

Console copy is the opposite register: sentence case, verbs first on buttons
("Claim assignment", not "Assignment claim"), and no exclamation marks.

## Visual foundations

### Colour

Tokens are semantic, in three bands:

- **Surfaces** — `substrate` (the desk) → `paper` (the sheet) → `surface`
  (a card on the sheet) → `surface-muted` → `surface-accent`.
- **Ink** — `ink-strong` (headlines, primary fill), `ink` (copy),
  `ink-muted` (furniture), `ink-inverse` (on a dark fill).
- **Lines and signal** — `border`, `rule`, `ring`, `ring-strong`, `danger`,
  `danger-text`, `danger-contrast`, `disabled`.

Rules that matter:

- Reader copy is `ink` on `paper`; headlines are `ink-strong`.
- `ink-muted` is furniture only. It measures 3.6:1 on paper in light and
  4.15:1 in dark — enough for a 12px bold tracked label, not enough for a
  sentence.
- Write destructive copy in `danger-text` and fill with `danger`. `danger` as
  small text on paper is 3.68:1 in light and fails.
- `border` and `rule` are decorative (1.3–1.9:1). A control must also be
  readable from its fill, its label or its focus ring — never from its border
  alone.
- Draw focus with `focus-ring` over `ring-strong`. The shipped `ring` token is
  1.82:1 on paper and does not meet the 3:1 a focus indicator needs; it stays
  in the system because the app still uses it, and it is being replaced.

### Typography

Four families, each with one job:

- **display** — Playfair Display. Headlines only, in the five editorial
  scales (`banner`, `feature`, `standard`, `rail`, `brief`). See
  **Editorial scale**.
- **reader** — Georgia. Article and blog copy at 18px/28px, decks in italic,
  captions at 12px/19px. Pretext measures these lines.
- **sans** — Plus Jakarta Sans. Console chrome: titles, body, help text.
- **label** — Arial / Helvetica. All uppercase furniture: sections, kickers,
  bylines, meta. Tracking 0.06–0.09em, weight 700–800, always uppercase.

Playfair Display and Plus Jakarta Sans are loaded by `next/font/google` in
`app/layout.tsx` as `--font-serif` and `--font-sans`; there are no font files
in this system to copy. Georgia and Arial are platform faces.

### Space and rhythm

Spacing steps are the shipped control and page geometry (2 → 48px). Vertical
rhythm is separate and solver-owned: `rhythm-base` 7px, `rhythm-line` 28px
(four rows, one line of reader copy), `rhythm-progress` 19px. Anything placed
in a reader page aligns to the rhythm; console chrome aligns to the spacing
steps.

### Shape and elevation

Paper is square (`radius-none`). Console chrome uses `radius-md` through
`radius-xl`, with `radius-lg` (14px) as the default. The only shadow is
`paper-drop`, which lifts a page or dialog off the substrate; everything else
separates with `border` or `rule`.

### Iconography

Lucide (`lucide-react`), stroked not filled, `stroke-icon` (2) stroke width,
16px beside 14px text and 12–14px inside xs and sm controls. Icons inherit
their text colour and are never the only label on a destructive action.
Reader surfaces use rules and type rather than icons; icons live in chrome.

## States

| State | How it reads |
| --- | --- |
| Hover | one surface step up (`surface-muted` → `surface-accent`); no size change |
| Press | `space-0.5` (1px) downward translate, no shadow change |
| Focus | `focus-ring` (3px) plus a solid `ring-strong` border |
| Selected | `surface-accent` fill with `ink-strong` label |
| Disabled | `opacity-disabled` with pointer events off |
| Invalid | `danger` border plus a 3px `danger` ring at 0.2 alpha |
| Destructive | `danger` at 10% fill, `danger-text` label |

## Consuming this system

Each site defines the semantic tokens as CSS custom properties on `:root`,
then re-declares the ones it re-skins under `[data-papyrus-theme="dark"]` and
`@media (prefers-color-scheme: dark)`. In the Papyrus app those names already
exist in `app/globals.css` (`--background`, `--foreground`,
`--foreground-muted`, `--border`, `--rule`, `--ring`, `--destructive`, …);
this system's names are the canonical ones and map onto them one for one.

What a consuming site provides:

- the two Google faces (or its own display and sans),
- its ramp choice and any extra signal hue (Threat Intelligence adds
  `--ti-*` tokens on top; those are fork tokens, not system tokens),
- the theme attribute wiring (`data-papyrus-theme` = `light` | `dark` |
  `system`),
- content. No component here fetches, and none of them know about GraphQL,
  Amplify or Pretext.
