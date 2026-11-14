# DecisionControl

One control for a classification that a model predicts and a human decides,
with the reason in plain sight. It replaced the two-row rating grid in the
References feed, the review card, the What-needs-me cards and the notification
cards, and ships as `components/decision-control.tsx`.

## Why one control, not two rows

The rating grid gives the classifier its own row and the editor another, with
Accept and Reject repeated in both. That treats them as two voters, which is
why it needs duplicate columns, a label column to say whose row is whose, and
roughly twice the height.

They are not two voters. They are **one decision in two stages** — *predicted*,
then *decided*. So there is one pair of segments, and the stages are degrees of
finish:

| Stage | How the segment looks | What it says |
| --- | --- | --- |
| Predicted | the full control tone, sub-label `PREDICTED` | the model's call, nothing recorded |
| Staged, in flight | the chosen fill, `SENDING…` or `UPDATING…` | your answer is on its way |
| Staged, waiting on you | the chosen fill, `NEEDS A REASON` | you chose, something is still missing |
| Decided | solid `primary` fill, `CONFIRMED` or `OVERTURNED` | locked in |

A segment never says it is unrecorded while it is being recorded: in flight it
says `SENDING…`, or `UPDATING…` when it is changing an answer already saved.
`NOT RECORDED` is reserved for the one state that really is — a failed save.

**Three degrees of finish, in tone alone.** The first draft drew the predicted
state as a dashed edge. It could not ship: the feed register tells surfaces
apart by tone and strips every border inside its flat panes, and the feed's own
`design` scenario asserts that nothing there has a border, an outline or a rule.
So the predicted side carries the full control tone, an untouched side is
quieter still, and the chosen one is the solid fill.

**The prediction's opinion survives the answer.** Once you decide, a small
target marker sits in the corner of the segment the model picked — on the
losing segment if you overturned it. That marker is what makes the second row
unnecessary: the comparison stays legible on one line.

**The verdict never tints your own choice.** The decided segment is always
`primary`, whether or not the model agreed; `verdict-match` and `verdict-miss`
colour the marker and the bar, which are the model's. An overturned Reject
painted red reads as *your answer is wrong* rather than *the model was* — the
error this component exists to avoid.

## Three parts, in the order you meet them

**1 · The prediction, as a bar that carries its own confidence.** It sits above
the choice it is about, spans the same width, and fills from the centre toward
the predicted side: `|P(accept) − 0.5| × 2`. The percentage is printed inside
the fill — and nowhere else, so no button has to carry a number. When the fill
is too short to hold it (a near-even prediction) the number sits just beside
it. A one-word caption above says `PREDICTED ACCEPT`, or `NO PREDICTION` rather
than leaving an empty rail to puzzle over.

The bar is the model's, so it never moves when you decide; only its tone
changes. A bar that jumped on your tap would read as *your* confidence.

**2 · The decision**, as the two segments above.

**3 · The reason, in the open.** Not behind a disclosure — a hidden reason is a
reason nobody gives. The block is always visible, at the full width of the
control: a label stating its condition (`REASON · OPTIONAL`, or `· REQUIRED TO
REJECT`) and one field, already two lines tall before anyone touches it, which
grows as it is used.

**Written reasons only.** There are no canned reason chips. A row of
pre-written answers is the path of least resistance, and what it collects —
*Off-topic*, *Duplicate* — is a label the model mostly already has; it is not
an explanation, and it teaches the next prediction nothing. So the only
affordance is the field, and the placeholder says what the writing is for:
*Why? In your own words — this is what the next prediction learns from.*

Either order works. Classify then explain, or type first and then classify:
nothing about the control depends on the reason existing, except the one
required case. When a decision is recorded without one the status line says
`no reason given` — a plain statement of the gap, not a scold and not a boast.

Every part of the control — bar, segments, field and status line — is the same
width, in one column. The field used to overhang the row by its own padding,
which read as the explanation being the only thing that filled the space.

## One status line for the whole block

Fixed height, so a vote never moves the card, and it speaks for everything the
block has captured — not per field:

| Phase | Line | Action offered |
| --- | --- | --- |
| idle | `Nothing recorded yet` | — |
| recording | `Recording…` with a spinner | — |
| recorded, no reason | `Recorded · overturns the prediction · no reason given` | — |
| recorded, with a reason | `Recorded · confirms the prediction · reason saved` | — |
| a reason is required | `A reason is needed to record Reject` | `Record` |
| reason edited after recording | `Recorded · reason not saved yet` | `Save reason` |
| failed | `Not recorded — the backend refused this` | `Try again` |

The decision records itself on tap: one bit, reversible by tapping the other
side, so a confirm button would only slow the feed down. The **one** exception
is a side that requires a reason — then the tap stages the answer, moves focus
to the reason, and the status line names what is missing. That is the only
place a `Record` button appears, and it appears exactly when the product
already needs more from the editor.

A reason typed after the decision is its own small commit (`Save reason`, also
on blur), so *Recorded* never claims more than is true.

## It says "prediction", never a product name

No engine, classifier or product name appears anywhere in this component's
copy: the segment says `PREDICTED`, the status line says *confirms the
prediction*. A Papyrus deployment publishes about any subject with any
classifier behind it, and `AGENTS.md` already forbids baking a classifier id
into application logic — the same rule applies to the words on screen. If a
publication wants to name its engine, that belongs in the surrounding card,
not in the control.

For the same reason the verdict words are `Confirmed` and `Overturned`, which
describe what the editor did. `Match` and `Miss` scored the machine, which is
the two-voter framing again.

## Accessibility

- The segments are a `radiogroup` labelled *Classification*; each is a `radio`
  with `aria-checked`. The predicted state is described, not checked: nothing
  is checked until a human decides.
- The bar is `role="img"` labelled `Prediction: Accept, 96% confident`.
- The status line is a `role="status"` region, so every phase is announced —
  including *overturns the prediction*, which a sighted editor reads from
  colour.
- Stage is never colour alone: dashed edge, fill weight, the sub-label word and
  the marker all carry it.
- The reason field has a real `<label>` tied to it by id.
- Focus is the system's 3px `focus-ring` on every segment, chip, field and
  button.

## Edge cases it has to hold

- **Nothing predicted**: no fill, no dashed segment, the caption says so. The
  first tap decides.
- **A prediction with no confidence**: the bar shows a mild lean and the word
  `unrecorded` rather than inventing a number.
- **A near-even prediction**: the number moves outside the fill.
- **Read-only** (a cached view, or an editor without rights): the predicted
  state still shows, taps do nothing, and the reason appears in words.
- **Changing your mind**: tapping the other segment re-records. Tapping your
  own answer does nothing — it never unselects.

## The alternative, and why it is second

Variant C writes the prediction as a sentence — *Predicted Reject* over its
bar — with `Confirm Reject` and `Overturn to Accept` beneath. It is the most
minimal version and the actions are unambiguous. Two things cost it the
recommendation: the symmetry disappears, so a feed of cards no longer has
Accept and Reject in the same place to aim at; and an item with nothing
predicted has no sentence to write, so it needs a second control. Variant A
degrades to that case by itself.

A slider from Reject to Accept with the prediction as a ghost handle was
considered and dropped: a binary choice should not need a drag, and on a phone
it is the worst target of the three.

## What adopting it changes in the code

No data-layer change was needed, contrary to what the chips suggested:
`use-reference-ratings.ts` already files a reject that carries words but no code
under `other`, and the policy guard in `curationForRelevanceReview` accepts it.
The call, the stored field and the GraphQL contract are untouched.

What does change is the *distribution* of codes. `isScopeTrainingNegativeReason`
treats `out_of_scope` and `policy_exclusion` as scope-training negatives, and
with the chips gone every rejection from this surface files under `other`, so
that signal stops arriving from here. Recovering it means classifying the
written reason — a better input than a chip anyway — rather than restoring the
chips.

## If this is adopted

The specifications that fix the present design move with it:
`features/newsroom-reference-feed.feature` asserts two rows sharing columns,
the words *Match* and *Miss*, and green and red cells. Those scenarios describe
this component's behaviour and would be rewritten alongside it — a spec change
to agree, not a refactor to slip in.
