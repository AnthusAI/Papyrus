# Scheduled publishing and automated announcements

Status: plan only. Nothing here is built. Epic: PPY-09ee86 (blocked by PPY-271940; related to PPY-156614 and PPY-824c14). First site: Machines on Machines (MoM).

## What was asked

Ryan, 2026-11-12, condensed:

1. We write faster than we want to publish. Publish at chosen times so work is spread out.
2. Scheduling only pays off once something announces what went live. Build an automated announcement system that posts on X (Twitter) as soon as something new qualifies.
3. A configuration area where a site owner connects accounts and API keys and decides what is announced (only 5 stars? 4 stars too? accepted research?). MoM starts with 5 stars only; then we look at the rate (about zero today) and adjust.
4. Use X only for announcements for now (research use may come later).
5. Depends on the published-date work (PPY-156614, especially PPY-271940).
6. On a newsroom item: see and change its scheduled time, beside what exists (published or not, publish now).
7. A schedule view by day, week or month, built on an off-the-shelf React calendar. No home-made calendar logic.

Standing rules that shape this plan: fix causes, no workarounds, fallbacks or shims; the simplest design that meets the need; narrative Gherkin for every behaviour; no fixed limits (a rate, spacing or budget comes from data or from a per-site setting with a written reason); DynamoDB is the catalog and text lives in S3; no whole-table reads and no O(N) work per change; no AppSync subscriptions; at most one new index per table per deploy; secrets only in SSM SecureString, never in Git, logs, chat or the UI after entry; no hand-made cloud resources; outward-facing automation needs per-site opt-in and a visible pause switch; Lucide icons, flat fills, no borders, colour never the only signal, plain words; a site's accounts and keys belong to the site owner.

## Summary

- **Scheduling** pins one immutable Story version to one moment. Four fields on that version's Item row (`scheduledPublishAt`, `scheduledBy`, `scheduledAt`, `scheduleState`), one new sparse index (`scheduleState` + `scheduledPublishAt`) for the schedule view, and one EventBridge Scheduler one-off schedule per scheduled version, exactly as the newsletter schedules an approved send. At the time, the normal publish path runs. If a newer version was saved after scheduling, nothing is published and the editor is told: versions are immutable, so there is no content hash to compare.
- **Announcements** go through Caducus, as Ryan decided for every notification: an announcement is a Caducus kind delivered on a new `x` channel to the site's connected account. Papyrus decides eligibility (published and rated at or above the site's announcement floor, default 5 on MoM), drafts the post text (model-drafted from the Story's own title, dek and summary, checked like any model-written text), and holds it for approval when the site asks. Caducus dedupes, delivers, records the post id and cost, and paces.
- **Accounts** are the site owner's: the owner's own X developer app (the owner pays X), connected through OAuth 2.0 Authorization Code with PKCE. The client secret and the rotating refresh token live in SSM SecureString per site and account and are never shown again.
- **Cost control** is a per-site budget the owner sets per X billing cycle (no default number), a running spend counter updated once per post, automatic pause when the next post would pass the budget, and a suggested budget computed from the site's own rate of eligible Stories.
- **Calendar**: FullCalendar 7 (`@fullcalendar/react`, MIT), loaded only on the schedule page. The spike is in `spikes/scheduling-calendar/` on this branch.

## What exists today (verified on `origin/develop`)

| Piece | Where | What it gives us |
| --- | --- | --- |
| First-publish time | `publishing.py`, `story_published_dates.py` (PPY-271940, merged in #1455; board still open) | `publishedAt` is the first publication and is carried forward; `versionPublishedAt` is when the served version went live. Scheduling relies on this: a scheduled republish must not reset the first date. |
| One-off schedules | `src/papyrus_content/newsletter/scheduler.py` | `at(...)` schedules in UTC, `ActionAfterCompletion: DELETE`, create-or-update by a stable name (`papyrus-nl-<site>-<issue8>`). The home-page plugin uses the same pattern for its trailing debounce, with a dedicated scheduler role limited to a name prefix. |
| Approve-then-send with a content check | `newsletter/issues.py` (`contentHash`, "edited after approval; approve again") | The model for "changed after scheduling". For Stories it is simpler: the schedule pins a version id. |
| The publish announcement hook | `src/papyrus_content/publish_alerts.py` | The only place a publish announces. Invokes the newsletter and the `notifications` router asynchronously on a real publish (`PublishResult.changed`), after the page is live, never on unpublish or reprojection. Announcements hang off this hook. |
| Caducus in each site | `amplify/plugins/notifications/`, `docs/notifications.md`, Caducus `docs/notifications-plan.md` | Per-site table, dedupe by event id, delivery log with `providerMessageId` and status, a `Channel` interface (email now; Slack and Discord planned), approval setting on lists. Built, off everywhere. |
| Ratings | `item_stars.py` (`effective_rating`), PPY-0e8d66 | The three-star floor for anything public or in a notification. Unrated is 0 and never qualifies; a model prediction never qualifies. |
| Retirement | `story_retire.py` | Retire with redirect. Announcements must follow it. |
| Share card | `share_preview.py`, `share_image_check.py` | Open Graph and Twitter card tags on every Story page. X builds the link card from these, so no media upload is needed. |
| Operations shared by CLI and routes | e.g. `editorial_checks.py` `OPERATIONS` | One operation table that the console route, the CLI and MCP call. |

## Scheduling model

**Where the schedule lives.** On the Item row of the version being scheduled: `scheduledPublishAt` (UTC ISO instant), `scheduledBy`, `scheduledAt` (when the schedule was set), `scheduleState` (`scheduled`, present only while scheduled, so the index stays sparse), and `scheduleName` (the EventBridge schedule name). A separate schedule record would be a second source of truth for the same fact; the version row is already the thing that gets published. One new index on Item: `scheduleState` + `scheduledPublishAt` (`listItemsByScheduleStateAndScheduledPublishAt`). Item has nine indexes today, so this is the tenth and the only index in that deploy. The schedule view queries one time range of that index; nothing reads the whole table.

**Who may schedule.** Whoever may publish on that site may schedule, unschedule and reschedule. The same check as publishing, no new role.

**Which version.** Scheduling pins the version the editor is looking at. Versions are immutable, so "the content that was reviewed" is exactly that version id. At the scheduled time, if the Story's head is still that version (or the pinned version is the newest unpublished one), it is published. If a newer version was saved after scheduling, nothing is published, the schedule ends in state `blocked` with the plain reason "A newer version was saved after this was scheduled. Schedule it again.", and the editors are notified through Caducus (an operator-class kind, as alarms are). No hash, no silent publishing of unreviewed text.

**Time zones and DST.** Store the UTC instant only. Show and pick times in the publication's time zone, a site setting (`publication.timeZone`, an IANA name such as `America/New_York`; added to the standard front-end config if it does not exist, required when scheduling is enabled). Picking a wall-clock time that does not exist (the spring-forward gap) is refused with "That time does not exist on 8 March in New York. Pick another time."; a time that happens twice (fall back) asks which one, showing both offsets. The drawer always shows the time with its zone name, and the editor's own zone in small type when it differs.

**Execution: one-off schedules, not a sweeper.** Each scheduled version gets one EventBridge Scheduler schedule `papyrus-pub-<siteId>-<item8>` (`at(...)`, UTC, `FlexibleTimeWindow OFF`, `ActionAfterCompletion DELETE`) that invokes `content-actions` with `{"task": "publish-scheduled", "itemId", "scheduledPublishAt"}`, through a scheduler role limited to that name prefix (the home-page pattern). Rescheduling updates it; unscheduling deletes it. A periodic sweeper would need a period, which is a fixed number we do not have data for, and would add latency up to that period. One-off schedules fire at the moment, cost nothing while waiting, and the pattern is already in the code twice.

**Exactly once.** The task first does a conditional update on the version row: `scheduleState = scheduled AND scheduledPublishAt = <the time in the event>` to `scheduleState = publishing`. A stale or duplicate invocation fails the condition and stops. Publishing itself is idempotent (`PublishResult.changed`). On success the schedule fields are removed and `versionPublishedBy` records the scheduler on behalf of `scheduledBy` (for example "scheduled by Sam").

**Missed or failed schedules.** EventBridge Scheduler retries with its retry policy and then sends the event to a dead-letter queue with an alarm, which reaches the operator listener as every dead-letter alarm does. The newsroom shows any version whose `scheduledPublishAt` has passed while it is still `scheduled` or `publishing` as "Overdue" (icon plus word) in the badge and the schedule view, read from the same index. There is no sweeper that publishes late items behind the editor's back: an overdue item is shown and the editor decides (publish now or reschedule).

**Publish now, unpublish, retire.** "Publish now" on a scheduled version publishes it and removes its schedule. Saving a newer version does not touch the schedule (it blocks at fire time, as above), but the drawer shows "A newer version exists than the one scheduled" at once. Retiring a Story removes any schedule on its versions. Scheduling a version of a Story that is already published means "publish this new version at that time" and keeps the first publication date (PPY-271940).

**Quality floor.** Scheduling, like publishing, does not require stars (PPY-0e8d66: an unrated published page is reachable but not listed). The drawer says so when the version is unrated: "Unrated: it will publish but will not be listed or announced until it is rated."

**Dates and the edge cache.** A scheduled publish is a normal publish: `publishedAt` is the moment it actually went live (not the scheduled moment, which may differ by retries), `versionPublishedAt` likewise. The projection and the exact-page invalidation of the normal publish path apply; the forum's short-lived prefixes do not concern Stories.

**Spreading out: slot suggestion.** The date picker offers "Next suggested time", learned from the publication's own history, with the manual choice always available. Two small facts are kept, each updated once per first publication (O(1) per publish, kept in one small JSON in the site store): a count of first publications per hour of the week in the publication's time zone, and the total count with the time of the first one. The suggestion is the earliest hour after both "now" and "the latest scheduled time plus the publication's mean gap between first publications (span divided by count)" whose hour-of-week has the most past publications within the following day. No fixed spacing, no fixed window: a site that publishes hourly gets hourly slots, one that publishes twice a week gets that. With no history the field offers no suggestion and says why.

## The schedule view

A newsroom page "Schedule" (calendar Lucide icon). Week view by default, Day and Month switches; on screens narrower than the week grid needs (the spike shows the 7-day grid overflows at 375px) it opens in a list of the week instead. Each item shows a Lucide icon and a word (Scheduled, Overdue, Blocked, Published) and the title; colour only repeats what the word says. Under the calendar a plain list of the same items (time, title, state, link to the Story drawer) is the keyboard and screen-reader path. Drag to reschedule is on: FullCalendar makes it one option plus a drop handler that calls the same reschedule operation, which revalidates the time (DST, past times) and can be undone from the toast. Empty state: "Nothing is scheduled this week." with the button "Schedule a Story" that opens the Ideas/Drafts board. Published items in the visible range come from the existing `publishedAt` indexes, so the view shows what went out beside what is coming.

### Calendar choice: FullCalendar 7

| | FullCalendar 7 (`@fullcalendar/react`) | react-big-calendar | SVAR React Calendar | react-smart-scheduler, trud-calendar |
| --- | --- | --- | --- | --- |
| Version, last release | 7.1.4 (core 7.1.5 on 2026-11-12) | 1.20.0, 2026-06-01 | 2.7.1, 2026-09 | 0.1.5; 1.0.1 |
| License | MIT (standard) | MIT | MIT core | MIT |
| GitHub | 20.8k stars, 1,084 open issues, releases about every two weeks | 8.8k stars, 129 open issues | 52 stars, no releases listed | 0 and 2 stars |
| React 19 | yes | yes | peer >= 18 | needs MUI (smart-scheduler) |
| Advisories | none | none | none | n/a |
| JS min+gzip | about 83 kB (day grid, time grid, interaction, theme, Temporal polyfill) + 5 kB CSS | 80 kB, 99 kB with drag | about 49 kB | not measured |
| Named time zones on UTC data | native (`timeZone="America/New_York"`) | none: browser-local Dates, needs a hand-made shift around DST | not checked | not checked |
| Removing borders | border colours are CSS variables | about 25 `!important` overrides | not spiked | not spiked |
| Accessibility (DOM dump) | labelled toolbar buttons, a tablist for views; events need `eventInteractive` to be focusable | focusable events, unlabelled toolbar buttons | not spiked | not spiked |
| 375px | week grid overflows: use list view on narrow screens | week grid overflows; 30-minute events clip their label | not spiked | not spiked |
| SSR in Next 15 | client-only via `next/dynamic`, build passes | same | | |

Recommendation: **FullCalendar 7**. It is the only candidate that handles a named publication time zone on UTC data, which is the heart of this feature; its theming is variables, not overrides; it is the most actively released. Costs and risks: about 83 kB gzip loaded only on the schedule page; v7 is new (most community answers are v6; plugins now import from `@fullcalendar/react/daygrid` etc.); events must be made focusable (`eventInteractive`); the list view is needed on phones. Premium FullCalendar plugins (resource timelines) are not needed. Spike: `spikes/scheduling-calendar/` (throwaway, fake data; screenshots were taken locally at 1440px and 375px in light and dark and are described in the PR, not committed).

## Newsroom: the schedule on an item

- **Card badge** on board cards: Lucide `CalendarClock` plus "Thu 13 Nov, 09:00" (publication zone). Overdue: `AlertTriangle` plus "Overdue". Blocked: `CircleSlash` plus "Blocked: newer version". Never colour alone.
- **Story drawer**, beside the existing Published/Not published state and Publish button: a "Scheduled for" row with the time, zone and who scheduled it, and buttons "Change time", "Suggest a time", "Unschedule". Unscheduled versions show "Schedule…" next to "Publish now".
- No AppSync subscription: the board and drawer read on open and after the editor's own action, as they do today.

## Announcements

### Through Caducus: yes

Ryan decided on 2026-11-12 that every notification goes through one Caducus setup (PPY-824c14). An announcement is a notification whose recipient is the publication's own public account instead of a person. Caducus already has what an announcement needs from a transport: an event id to dedupe on, a delivery log with a provider message id and a status that never moves backward, a `Channel` interface with Slack and Discord already planned, per-list approval, pacing, a dead-letter path and the site's own pause story. Building a second channel framework in Papyrus would be a second notification system, which is exactly what that decision rules out, and Bluesky, Mastodon, LinkedIn and Slack would each be built twice. So: a Caducus channel `x` (an adapter that posts and deletes), a new recipient class `broadcast` (the site's connected channel account, not a Person), and a cost field on deliveries for paid channels. Caducus is read-only from here: those three additions need a Caducus issue (`kanbus-`) and release before the Papyrus side can ship. Papyrus keeps what is editorial: eligibility, drafting, approval, budget and retirement.

One exception to Caducus's current secret rule: Caducus keeps runtime Slack and Discord tokens KMS-encrypted in its table. For X we follow the Papyrus standing rule instead: SSM SecureString per site and account. The X channel takes a token-provider interface, so the host decides where tokens live.

### What triggers an announcement

An announcement is drafted when a Story **becomes eligible**, which is the later of two events: its first publication (from `publish_alerts.py`, only `PublishResult.changed`, only the first publish; a new version of an already-announced Story does not re-announce) and its rating reaching the site's announcement floor (a rating often comes after publishing). Eligibility rules, all per-site settings in the Announcements admin page:

- **Minimum stars**: 1 to 5, never below the site's quality floor (PPY-0e8d66, default 3). Default for a new site: 5 (announcements are the most public thing we do). MoM: 5.
- **What may be announced**: Story types (Article, Post) and, optionally, sections. "Accepted research" (References) is listed as a later kind, off, because a Reference has no page of ours to link to on most sites.
- **Not already announced** on that account: the announcement id is deterministic, `<accountId>#<lineageId>`, written with a conditional put.
- **The site is opted in and not paused**, the account is connected and healthy, and the budget allows the next post.

Eligible but blocked (paused, over budget, account disconnected) is recorded with the reason, not dropped, and shown in the queue.

### Who writes the post

A model (GPT-6 Luna, the LLM default) drafts the post from the Story's title, dek and summary only, under the site's announcement voice rules held as guidelines-as-data (PPY-2a2a8a), so voice lives with the site's other guidelines. The draft must make no claim absent from the Story: the layered fact check (fact-checking standard) runs on the draft with the Story text as its only source, plus the rule lane of `papyrus editorial check`. X's own length rule applies (280 weighted characters; a link counts as 23 because X wraps every link). A draft that fails a check is not posted; it is shown with the failed check. Approval is a per-site setting: **required** (an editor approves or edits the text in the newsroom) or **automatic** (posted when the checks pass; editors can still withdraw, which deletes the post). MoM starts with **required**.

### Media, links, analytics

No media upload: X builds the link card from the page's Open Graph and Twitter tags, which every Story page already has (and `share_image_check.py` checks). That also drops the `media.write` scope. The link is the canonical page URL with `utm_source=x&utm_medium=social&utm_campaign=announcement` so GA4 attributes visits. No link shortener (X wraps links itself).

### Exactly once, retries, failures

X documents no idempotency key for creating posts. So the announcement row moves `approved → posting` with a conditional update carrying an attempt id before the request, and `posting → posted` with the post id after. On a clear failure (4xx other than rate limit) it goes to `failed` with X's message. On a rate limit it waits until X's `x-rate-limit-reset` header says. On an unknown outcome (timeout, 5xx), it does not post again blindly: it reads the account's most recent posts (one read, priced per post returned) for the announcement's link; found means `posted`, not found means retry. X's duplicate-content refusal is treated as "already posted" only after that read confirms it. States: drafted, awaiting approval, approved, posting, posted, failed, blocked (with reason), withdrawn.

### Retirement and corrections

Retiring a Story with a redirect deletes its announcement post ($0.010 per delete on the 2026-11 price list) and records "withdrawn: Story retired". A correction (a new version, usually with a revision note) leaves the post alone: the link now shows the corrected page and its history. If the post text itself repeats the corrected claim, the editor uses "Withdraw announcement" (delete) and may approve a new one. X's create-post API documents an edit option (`edit_options.previous_post_id`), but its eligibility rules (time window, edit count, account type) were not verified, so editing is not part of the first version.

### Audit trail

Every announcement row records the Story lineage and version, the account, the text (in S3; DynamoDB holds the key), who or what drafted and approved it and when, the post id and link, the cost charged, the state history and any error. The newsroom shows them on the Story drawer ("Announced on X by @account, 13 Nov 09:01, view post") and in an Announcements list on the admin page. When revision history is on (PPY-156614), a withdrawal for a retirement appears there as a note; posting does not (it is not a change to the article).

### Accounts and keys

- **How many**: one account per publication to start. Per-section accounts are a later setting (the account id is already part of the announcement key, so nothing changes shape).
- **Whose**: the site owner's. The owner creates an X developer app in their own X developer account (the owner pays X), and enters its client id and client secret once in the newsroom Administration area. The secret is written to SSM SecureString `/papyrus/<siteId>/announcements/x/client-secret` and never shown again. The IAM permission to that path prefix is in the plugin template; nothing is made by hand.
- **Connecting**: OAuth 2.0 Authorization Code with PKCE, confidential client. The owner clicks "Connect X account", signs in at X as the account to post from, approves, and returns to the newsroom. Pasted tokens are not offered: they put long-lived secrets in a clipboard and a chat window. Scopes: `tweet.write`, `tweet.read`, `users.read` (what posting requires) and `offline.access` (to refresh). No `media.write`.
- **Tokens**: the access token lasts two hours and is held only in memory for one post. The refresh token (single-use, rotating, about six months) is stored in SSM SecureString `/papyrus/<siteId>/announcements/x/<accountId>/refresh-token`; each refresh writes the new token first, under a per-account lock (a conditional DynamoDB lock row), because two concurrent refreshes make one fail. A failed refresh marks the account "Needs reconnecting" and pauses its announcements; nothing falls back to another account.
- **Revocation**: "Disconnect" calls X's revoke endpoint and deletes the parameter. Rotating the client secret is "Replace secret" (write only).
- **Labels**: X's rules (help pages could not be fetched by tool; search excerpts say automated accounts must show the automated label linked to a human-run account) are a checklist item the owner confirms before turning announcements on: "This account shows X's Automated label, managed by @owner".

### Cost control

Prices verified on docs.x.com/x-api/getting-started/pricing on 2026-11-12: create a post $0.015, create a post with a URL $0.200, delete $0.010, read $0.005 per item returned. Announcements always carry a link, so each costs $0.20.

- **Prices** are a per-site setting copied from that page with its date, because X does not return a price with each request and the price list will change. The admin page shows "Prices as of 12 Nov 2026" and links to the page.
- **Budget** is a per-site setting the owner must enter in their own currency amount per X billing cycle, with no default: the right number depends on the owner's wallet, not on us. The admin page suggests one: the site's own rate of Stories that met the announcement rules over its history (counted from the eligibility events, O(1) per event) times the post price, shown as "At your recent pace, about N posts and $X per month". On MoM today that is close to zero, which is the point Ryan wants to review.
- **Spend** is a counter row per account per billing cycle, incremented once per post or delete with the price used. Before posting, if counter plus price would pass the budget, the announcement is `blocked: budget reached` and the site's announcements pause with that reason shown at the top of the newsroom admin page and on the Announcements list. Nothing is dropped; raising the budget or the next cycle resumes. The X console's own spending limit is the owner's bill of record; the admin page tells the owner to set it, and shows X's daily usage counts (`GET /2/usage/tweets`) beside our counter so a mismatch is visible.
- **No pacing number.** Posting is immediate once eligible; spreading out is what scheduling is for.

### The pause switch and opt-in

Announcements are off for every site until an owner turns them on in Administration, after connecting an account, confirming the label and entering a budget. A "Pause announcements" switch sits at the top of the Announcements admin page and on the Announcements list, with the reason and who paused it. Paused means nothing is posted and new eligible Stories wait as "blocked: paused".

### Testing safely

X has no sandbox. MoM tests on a private (protected) test account owned by Ryan, connected as MoM's account, with the real pipeline and a small budget. Protected posts are seen only by approved followers. Once the posts look right, the owner disconnects the test account and connects the real one.

### CLI and MCP parity

One operation table (as `editorial_checks.OPERATIONS`) serves the console routes, the `papyrus` CLI and MCP: `schedule set|change|clear|suggest`, `schedule list --from --to`, `announcements list|show|approve|edit|withdraw|retry`, `announcements pause|resume`, `announcements settings show|set`, `announcements account status`. Connecting an account stays in the browser (OAuth needs it); the CLI prints the console link. Mutation commands write unless `--dry-run`, as the CLI does today.

## Relation to the newsletter

The newsletter is a separate send with its own approval and schedule. This plan reuses its scheduling pattern (same one-off schedule shape, a different name prefix and task), not its tables. When the newsletter converges into Caducus (PPY-824c14), announcements are already there.

## How could we screw this up?

| Failure | What prevents it |
| --- | --- |
| Posting about something retired, wrong or unreviewed | Eligibility is checked again at posting time (published, rated, not retired); approval required on MoM; retirement deletes the post. |
| Publishing text nobody reviewed because a newer version arrived | Schedules pin a version; a newer version blocks the publish and tells the editor. |
| Runaway spend | Owner-set budget, pause before passing it, visible counter, X console limit recommended, one post per Story per account by key. |
| Duplicate posts | Deterministic announcement id with conditional put; no blind retry on unknown outcomes. |
| Wrong account | One account per site; the drawer and admin page always name the account; announcement key includes it. |
| Leaked token | SSM SecureString only, written once, never returned by any route, never logged; revoke and replace from the admin page. |
| X suspends the account for automation | Automated label confirmed; one post per Story (no duplicates, no reposting); approval at first; posting volume is tiny. |
| Announcing low-quality items | Floor of 5 stars on MoM, never below the site floor; unrated never qualifies; predictions never qualify. |
| Time zone mistakes | UTC stored; the zone shown on every time; DST gaps refused and overlaps asked. |
| A scheduled publish silently missed | Retries, dead-letter alarm, "Overdue" badge from the index. |
| Model invents a claim in the post | Draft sourced only from the Story; fact check against the Story; failed checks are not posted. |

## Stories

1. PPY-085d0b **Scheduling model and publish-at-time execution** (backend). Blocked by PPY-271940.
2. PPY-92164e **Newsroom schedule field and badge.** Blocked by 1.
3. PPY-38f016 **Schedule calendar view** (FullCalendar). Blocked by 1.
4. PPY-9f4d66 **Announcement channel framework with the X adapter** (Caducus `x` channel, broadcast class, cost field; Papyrus wiring). Needs a Caducus issue.
5. PPY-2deb63 **X account connection and secure token handling.** Blocked by 4.
6. PPY-ae9d06 **Announcement eligibility rules and configuration UI.** Blocked by 4; relates to PPY-0e8d66.
7. PPY-64378c **Announcement text drafting with checks and approval.** Blocked by 6; relates to PPY-2a2a8a.
8. PPY-a326aa **Announcement audit trail.** Blocked by 4.
9. PPY-8037b8 **Cost, budget and pause controls.** Blocked by 4.
10. PPY-bf9d26 **Retirement and correction handling.** Blocked by 4.
11. PPY-24358c **CLI and MCP parity.** Blocked by 1 and 6.
12. PPY-3c5468 **p.apyr.us feature page** (task). Blocked by 3 and 9.
13. PPY-4007c8 **MoM rollout**: private test account first, 5 stars only. Blocked by all of the above.

The issue texts carry the Gherkin.

## Questions for Ryan (with recommendations)

1. How many X accounts to start? One per publication (MoM's own); per-section accounts later.
2. The announcement floor on MoM: 5 stars to start, as you said; we review after a month of data.
3. Should a person approve each post's text at first? Yes on MoM, until a run of drafts needs no edits; then switch to automatic (withdrawal stays available).
4. Monthly budget for MoM: your call; at $0.20 per post and today's rate it is cents. I suggest $10 per billing cycle as MoM's entered setting, and the same as X's console limit.
5. Test account: a protected X account you own, connected to MoM first.
6. Should References (accepted research) ever be announced? Not now; only Stories.
7. Whose X developer app: the site owner's (yours for MoM), so each site pays its own X bill.
