# Scheduled publishing

An editor pins one version of a Story to a moment. At that moment the site publishes exactly that version, once, by the normal publish path. This is the backend (PPY-085d0b, epic PPY-09ee86; design: `docs/plans/scheduled-publishing-and-announcements.md`). The newsroom field and badge (PPY-92164e) and the calendar (PPY-38f016) build on it; nothing here draws a screen.

## Turning it on

Set the publication's time zone in the site's backend settings and deploy:

```ts
publication: { kind: "s3-projection", timeZone: "America/New_York" }
```

`timeZone` is an IANA name. Without it the site answers every schedule request with `scheduling-off` and the deploy wires nothing. It needs the S3 projection publication. The deploy (`amplify/publication/scheduled-publishing.ts`, tested by `scripts/test-scheduled-publishing.ts`) adds, in the content-actions function's own stack:

| Resource | Why |
| --- | --- |
| A role EventBridge Scheduler assumes (this account only) | It may invoke content-actions and send undeliverable events to the dead letter queue, nothing else. |
| An SQS dead letter queue (14 days, encrypted) and an alarm on it | An event Scheduler cannot deliver waits there; the alarm raises when a message is visible. No alarm action: the account's operator listener reads every alarm. |
| IAM on the function: `scheduler:CreateSchedule`, `UpdateSchedule`, `DeleteSchedule` on `schedule/default/papyrus-pub-<siteId>-*`, and `iam:PassRole` for that role to Scheduler only | The function manages only its own schedules. |
| Settings on the function: `PAPYRUS_PUBLICATION_TIME_ZONE`, `PAPYRUS_SCHEDULER_ROLE_ARN`, `PAPYRUS_SCHEDULER_DEAD_LETTER_ARN`, `PAPYRUS_SCHEDULE_NAME_PREFIX` | The function's own ARN comes from the invocation, because a setting naming itself would be a circular reference. |

`<siteId>` is the brand id (at most 35 characters, lowercase letters, digits, hyphens).

## What is stored

On the Item row of the version being scheduled (`amplify/data/schema.ts`):

| Field | Meaning |
| --- | --- |
| `scheduledPublishAt` | The UTC instant to publish at. |
| `scheduledBy` | Who scheduled it (the person's user name; the version's `versionPublishedBy` becomes `scheduled by <scheduledBy>`). |
| `scheduledAt` | When the schedule was set. |
| `scheduleState` | `scheduled`, `publishing` or `blocked`. Present only while a schedule exists, so the index stays sparse. |
| `scheduleName` | The EventBridge Scheduler schedule: `papyrus-pub-<siteId>-<16 hex of a digest of the version id>`. (The plan said the first 8 characters of the id; version ids share long prefixes, so a digest names them.) |

One new index on Item, `scheduleState` + `scheduledPublishAt` (`listItemsByScheduleStateAndScheduledPublishAt`). Item had nine indexes; this is the tenth and the only index in its deploy (DynamoDB adds one global secondary index per table per update). A time range of schedules is one index query per state; nothing reads the table. A new version never inherits its predecessor's schedule (`save_story_version` leaves the five fields out of the copy).

A Story has one schedule. Scheduling the newest version replaces the schedule of an earlier version. Only the newest version of a Story can be scheduled, and only Stories (not wiki pages or checklist steps; an untyped Story must be given a type first).

## Time zones

Only the UTC instant is stored. `schedule --at` takes:

* a time with an offset or `Z` (`2026-11-13T09:00:00-05:00`): exactly that instant;
* a time without one (`2026-11-13 09:00`): a wall-clock time in the publication's zone.

A wall-clock time the zone skips (8 March 2026, 02:30 in New York) is refused: `That time does not exist on 8 March in New York. Pick another time.` A time the zone repeats (1 November 2026, 01:30) is refused with both choices (`01:30 EDT`, `01:30 EST`, each with its UTC instant under `choices`); the caller answers by typing the offset. A time that has passed is refused with `That time has passed.` Responses carry `local` (ISO with offset), `label` (`Fri 13 Nov 2026, 09:00 EST`) and `zone` beside the UTC time.

## The run at the scheduled time

Each scheduled version has one one-off Scheduler schedule (`at()` in UTC, flexible window off, deleted by the service after it runs) that delivers `{"projectionTask": {"task": "publish-scheduled", "itemId", "scheduledPublishAt"}}` to content-actions. The timer is created first and the row written second: a timer without a row fires and finds nothing, a row without a timer would never fire. Rescheduling updates the same timer.

1. **Claim.** A conditional update on the row: `scheduleState = scheduled AND scheduledPublishAt = <the time in the event>` to `publishing`. A duplicate event, or a late event for a time the editor has since changed, fails the condition and stops without changing anything.
2. **Pinned version.** If a newer version of the Story exists, nothing is published. The row becomes `blocked`, which reads "A newer version was saved after this was scheduled. Schedule it again.", and a flag review request (raised by `scheduled-publishing`) tells the site's editors in the Notification Center. Versions are immutable, so there is no content hash to compare.
3. **Publish.** `publish_item_action` runs as `scheduled by <scheduledBy>` with that person's approval (a schedule set by a signed-in person is their approval; a site that requires approval to publish refuses a schedule from a caller who is not one, as it refuses their publish). It is the normal path: the page checks, the first `publishedAt` kept (#1455), `versionPublishedAt` = the moment it went live, the projection job, the site triggers.
4. **End.** The schedule fields are removed and the timer deleted.

If the publish is refused (an open checklist, a page the site cannot render), the claim is handed back (`scheduled`), the run fails so Lambda retries it and then sends it to the function's failure destination, and the version shows as overdue. A run that dies mid-publish (a timeout) leaves `publishing`, also shown as overdue; nothing publishes it behind the editor's back.

## Overdue, missed schedules and the dead letter queue

`overdue` is derived, not stored: a version whose `scheduledPublishAt` has passed while it is still `scheduled` or `publishing`. Events Scheduler cannot deliver go to the dead letter queue and raise its alarm. There is no sweeper that publishes late work: the editor decides (publish now, or schedule again).

## Publish now, take down, retire

* `publishItem` removes the schedules of the published version and of every older version of the Story (a schedule on a newer version stays). The answer carries `schedule.removed`. If removing fails the publish still happens and the answer says so (`schedule.error`); the leftover timer then finds its version already published and does nothing.
* `unpublishItem` removes every schedule of the Story.
* `papyrus stories retire` removes the Story's schedules first (through the same mutation) and stops before changing anything if it cannot. A dry run lists the `unschedule` step.
* A publish made by the operator lane's local `ops content publish` (no content-actions function) cannot delete the timer; the version's fields remain until the timer fires, when the version is found published and the schedule is cleared.

## One operation table

`story_schedule.OPERATIONS` has two operations. The `scheduleItem` mutation (content-actions, authorised like `publishItem`: editors and admins), `papyrus stories schedule` / `stories schedule-list` and the MCP tools `stories_schedule` / `stories_schedule_list` all run them, so they refuse in the same words.

| Operation | Input | Answer |
| --- | --- | --- |
| `schedule` | `storyLineageId` or `itemId`; `at` or `clear`; `dryRun` | `{ok, scheduled, itemId, versionNumber, scheduledPublishAt, local, label, zone, scheduledBy, replaced, notes}` or `{ok, cleared, itemIds}` |
| `schedule_list` | `storyLineageId`, or `from` / `to`; `states` (`scheduled`, `publishing`, `blocked`, `overdue`) | `{ok, timeZone, now, schedules: [{itemId, lineageId, versionNumber, title, state, storedState, scheduledPublishAt, local, label, scheduledBy, scheduledAt, message}]}` |

A refusal is `{ok: false, errors: [{code, message, ...}]}`. Codes: `not-allowed`, `scheduling-off`, `scheduling-misconfigured`, `nonexistent-time`, `ambiguous-time`, `time-passed`, `bad-time`, `not-newest`, `not-a-story`, `type-required`, `not-scheduled`, `publishing`, `approval-required`, `bad-input`. `not-allowed` ("You can't publish on this site, so you can't schedule.") is checked on the caller's groups, the same as `publishItem`'s. An unrated Story schedules with the note "Unrated: it will publish but will not be listed or announced until it is rated."

## What the interface stories read

* The board badge and drawer (PPY-92164e): one `schedule_list` call with `storyLineageId`, or the row's `scheduleState`, `scheduledPublishAt`, `scheduledBy` on the version; `state` already says `overdue`, `blocked` carries its message, and `label` and `zone` are the publication-zone text.
* The calendar (PPY-38f016): `schedule_list` with `from` and `to` (the index range); published items in the same range come from the existing `publishedAt` indexes. Drag to reschedule calls `schedule` with the new `at`.
* Times are for the interface to format; the backend never sends a browser-zone time.

## Not built here

The editors' notice uses a flag review request. The plan's Caducus operator-class kind waits for the notifications convergence (PPY-824c14). Slot suggestion ("Next suggested time") belongs to the field story. Announcements are separate stories.
