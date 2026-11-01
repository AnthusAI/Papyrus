# Notification Center

> The **Notification Center** is the console home page for [Review Requests](review-requests.md) and steering opportunities, and it is safe to ignore. See [feature-names.md](feature-names.md#review-requests-and-the-notification-center).

The Notification Center is the CMS console home: the first page an editor sees after signing in (`/newsroom`, the Overview tab, titled
"Notification Center"). Stories PPY-1cd261 (this page) and PPY-ab6a50 (the review requests it lists, see
[review-requests.md](review-requests.md)), under the background-automation epic PPY-9ff95b.

## What the page looks like now ("What needs me?")

The page is one feed that mixes everything that may need a person, in the shape of the References page: flat, rounded cards (no borders or
lines; tones come from the brand), a detail pane beside the feed (a bottom sheet on a phone) with Previous and Next, and the shared Accept / Reject
grid on every card. An editor on the overview should see the same components and patterns as on the References page (Ryan, 2026-10-27).

**What is in the feed.** One model, `NeedsMeItem` (`lib/needs-me-ranking.ts`), with an adapter per source (`lib/needs-me-items.ts`):

| Type | Pill | What it reads | Decided by |
|---|---|---|---|
| `reference` | References | A pending Reference, the Cyclotron's decision on it (label, confidence), its preview picture | The References review (`onReview`): Accept, or Reject with a reason code |
| `incomplete_capture` | Captures | The same Reference when a capture was attempted and came up short: thin text, or a curation card that records no text (`lib/reference-capture.ts`). A Reference nobody has tried to capture is not listed. | The same review; the detail also has "Paste or correct the text" |
| `idea_batch` | Ideas | ONE card per idea-pipeline review request (a batch): the ideas filed in that run with their stage, and a link "Open the Idea column" to the Stories board | The Stories board: move an idea forward to accept it, or to `spiked` with a reason to decline it. The card has no Accept or Reject |
| `stage_review` | Stories | An open hard gate or soft review that is not about a batch of ideas: reason, ask, deadline, the subject story's title and opening paragraphs | `answerReviewRequest`: approve or reject, with an optional Why |
| `held_email` | Email | An email submission held for review (Monitoring's own list): subject, sender facts, SPF/DKIM/DMARC verdicts, inert text, links as text | `decideMonitoringEmailSubmission`: Accept releases it, Reject discards it |
| `flag` | Other | An open flag | Acknowledge |
| `concept_proposal` | Other | A proposed taxonomy concept or a reader's proposal | **Stub**: typed, returns nothing yet |

**Order.** Hard gates first, oldest first. Then the interim *value of your input*: `uncertainty x importance`.
Uncertainty is `1 - |2P - 1|` with P the Cyclotron's probability that you would Accept (a coin toss is 1, a certainty 0), and 0.5 when the item has no
prediction. Importance is the item's own priority (a relevance score, or a story or section priority); no source supplies one yet, so it is 1. Age does not
change the score: the Cyclotron's own confidence is used as it was recorded. The result is interleaved so that no
more than two items of one type sit in a row while another type waits. The scoring lives in one module behind the `AttentionModel` interface; a future Cyclotron "attention"
decision replaces `interimAttention` and nothing else changes.

**Confident items do not ask for you.** An open item with a prediction whose uncertainty is below the learned threshold goes to **Decided automatically**, collapsed, with an
Overrule button that opens it in the detail pane. The threshold is the median uncertainty of the predictions you have confirmed (the Reference you accepted or rejected agreed with the
Cyclotron); with fewer than 10 confirmed predictions there is no threshold and nothing is skipped. A hard gate, an item the Cyclotron or the raising step asked a person about
(`reviewRecommended`, every idea batch, review and email), and an item with no prediction are never skipped. This iteration shows the Cyclotron's suggestion and lets you
overrule it; it does not yet write the suggestion back as the decision.

**One order per visit.** The order is taken once when every source has been read, and then left alone: selecting, deciding, a refresh or the cached view never re-rank it. A card you decide
stays where it is, showing the answer. Items that arrive later wait behind an "N new items: show" pill (the same rule as the References feed).

**Pills** (All, References, Ideas, Stories, Email, Captures, Other) count what waits and narrow the feed to one type. **"You're shaping this"** is a slim strip: this calendar week (Monday, UTC),
how many decisions you made, how many References you rated in agreement with the Cyclotron and how many you overruled. **"How this is ordered"** opens the recipe in plain words with this
site's learned numbers.

**If you ignore an item** its default stands, and the card says so in words ("Closes on ... if nobody answers. The ideas stay in the Idea column.", "Held privately; nothing is routed unless you accept
it.", "It stays pending with the Cyclotron's suggestion: Accept 82%."). Only a hard gate says "Waiting for you."

**Loading.** Skeleton cards at once; a return visit paints the last view (saved in this browser, display only, dropped on sign-out) marked "Showing your last view while it updates", and answering waits for the live
read. Held email is not in the saved copy; it joins when read.

The model is `lib/needs-me-ranking.ts` (scoring, order, threshold, snapshot, counts, the strip) and `lib/needs-me-items.ts` (adapters); the view is `components/needs-me-feed.tsx` (cards, pills, strip, detail
shell), `components/needs-me-detail.tsx` (one body per type) and `components/needs-me-shared.tsx`; `components/notification-center.tsx` loads the sources and routes each decision to its action. Review-request
wording and the idea-batch model stay in `lib/notification-feed.ts` and `lib/review-requests.ts`. Preview with real data: `scripts/export-notification-center-fixture.py` (read-only, IAM, strips people) beside
`scripts/export-reference-feed-fixture.py`, then `PAPYRUS_FEED_FIXTURE=... PAPYRUS_NOTIFICATION_FIXTURE=... npm run dev:preview`; `scripts/capture-notification-center-shots.mjs` takes the screenshots.
The sections below describe the review-request rules, which still hold; the table of sections is the earlier layout.

## The principle (Ryan, 2026-10-23)

On a site with a private backend, the main thing an editor does is **interact selectively with a stream of review and steering
opportunities, ignore some of them, and let them run.** If you only look, the system keeps doing what it is doing. If you dig in and
steer something, it takes that steering into account as it moves forward.

What that means for every entry:

1. **Ignore-safe by default.** Everything except a hard gate carries on if nobody acts. A soft review with a deadline simply closes at it, and one without a deadline (the default) stays open until answered; a flag never waits. Each entry says what that means in words. For ideas to review: "Closes on 2026-10-30 07:00 UTC if nobody answers. The ideas stay in the Idea column." or "No deadline." Nothing is ever published by a deadline. Only a hard gate says "Waiting for you."
2. **One decision vocabulary: Accept or Reject.** Each open request offers Accept and Reject (a flag offers Acknowledge, stored as the decision `acknowledge`; nothing is accepted), an optional full-width "Why?" box, and, as a reason to reject, one chip: "Not this kind of thing". The chip is stored as the steer `not_this_kind`, and the step that raised the request reads it back (`steering_for`, see the hook below). Stored decisions keep their old names (`approve`, `reject`, `feedback`); the page says Accepted and Rejected.
3. **Generated ideas are one card, decided on the board.** A review request raised by `idea-pipeline` (subject type `batch`) whose links are the ideas filed in that run shows as ONE card, type "Ideas to review": the list of its ideas with each one's stage, and a link "Open the Idea column" to the Stories board (`/newsroom/work`). It has no Accept or Reject and no Why box: an editor accepts an idea by moving it forward and declines it by moving it to `spiked` with a reason, and those stage moves are the feedback the next run reads (`ItemStore.feedback`). The card disappears when none of its ideas is left in the Idea column. Older batch requests whose links are Proposals (raised before ideas became Items) get no card; `papyrus ideas migrate-proposals` turns the open `story_draft` Proposals into idea Items once.
4. **Glanceable.** A summary line leads the page: "N waiting for you · N ideas to review · N other reviews open · N recently decided by the system". Waiting counts hard gates plus Cyclotron items held for review. Ideas counts the ideas still in the Idea column in open batch reviews.
5. **Deleted stories are marked.** A card whose "About: story ..." points at a story that no longer exists shows the id with "(story deleted)".
6. **Steering is visible afterwards.** "You steered ... Applied in run run-w43 on ..." or, before the next run, "... has not used it yet; it will on its next run."
7. **Words and icons, never colour alone** (Ryan is colourblind), and Lucide icons only.

**What "Not this kind" does.** `steering_for(raised_by="idea-pipeline")` returns the answer, and `ideas synthesize` shows it to the model as reviewer feedback on its next run (`read_steering`, `mark_applied`). Trend-story and monitor-story runs raise their batches as `idea-pipeline` too but do not read steering back, so only the next story-idea synthesis run sees an answer given on the request; stage moves on the board are read by every run.

**Layout and corners.** The feed and the detail fill the viewport's height and scroll on their own; the other sections of the home (open assignments, sections) sit at the end of the feed's own scroll, so they never push anything up. On a wide screen the Previous / Next bar is fixed to the bottom-right corner of the viewport (the detail column's width); on a phone it is the fixed bottom of the sheet. Every corner radius of the feed layer comes from four tokens in `components/newsroom-organizer.css` (`--feed-radius-xl` 12px, `-lg` 10px, `-md` 8px, `-pill` 8px), so the roundness is tuned in one place.

## The reason, in any order

Ryan, 2026-10-27: "I rated the three stories and one recorded only the label and not the explanation, and the UI did not let me update the explanation." Every decision surface now behaves like the References feed (PR #798): the label and the explanation can be given in either order, the explanation can be changed whenever the item is reopened, and nothing typed is ever lost.

* **The Why? box is always there**, empty or holding the saved reason, whether the item is open or decided. The Accept or Reject of a review request or a held email is final here (a request has closed, an email is queued), so a decided item shows its choice and keeps only the Why editable.
* **Reason, then vote:** the vote carries the Why that was typed. **Vote, then reason:** the Why is saved onto that decision after a short pause (1.2 seconds without typing) or when the box loses focus. Changing the vote of a Reference keeps its reason (#798). One shared rating store (`components/use-reference-ratings.ts`) serves the card and the detail pane, so either shows what the other saved.
* **Saved tick, errors in words, no lost text.** The status line under the box says "Saving…", then "Saved" with a tick, or says in words why it could not save ("Your note could not be saved. It is kept here; keep typing or tap away to try again."). The typed text stays in the store until it is saved; tapping away, the next pause, or leaving the page tries again.
* **Reopening shows the saved reason**, in the box in the detail pane and as a clipped "Why: ..." line on the card.

Which operation saves a later edit:

| Item | Operation | What changes |
| --- | --- | --- |
| Hard gate, stage review, flag (acknowledged) | `saveReviewReason` with `answerReasonUpdate` | `answer.feedback`. The decision, the steer, who and when stay. |
| Held email | `monitoringDecideEmailSubmission` again, with the same decision and the new reason | The Monitoring view rewrites the decision row's `reason` (and `reasonEditedAt`) until the receiver has applied the decision. Afterwards the receipt keeps the reason it was applied with, the page says so in words, and no row is written. A repeat with no reason changes nothing. |
| Reference, incomplete capture | the References review (`onRateReference`) with the same choice and the new note (#798) | `curationStatusReason` on the existing rating. |


## What the page shows in v0, in order

| Section | Source | In v0 |
|---|---|---|
| Waiting for you: hard gates | `ReviewRequest`, mode `hard_gate`, open | Accept, Reject, Why, "Not this kind of thing". |
| Ideas to review | Open soft reviews raised by `idea-pipeline` whose links are idea Items, soonest deadline first | One card per batch with a link to the Idea column; no Accept or Reject. |
| Other reviews | Every other open soft review, soonest deadline first, no deadline after them | Accept, Reject, Why. A request whose deadline has passed is marked timed out when the page loads; one with no deadline stays until answered. |
| Cyclotron items routed to a person | The References tab's own rule: a current relevance decision with `reviewRecommended` on a still-pending reference, least confident first | **Counts, a list of up to 10 and deep links** into the existing References review control. The relevance review control is not duplicated here. |
| Flags | `ReviewRequest`, mode `flag`, open | Acknowledge, Why. |
| Answered, and what became of it | Answered, timed-out and withdrawn requests, newest first | Shows "proceeded without review" and "You steered ... applied in run Y". |
| Recently decided by the system (collapsible) | Current relevance decisions that were not routed to a person, newest first, 20 | **Read only**, with a link to correct each in References. Filtering by publication, label and confidence, and correction feeding ground truth, are follow-ups. |

Read and unread are tracked per user (`ReviewReadMark`, one row per user and request). Opening an entry's item, answering it, or "Mark read"
marks it read. The Cyclotron lists have no read state in v0.

Not in v0: an email per new hard gate (see [review-requests.md](review-requests.md#email)), Slack, the filters on the stream, and the
correction-to-ground-truth path.

## Code

* `components/notification-center.tsx`: the container that loads, answers and marks read; the view is `components/needs-me-feed.tsx` (`NeedsMeView`, pure).
* `lib/review-requests.ts`: sections, ordering, summary, the words, the answer and timeout updates (shared by the page and its tests).
* `lib/review-client.ts`: the GraphQL calls; every change carries the condition `state = open`.
* `components/newsroom-ops-overview.tsx` mounts it above the existing destinations.
* Tests: `scripts/test-notification-center.ts`.

**Needs attention** (the Overview's list of pending references) shows the Cyclotron's suggestion on each row: the same read-only Cyclotron row as the review card (Accept or Reject highlighted with its confidence, or "No prediction"). The row opens the reference in the review queue, where the decision is made.

There is no "Proposed Stories" entry in the sidebar: generated ideas live in the Idea column of the Stories board. The Proposals panel (`/newsroom/administration/proposals`, under Administration) is only for other Proposals (renames, merges, new concepts, reader-filed proposals) and hides old `story_draft` rows.

Tests: `scripts/test-needs-me-ranking.ts` (score, order, threshold, snapshot, adapters), `scripts/test-notification-center.ts` (review-request model and words, the rendered page), `scripts/test-notification-center-feed.ts` (browser, 375 and 1440 px, fake data API), `features/newsroom-notification-center.feature` (`npm run test:notification-center`).
