# Brands and forks

A Papyrus site is a fork of one application, not a copy of the design. Both
shipped brands use identical semantic token names and identical primitives;
they differ only in which ramp each name resolves to.

## The two shipped brands

| Semantic token | Papyrus | Threat Intelligence |
| --- | --- | --- |
| `paper` | slate-2 | sand-2 |
| `surface` | slate-1 | sand-1 |
| `surface-muted` | slate-3 | sand-3 |
| `ink` | slate-11 | sand-11 |
| `ink-strong` | slate-12 | sand-12 |
| `ink-muted` | slate-10 | sand-10 |
| `border` / `rule` | slate-6 / slate-7 | sand-6 / sand-7 |
| `danger` | tomato-9 | tomato-9, surfaced as the alarm red |

Threat Intelligence keeps the slate ramp for one thing only — pictogram
geometry — and otherwise runs warm. It also adds fork tokens
(`--ti-alarm-red`, `--ti-rhythm: 7px`, `--ti-copy-font-size: 18px`,
`--ti-cta-*`) that belong to that publication, not to this system. A fork may
add tokens; it may not redefine what a system token means.

Dark mode on that brand reverses the role of the alarm red: `tomato-11` in
light (where it must carry text contrast) and `tomato-9` in dark. That is the
pattern for any fork hue — pick the step that holds 4.5:1 in each theme, not
the same step in both.

## Starting a new fork

1. Choose a ramp pair: one neutral for surfaces and ink, one hue for signal.
   Resolve every semantic token to an exact step; do not hand-mix values.
2. Check each ink-on-surface pair in **both** themes. `ink` must clear 4.5:1
   on `paper` and on `surface`. If the neutral ramp's step 11 does not, move
   to step 12 for copy rather than lightening the surface.
3. Declare the tokens on `:root`, then the dark overrides under both
   `@media (prefers-color-scheme: dark)` (guarded so an explicit light choice
   wins) and `[data-papyrus-theme="dark"]`.
4. Register the brand in `lib/site-brand.ts` with its masthead copy, text
   font, default presentation and any forced presentation.
5. Leave the primitives alone. A fork that needs a new component adds it to
   this system, so the other sites get it too.

## Theme contract

`<html>` carries the reader's choice as `data-papyrus-theme` with
`light`, `dark` or `system`, and the reader capability attributes
(`data-site-brand`, `data-default-presentation`, `data-forced-presentation`,
`data-presentation-choices`). Components read none of these directly: they
read tokens, and the tokens change underneath them. A component that branches
on brand is a component in the wrong place.
