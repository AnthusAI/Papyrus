# Announcement and Delivery records

Status: records, indexes and relation types merged to `develop` (PPY-3792dd, slice 1 of epic PPY-a36492); cloud only, nothing is wired to send. Design: `~/Projects/papyrus-announcement-delivery-design.md` sections 2, 2.1, 2.2 and 13.

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

The attempt log and the `started` and `unknown` outcomes (PPY-a570e8), durable triggers (PPY-e3bb2b), X on the new records (PPY-efd06c), the review policy (PPY-97c0f2), text versions and pinned edits (PPY-e8ec54), and the console. Nothing sends.
