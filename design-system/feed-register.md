# The feed register

The newsroom feed — the References feed, the review card, the What-needs-me
cards and their detail panes — is a third register beside paper and chrome, and
it has its own rules. A component that lives there follows them, because the
surface enforces them in CSS whether the component agrees or not.

## What makes it different

**Nothing has a border, an outline or a rule.** Regions are told apart by tone
alone. `[data-feed-flat]` zeroes every border and box-shadow inside itself with
repeated-attribute selectors, so a bordered card dropped into a feed pane
simply loses its border.

**Three tone steps, mixed from the Kanbus theme**, not from the slate ramp:

| Token | Light | Dark |
| --- | --- | --- |
| `--feed-card` | theme paper mixed 35% toward white | theme paper 94% toward ink |
| `--feed-footer` | paper 70% toward white | paper 90% toward ink |
| `--feed-control` | paper 90% toward ink | paper 80% toward ink |

**Its own radius scale**, half the first design: `--feed-radius-xl` 12px (sheets),
`--feed-radius-lg` 10px (cards, detail pane), `--feed-radius-md` 8px (rating
cells, buttons, textareas), `--feed-radius-pill` 8px (chips, filters, toggles —
a rounded rectangle, not a capsule). These are smaller than the chrome radii;
inside a feed surface the chrome values are remapped to them.

**Dark mode comes from `[data-color-mode="dark"]`**, set with
`[data-kanbus-theme]` on the organizer root. It is not Tailwind's `dark:`
variant: that variant is defined as `&:is(.dark *)` and nothing in the app adds
a `.dark` class, so every `dark:` utility in a newsroom component is dead code.
Write dark values as tokens in the feed layer instead.

**The newsroom maps the shared semantic names onto the theme**:
`--foreground`, `--muted-foreground`, `--primary`, `--ring` and the rest are
re-declared from `--kb-theme-*` for the organizer scope. So a component written
against the semantic tokens re-skins correctly here without knowing about
Kanbus — which is the point of the whole system.

## Verdict tones

Machine-versus-human comparisons (see **RatingGrid**) need one agreement colour
and one disagreement colour, which is the only place the system uses a hue pair
rather than ink weight. The `verdict-*` tokens carry it, and the rule is that
**hue is never the only signal**: a verdict cell always also carries an icon
(CircleCheck or CircleX) and the word Match or Miss. Executable specifications
assert both the colour and the word, so the pair is a contract, not a
preference.

Red and green are the least distinguishable pair for colour-blind readers. They
remain here because the specs fix them and because the icon and word carry the
meaning on their own; the light and dark values differ in lightness as well as
hue so the tint is never the only cue.
