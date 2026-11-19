# Announcements learn from a person's edits

When a person rewrites how something is announced, later announcements change, and never silently. Design: [always-on agents architecture](design/always-on-agents-architecture.md), epic O (PPY-f51641), sections 16.1 to 16.7. The records are the Deliveries of [announcement records](announcement-records.md).

Three layers, each needing a person:

| Layer | What it is | How it starts | Effect on the drafter |
| --- | --- | --- | --- |
| Candidate | An edit with no scope chosen | `announcements example DELIVERY` with no scope | None. Listed for an admin. |
| Example | An edit a person gave a scope wider than "just this one" | `announcements example DELIVERY --scope channel` | Loaded for that scope, newest first. |
| Guideline | A guideline file with `learnedFrom` naming the Deliveries | Proposed by the learner, accepted by an admin | Read like any guideline. |

## Recording an edit (slice O1, PPY-627bbc)

`delivery_examples.Examples.record` writes a few short fields on the Delivery, once:

- `machineVersion`: the machine's draft the person worked from (the newest machine-owned version at or before the final one).
- the final version is not stored: it is the version that went out (the newest sent attempt's `version`) or the `preferredVersion` a person saved after it. The difference between the two stored versions is computed when needed, never stored again.
- `exampleScope`: `this_one`, `channel`, `kind` (this kind of Announcement on this channel) or `publication`; `exampleState`: `candidate`, `active`, `declined` (a person chose "just this one"); `exampleAt`.
- `exampleKey`: the partition an active example is read from (`publication`, `channel:<channel>`, `kind:<channel>:<kind>`), present only while the example is active, so the drafter reads examples through one sparse index and never scans.
- the person's one-line reason is the Delivery's S3 file `reason`; the catalog row never holds it. A reason goes with a scope.

Rules: only a person records (an agent is told `human_required`); a Delivery that has not gone out and has no preferred version has nothing to record; an unedited send records nothing (no block of the final version is a person's); recording the same answer twice changes nothing; a candidate or a declined edit is given a scope by recording again; an active example is not recorded again with another scope until it is turned off.

Operation: `announcements_example` (`papyrus announcements example DELIVERY [--scope S] [--reason TEXT]`). Specs: `delivery-edit-capture.feature`, `delivery_examples_test.py`.
