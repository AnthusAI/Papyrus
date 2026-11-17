# Announcement and Delivery records

Status: records, indexes and relation types (PPY-3792dd, slice 1 of epic PPY-a36492) and the attempt log (PPY-a570e8, slice 2) merged to `develop`; cloud only, nothing is wired to send. Design: `~/Projects/papyrus-announcement-delivery-design.md` sections 2, 2.1, 2.2 and 13.

Two records replace "one row for each announcement on each channel":

- An **Announcement** (model `AnnouncementDecision`) is the decision to say something about one or more Stories. It has a once-only key, a kind, a release time and a state. It knows nothing about channels, holds no approval and no words.
- A **Delivery** (model `Delivery`) is one channel's version of that decision: the account, the words and picture (files in S3), the approval it runs under, every wait as a named time, the attempts and the address of the result.

The model is named `AnnouncementDecision` because the model `Announcement` is the X row shape built for PPY-09ee86 and deployed to the sites; the X rewire (PPY-efd06c) deletes it. See [announcements](announcements.md).

## The rules

- **Decided once.** An Announcement's id is made from its once-only key (`story-published:<lineage>`, `roundup:<list>:<yyyy-ww>`, `correction:<lineage>:<version>`) and the row is created with a condition on that id. The same Story published twice finds the first decision. The key is also an index, for reads from outside the writer.
- **Written together, finished on retry.** `Announcements.announce` writes the Announcement, then each Delivery and its words, then the `announces` relations. A crash anywhere leaves rows the same call completes. A decision with no Delivery writes nothing, so a publish that qualifies on no channel leaves no row. A plan that breaks a rule is refused before the first write.
- **One live Delivery for each Announcement, channel and account.** A Delivery's id is `<announcement>#<channel>#<account>#g<generation>`, created with a condition. A second Delivery for the same three is a correction: `Deliveries.supersede` writes the next generation with `supersedes`, marks the old one `superseded` with `supersededBy`, and writes the `supersedes` relation. AppSync has no transaction across writes, so these are three ordered conditional writes and a retry finishes them. The live Delivery of a channel and account is the highest generation.
- **Approval lives on the Delivery** (`approval`, `approvalPolicy`, `approvedVersion`, `approvedBy`, `approvedAt`). `none` is approved by `system` under the named policy. An approval names one version; a later version is not approved. The Announcement keeps only the decision and `releaseAt` (UTC; empty means now).
- **Every wait is a named time on the Delivery.** `releaseAt`, `lockAt` (equal to `releaseAt` with no separate lock), `nextAttemptAt` with `waitingFor` (`rate limit`, `budget cycle`, `release`). `dueAt` is the earliest still pending, and with `dueKey` it is present only while one is, so the due index is sparse. A lock is a fact (`lockedAt`, `lockedVersion`); nothing holds it.
- **No text in the catalog.** A Delivery row holds `textKey`, `imageKey` and `contentHash`. The words are one file in S3 (a ModelAttachment, owner kind `delivery`, role `delivery_text`). `records.require_catalog_only` refuses a row that carries post text, HTML or Markus.
- **A change to a row is conditional on its `revision`**, so two writers never silently overwrite each other; the second is told the row changed (`Conflict`).

## Attempts

A retry is an attempt. A Delivery's `attempts` field is a log that only grows; each entry has `number`, `at`, `eventId`, `outcome`, `code` (the provider's code) and, once closed, `closedAt`. Code: `attempts.py`; specs `delivery-a-retry-is-an-attempt.feature`, `delivery-attempt-written-before-the-call.feature`, `delivery-attempt-opening-guard.feature`, `delivery-one-consumer-per-account.feature`.

- **One event for each attempt.** Attempt N is the Caducus event `delivery:<deliveryId>:a<N>` (`records.attempt_event_id`). Caducus dedupes on the event id, so the same attempt handed over twice posts once, and a retry is a new event. The old `:r<round>` suffix belongs to the X row shape and goes with it when X moves onto Deliveries (PPY-efd06c).
- **Written before the call.** `Attempts.open` writes the entry as `started` and moves the Delivery to `sending` in one write conditional on the row's `revision`; only then is the provider called. An entry closes `sent`, `refused` or `unknown` (the always-on standard's words). A `sent` or `refused` entry never changes; `unknown` closes once to one of those.
- **Settled, never timed out.** An entry left `started` or `unknown` is settled by reading Caducus's record of its event id (`Attempts.settle`). A record that says how it ended closes the entry. With no record the same event id is handed over again (Caducus dedupes, so no second post). With a record still queued nothing changes: no clock decides. Until then the list reads "Outcome unknown" (`attempts.shown`). A second attempt does not open while one has no answer.
- **A wait ends an attempt.** A pause closes it `refused` with code `paused` and the Delivery is `blocked` until a person resumes it. A budget stop closes it `refused` with code `budget reached`: `blocked`, with `waitingFor` `budget cycle` and `nextAttemptAt` when the cycle begins. A rate limit closes it `refused` with code `rate limit`: `ready`, with `waitingFor` `rate limit` and `nextAttemptAt`, which must name a time. `dueAt` follows `nextAttemptAt`. The next try is the next attempt. After the first attempt the release and lock times are used up and stop being pending.
- **No invented retry count.** A sequence ends on a clear answer: `sent`, a provider refusal (the Delivery is `failed` until a person tries it again), or the read that shows whether the post exists after an unknown outcome.
- **The guard when an attempt opens.** The Delivery must be the highest generation of its Announcement, channel and account, must not be superseded, and its words file must exist and match the row's content hash. Otherwise nothing is sent and one flag (subject type `delivery`) is raised, once for each Delivery and reason. A Delivery that is only waiting (not due, not approved, already sent) raises no flag. `releasable` still reads only the row.
- **Closing never revives.** A close applies to the row as it is now (it re-reads after a conflict). If the Delivery was superseded while its attempt was open, the outcome goes in the log, the provider's facts (`providerId`, `cost`) are recorded, and the state stays `superseded`.
- **A Delivery with an open attempt is not corrected** (`OpenAttempt`): settle it first.
- **One worker for each channel account, for every channel.** All attempts for one channel account pass through one `AccountWorker`, which refuses a Delivery of another account. The queue that gives it a single consumer belongs to each channel's infrastructure and arrives with the channel (X: PPY-efd06c).

Caducus needs no change to accept the id shape (its event id is any non-empty text it dedupes on); it has its own spec for `delivery:<id>:a<N>`.

## Reads: every one is an index or a get

| Read | Index |
| --- | --- |
| Announcement by once-only key | `listAnnouncementDecisionsByDedupeKeyAndCreatedAt` |
| Planned Announcements by release time (the calendar, the schedule) | `listAnnouncementDecisionsByStateAndReleaseAt` |
| An Announcement's Deliveries | `listDeliveriesByAnnouncementAndCreatedAt` |
| An account's Deliveries, newest first | `listDeliveriesByAccountKeyAndCreatedAt` (`<channel>#<account>`) |
| Deliveries that are due (sparse) | `listDeliveriesByDueKeyAndDueAt` |
| A Story's Announcements | the `announces` relation, `listSemanticRelationsByObjectState` (`item#<lineage>#current`, predicate `announces`) |
| Rows of one tenant | `listAnnouncementDecisionsByTenant`, `listDeliveriesByTenant` |

No subscriptions. The code is in `src/papyrus_content/announcements/` (`records.py`, `decisions.py`, `deliveries.py`, `links.py`); the specs are `features_backend/announcement-*.feature` and `delivery-*.feature`.

## Relation types

`announces` runs from an Announcement to a Story and names the version looked at; `supersedes` runs from a Delivery to the Delivery it corrects. Both are in `papyrus-semantic-relation-types.yml`.

## Not in this slice

The channel transport for X and the queue with one consumer for each account, the "Outcome unknown" mark in the list, durable triggers (PPY-e3bb2b), X on the new records (PPY-efd06c), the review policy (PPY-97c0f2), text versions and pinned edits (PPY-e8ec54), and the console. Nothing sends.
