# Eyebrow

Uppercase editorial furniture: kickers, section labels, bylines and meta rows.
This is the one place uppercase type is allowed.

Roles map to the four Furniture type styles. `kicker` (default) is the small
line above a headline and the continuation heading. `section` is a section
label or inside-page header, and is the only role in `ink-strong`. `byline`
is attribution. `meta` is a values row — desk, lane, read time, status —
separated by `·`.

Rules:

- Pass the text already written as a label: terse, no trailing punctuation,
  one or two lines at most.
- Tracking is part of the style. Do not add letter-spacing on top of it, and
  do not use `text-transform` to fake a label out of sentence-case copy — write
  the label.
- `tone="alarm"` paints `danger-text` and means a live alarm state, not
  emphasis. On the Threat Intelligence brand it is the alarm red; everywhere
  else it is the same destructive hue.
- Use `as="h2"` when the label is genuinely the heading of a section, so the
  document outline is right; the default `span` is for furniture that is not a
  heading.
