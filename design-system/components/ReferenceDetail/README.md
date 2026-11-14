# ReferenceDetail

The whole pane an editor works in when they open a reference: what the source
is, the decision, the messages about it, and the state of the text Papyrus
captured from it. Composed in `components/needs-me-reference-detail.tsx` as
`ReferenceBody`, from `ReviewCard`, `DecisionControl`,
`ReferenceSuggestionProvenance`, `ReferenceConversation` and
`ReferenceCapturePanel`.

## Six zones, in reading order

1. **What it is** — title (linked to the source), dek, the source preview
   image, status badges, and the stored summary. An editor reads the thing
   before judging it, so nothing interactive comes before this.
2. **The decision** — `DecisionControl`: the prediction bar with its
   confidence, the two buttons, the written reason, one status line.
3. **Why it was predicted** — the provenance line: which topic it scored
   against, how many accepted examples back it.
4. **Messages** — the thread, with replies indented one step and a composer at
   the end. Each message is a tone block, not a bordered card.
5. **Our captured record** — the state of the captured text (full, partial,
   missing), the text itself behind a show-all toggle, the two correction
   routes (*Paste or correct the text*, *Upload a PDF*), and the
   *was the capture complete?* assessment.
6. **Provenance** — imported date and media type, as a two-column definition
   list.

A sticky queue bar (`Previous · 4 of 23 · Next`) sits under all of it when the
pane is opened from a list.

## What the composition gets right

- **One column, one width.** Every zone spans the pane; nothing is inset or
  narrowed, so the eye tracks straight down.
- **Reading before judging.** The decision sits after the summary, not above
  it.
- **Tone, not boxes.** Messages, the capture record and the correction routes
  are tone blocks in the feed register — no borders, no nested cards.

## What is worth improving

- **Zone 5 is heavy.** *Paste or correct the text* and *Upload a PDF* are two
  panels of near-equal weight, each with its own note field and verdict, for
  something most references never need. They could collapse behind the status
  line until the capture is actually in question — the status already says
  whether it is.
- **Two places ask "what do you think?"** The decision's reason field and the
  capture's note field look alike and sit four zones apart. An editor who
  types their reasoning into the capture note has filed it where nothing will
  learn from it.
- **The assessment group repeats the decision's shape.** *Complete /
  Incomplete / Not sure* is a second segmented answer with the same tones as
  Accept / Reject, which reads as a second verdict of equal weight.
- **Zone 3 is a sentence with no home.** The provenance line floats between the
  decision and the messages; it belongs with the prediction it explains, under
  the bar.
- **Status badges and the capture state say overlapping things** in different
  shapes — a pill at the top, a tone block in the middle.

## Rules

- The queue bar is navigation, never a place to answer from: an editor should
  not be able to rate and advance without the answer landing first.
- The pane never scrolls a zone of its own; the pane scrolls.
- Nothing here fetches on the editor's behalf except the capture text, which
  loads with its own status line rather than blocking the pane.
- Disabled means a reason in words. Every control in the pane takes the same
  `disabledReason`, and the pane says it once rather than per control.
