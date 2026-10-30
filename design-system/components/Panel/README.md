# Panel

A surface with a register. Panel is how a layout declares whether a block is
reader-facing paper or newsroom chrome, so the two never blur into each other.

- `paper` — square corners, a 2px section rule along the top, serif copy, and
  a display-face title. For anything a reader sees.
- `chrome` (default) — `radius-lg`, a hairline `border`, `surface` ground,
  sans copy. For console panels.
- `quiet` — `surface-muted` with no border, for a nested group or an empty
  state inside a chrome panel.
- `lifted` — `radius-xl` with `paper-drop`. Dialogs and popovers only; one
  lifted surface at a time on screen.

Padding is `tight` (12px), default (16px) or `loose` (24px). Inside a `paper`
panel the horizontal padding is zero by design: reader copy aligns to the
column, not to a card inset.

Rules:

- Do not nest a `chrome` panel inside a `paper` panel. If a reader surface
  needs an interactive block, put the block on paper and give it a rule, not a
  card.
- Separate sections inside a panel with `Rule`, not with a shadow or a second
  border.
- A panel never scrolls itself; the page or a scroll area owns scrolling.
- Content height is the consumer's. Panel sets no min-height, because on
  reader pages the solver has already decided the geometry.
