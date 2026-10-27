# Notification Center

> The **Notification Center** is the console home page for [Review Requests](review-requests.md) and steering opportunities, and it is safe to ignore. See [feature-names.md](feature-names.md#review-requests-and-the-notification-center).

The Notification Center is the CMS console home: the first page an editor sees after signing in (`/newsroom`, the Overview tab, titled
"Notification Center"). Stories PPY-1cd261 (this page) and PPY-ab6a50 (the review requests it lists, see
[review-requests.md](review-requests.md)), under the background-automation epic PPY-9ff95b.

## The principle (Ryan, 2026-10-23)

On a site with a private backend, the main thing an editor does is **interact selectively with a stream of review and steering
opportunities, ignore some of them, and let them run.** If you only look, the system keeps doing what it is doing. If you dig in and
steer something, it takes that steering into account as it moves forward.

What that means for every entry:

1. **Ignore-safe by default.** Everything except a hard gate proceeds if nobody acts. A soft review with an explicit deadline proceeds at it, and one without a deadline (the default) stays open until handled; a flag never
   waits. Each entry says so in words: "Proceeds automatically on 2026-10-30 07:00 UTC unless you steer it." Only a hard gate says
   "Waiting for you."
2. **Steering, not just approve or reject.** Each open entry offers approve and reject (a flag offers acknowledge, stored as the decision `acknowledge` and shown as "Acknowledged by ..."; nothing is approved. Answers stored earlier as `approve` on a flag still read as Acknowledged), a short note ("Steer with
   this note"), and "Not this kind of thing". The steering is stored on the request and the step that raised it reads it back
   (`steering_for`, see the hook below).
3. **Glanceable.** A summary line leads the page: "N waiting for you · N proceeding soon · N recently decided by the system". Waiting
   counts hard gates plus Cyclotron items held for review (both stay put until a person acts); proceeding soon counts open soft reviews.
4. **Deleted stories are marked.** A card whose "About: story ..." points at a story that no longer exists (no version of its lineage remains) shows the id with "(story deleted)", the same wording as the automations run list.
5. **Steering is visible afterwards.** "You steered 'Fewer listicles'. Applied in run run-w43 on 2026-10-20 07:00 UTC." or, before the next
   run, "...idea-pipeline has not used it yet; it will on its next run."
6. **Words and marks, never colour alone** (Ryan is colourblind): "■ Hard gate", "◐ Soft review", "⚑ Flag", "● New", "Held for review".

## What the page shows in v0, in order

| Section | Source | In v0 |
|---|---|---|
| Waiting for you: hard gates | `ReviewRequest`, mode `hard_gate`, open | Entry with approve, reject, note, "not this kind of thing". |
| Proceeding soon: soft reviews | `ReviewRequest`, mode `soft_review`, open, soonest deadline first, requests with no deadline after them (oldest first) | Same controls. A request with an explicit deadline that has passed is marked timed out when the page loads; one with no deadline stays here until someone answers it. |
| Cyclotron items routed to a person | The References tab's own rule: a current relevance decision with `reviewRecommended` on a still-pending reference, least confident first | **Counts, a list of up to 10 and deep links** into the existing References review control. The relevance review control is not duplicated here. |
| Flags | `ReviewRequest`, mode `flag`, open | Acknowledge, note. |
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
