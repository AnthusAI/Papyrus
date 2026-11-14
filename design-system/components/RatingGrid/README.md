# RatingGrid

One grid that puts a machine prediction and a human answer in the same columns,
so an editor can see at a glance whether the Cyclotron agreed with them.

It ships in the Papyrus repository as `components/review-rating-grid.tsx` and is
used by the References feed, the review card, the What-needs-me cards and the
notification cards. This card is the design contract; the repository file is the
implementation.

## The shape

Three columns — label, Accept, Reject — and two rows that share them exactly:

```
Cyclotron   [ Accept 96% ]   [ Reject ]     read only; the predicted side is highlighted
            [====== confidence, centred at 50% ======]
You         [ Accept ]       [ Reject ]     the real buttons, each under its matching cell
```

The confidence bar fills from the centre outward: `|P(accept) − 0.5| × 2`, so a
50/50 prediction shows nothing and a 96% Accept nearly fills the right half. A
prediction with no recorded confidence is a mild lean, not a certainty.

The grid sizes itself with a container query on its own width, not the window's.
On a card as narrow as 240px the label column shrinks to its word, the padding
tightens, and the confidence moves onto its own line inside the cell rather than
spilling out of it.

## Tokens it uses

Every tone, corner and opacity is a token; the component holds no palette value
of its own beyond a last-resort fallback for surfaces that declare none.

| Slot | Token |
| --- | --- |
| Cell and button ground | `--feed-control` |
| Bar centre notch | `--feed-footer` or `--feed-card`, per the `surface` prop |
| Chosen button | `--primary` / `--primary-foreground` |
| Match cell | `verdict-match-tint` + `verdict-match-ink` |
| Miss cell | `verdict-miss-tint` + `verdict-miss-ink` |
| Bar fill | `verdict-match`, `verdict-miss`, else `--primary` |
| Corners | `--feed-radius-md` |
| Switched-off step | `--feed-quiet` |
| Focus | 3px ring in `--ring` |

## Rules

- **Feedback is never colour alone.** A verdict cell carries the icon
  (CircleCheck / CircleX) and the word (Match / Miss) as well as the tint, and
  the screen-reader text says whether the prediction matches.
- **A vote never changes the height of the card.** The confidence and the
  verdict share one line inside the cell, and the saved tick can be laid over
  the surrounding padding (`statusOverlay`) so it adds no row.
- **The bar sits midway between the two rows.** Nothing visible goes under it;
  the state line beneath is screen-reader only.
- **A switched-off grid never votes**, whatever the caller passes as
  `onChoose`; it says why in words through `disabledReason`.
- Pass `showPrediction={false}` for an item with nothing to predict (an AI
  draft): the Cyclotron row and the `You` label drop out and only the two
  buttons remain.
- The consumer owns saving. The grid reports `feedback.phase` and nothing else;
  it does not know about GraphQL, and it does not retry.
