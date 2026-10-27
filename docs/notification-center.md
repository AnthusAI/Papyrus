# Notification Center

> The **Notification Center** is the console home page for [Review Requests](review-requests.md) and steering opportunities, and it is safe to ignore. See [feature-names.md](feature-names.md#review-requests-and-the-notification-center).

The Notification Center is the CMS console home: the first page an editor sees after signing in (`/newsroom`, the Overview tab, titled
"Notification Center"). Stories PPY-1cd261 (this page) and PPY-ab6a50 (the review requests it lists, see
[review-requests.md](review-requests.md)), under the background-automation epic PPY-9ff95b.

## What the page looks like now ("What needs me?")

The page is a feed of flat, rounded cards in the style of the References feed (no borders or lines; tones come from the brand). A short header
says what waits ("3 drafts and 12 references waiting for you"), and pills narrow the page: All, Drafts, References, Other.

* **Drafts.** Every AI draft is its own card: the cited source's picture, headline, dek, section, the evidence line, source chips (favicon and
  domain), a caption "from Monitor stories run · Oct 27" and "Open full draft", then the shared Accept / Reject grid (no Cyclotron row, a draft has
  no prediction) with an optional full-width Why?. Reject is one tap; a quiet "Not this kind of story" chip beside the Why? box, when on, is the steering signal. A request that covers several drafts is never shown as a batch; it closes itself when its last draft is decided. A card decided
  in this visit stays in place showing its answer.
* **References.** The References feed's own cards (best bets first, a screenful at a time), rated in place through the References review; a card opens the
  References queue.
* **Other.** Hard gates and other soft reviews are cards with Accept / Reject; flags are slim cards with Acknowledge and an optional note.
* **Decided automatically (N)** is a collapsed footer listing what the Cyclotron decided on its own confidence, read only.
* **All caught up** when nothing waits, with the last few things you decided ("Recently decided" is always shown under the cards).
* **Loading.** Skeleton cards at once; a return visit paints the last view (saved in this browser, display only, dropped on sign-out) marked "Showing your
  last view while it updates", and answering waits for the live read. The References reads start as soon as the session is confirmed, as on the References page.

The model is `lib/notification-feed.ts`; the cards are `components/notification-cards.tsx`. The earlier "Needs attention" list, the Cyclotron "held" list and the unread badges are gone from the page. The nav item is "Needs me".

Preview with real data: `scripts/export-notification-center-fixture.py` (read-only, IAM, strips people) beside `scripts/export-reference-feed-fixture.py`, then
`PAPYRUS_FEED_FIXTURE=... PAPYRUS_NOTIFICATION_FIXTURE=... npm run dev:preview`; `scripts/capture-notification-center-shots.mjs` takes the screenshots.
The sections below describe the model and the rules, which still hold; the table of sections is the earlier layout.

## The principle (Ryan, 2026-10-23)

On a site with a private backend, the main thing an editor does is **interact selectively with a stream of review and steering
opportunities, ignore some of them, and let them run.** If you only look, the system keeps doing what it is doing. If you dig in and
steer something, it takes that steering into account as it moves forward.

What that means for every entry:

1. **Ignore-safe by default.** Everything except a hard gate carries on if nobody acts. A soft review with a deadline simply closes at it, and one without a deadline (the default) stays open until answered; a flag never waits. Each entry says what that means in words. For AI drafts: "Closes on 2026-10-30 07:00 UTC if nobody answers. The drafts stay in Proposals." or "No deadline." Nothing is ever published by a deadline. Only a hard gate says "Waiting for you."
2. **One decision vocabulary: Accept or Reject.** Each open request offers Accept and Reject (a flag offers Acknowledge, stored as the decision `acknowledge`; nothing is accepted), an optional full-width "Why?" box, and, as a reason to reject, one chip: "Not this kind of thing" (for a draft, "Not this kind of story"). The chip is stored as the steer `not_this_kind`, and the step that raised the request reads it back (`steering_for`, see the hook below). Stored decisions keep their old names (`approve`, `reject`, `feedback`); the page says Accepted and Rejected.
3. **AI drafts are shown in place.** A review request whose links are proposals (a trend story batch, a monitor story batch, an idea batch, or one proposal as the subject) shows each draft: headline, dek, section, evidence (the signals it rests on, or the monitor that found it), the cited sources with links, and "Open the full draft in Proposals" (the Proposals panel opens on it, `?proposal=<id>`). Each draft has its own Accept and Reject:
   * **Accept** moves the Proposal to `approved` (a draft walks `in_steering`, `editor_review`, `approved`, one `transitionProposal` call each, as the panel's own buttons do). **Reject** moves it to `declined`. A draft on hold says so and does not move. A refused move is said in words and nothing is recorded.
   * The Why and the chip are read when the editor taps Accept or Reject, so write them first. The Why is kept on the request, never sent as the Proposal's (public) transition reason.
   * Each decision is recorded on the request's link (`links[].decision`). When every draft that can be opened is decided, the request closes itself (answered): all Accept is `approve`, all Reject is `reject`, a mix is `feedback` with a note naming each draft; the answer carries `drafts` and `steer: not_this_kind` when any rejection used the chip. Drafts decided in Proposals instead also close the request. A draft that is not a Proposal on this site (an idea kept only as JSON) cannot be opened; if none can be, the request itself takes Accept or Reject.
4. **Glanceable.** A summary line leads the page: "N waiting for you · N AI drafts to review · N other reviews open · N recently decided by the system". Waiting counts hard gates plus Cyclotron items held for review. AI drafts counts drafts not yet decided in open draft reviews.
5. **Deleted stories are marked.** A card whose "About: story ..." points at a story that no longer exists shows the id with "(story deleted)".
6. **Steering is visible afterwards.** "You steered ... Applied in run run-w43 on ..." or, before the next run, "... has not used it yet; it will on its next run."
7. **Words and icons, never colour alone** (Ryan is colourblind), and Lucide icons only.

**What "Not this kind" does.** `steering_for(raised_by="idea-pipeline")` returns the answer, and `ideas synthesize` shows it to the model as reviewer feedback on its next run (`read_steering`, `mark_applied`). Trend-story and monitor-story runs raise their batches as `idea-pipeline` too but do not read steering back, so for those batches the answer is stored and visible but only the next story-idea synthesis run sees it.

## What the page shows in v0, in order

| Section | Source | In v0 |
|---|---|---|
| Waiting for you: hard gates | `ReviewRequest`, mode `hard_gate`, open | Accept, Reject, Why, "Not this kind of thing". |
| AI drafts to review | Open soft reviews whose links are proposals, soonest deadline first | Each draft in place with its own Accept and Reject. |
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

* `components/notification-center.tsx`: the view (`NotificationCenterView`, pure) and the container that loads, answers and marks read.
* `lib/review-requests.ts`: sections, ordering, summary, the words, the answer and timeout updates (shared by the page and its tests).
* `lib/review-client.ts`: the GraphQL calls; every change carries the condition `state = open`.
* `components/newsroom-ops-overview.tsx` mounts it above the existing destinations.
* Tests: `scripts/test-notification-center.ts`.

**Needs attention** (the Overview's list of pending references) shows the Cyclotron's suggestion on each row: the same read-only Cyclotron row as the review card (Accept or Reject highlighted with its confidence, or "No prediction"). The row opens the reference in the review queue, where the decision is made.

**Drafts** is an Editorial work navigation item that opens the Proposals panel (`/newsroom/administration/proposals`), so drafts are reachable outside Administration.

Tests: `scripts/test-notification-center.ts` (model and words), `scripts/test-notification-center-drafts.ts` (browser, 375 and 1440 px, fake data API), `features/newsroom-notification-center.feature` (`npm run test:notification-center`).
