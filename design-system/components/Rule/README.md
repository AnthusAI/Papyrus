# Rule

A horizontal or vertical line in `rule`. Papyrus separates with rules, so this
is the default divider in both registers.

`hairline` (1px) is a column rule, a deck rule or a divider inside a panel.
`section` (2px) is a section break or an appendix divider — the heavier
newspaper rule. `soft` draws either at `opacity-rule-soft` for a deck or an
inset, where a full-strength rule would compete with the copy.

Pass `label` and the rule becomes a labelled section break: an uppercase
section eyebrow, then the line filling the remaining width.

Rules:

- A rule is a separator, not a decoration. Do not stack rules, and do not use
  a field of rules as a texture — the paper background already carries grain.
- Vertical rules sit between columns of the same kind; they stretch to the
  row, so the parent needs to be a flex row.
- On reader pages, rule placement is solver geometry: a rule added in markup
  that the solver did not account for will push copy out of its measured box.
