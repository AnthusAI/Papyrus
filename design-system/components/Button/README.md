# Button

The one action primitive for console chrome; reader pages use links and rules,
not buttons.

One `default` button per view — the action the view exists for. Everything
else is `secondary`, `outline` or `ghost`. `destructive` is for an action that
removes or cancels something a person cannot get back; it fills at 10% of
`danger` and labels in `danger-text`, so it reads as a warning rather than a
second primary.

Sizes come from the `control-*` tokens: `xs` (24px) in dense tables and
toolbars, `sm` (28px) inside panels, `default` (32px) everywhere else, `lg`
(36px) for a page-level action. Radius steps down with size so a small button
does not look like a pill.

Rules:

- Label with a verb in sentence case: "Claim assignment", not "Assignment".
- An icon never stands alone on a destructive action; keep the word.
- Focus draws `focus-ring` over a solid `ring-strong` border. Do not remove
  it, and do not replace it with a colour change.
- Press is a 1px translate (`space-0.5`). No shadow, no scale.
- Disabled uses `opacity-disabled` with pointer events off; a disabled button
  needs a tooltip or help text saying what would enable it.

The consumer provides the label, the handler and the disabled state. The
component does no loading state of its own — render the label you want while a
request is in flight.
