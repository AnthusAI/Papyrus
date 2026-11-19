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

## A preferred version: teach without sending again (slice O2, PPY-75a314)

After a Delivery went out (or while an attempt is open) a person saves how it should have read as the next version, flagged `preferred` and named in `preferredVersion`. It is never sent and
changes no public text (the version that went out stays `sendable`, the state stays `sent`, no attempt is added). `announcements_preferred` (`papyrus announcements preferred DELIVERY --replaces N --text T [--scope S] [--reason R]`)
saves it and, when a scope is given, records the example in the same step; with none it is a candidate. A person only: an agent is told `human_required`, and a machine's redraft of a sent Delivery is refused. A save names the version it replaces
like every save (`stale_version`), and a Delivery that has not gone out has no preferred version (`constraint_conflict`: edit it).

**Teaching and correcting are separate choices.** Saving a preferred version corrects nothing. To also correct the public post a person runs `papyrus announcements correct` with the words, which makes the superseding Delivery
where the channel can delete the old post ([correction](announcement-records.md)); the example on the old Delivery stays.

Specs: `delivery-preferred-version.feature`.

## Examples reach the drafter, and every draft names what it read (slice O3, PPY-d99bd0)

`learned_examples.load(deliveries, channel=, kind=, budget=)` reads the **active** examples for the draft: the partitions `publication`, `channel:<channel>` and `kind:<channel>:<kind>` of the sparse
index `listDeliveriesByExampleKeyAndExampleAt` (`deliveriesByExample`), merged newest first, until the character budget (the context pack's default, `DEFAULT_MAX_CHARACTERS`) is spent; older
ones are left out and counted (`dropped`). Each is the machine's version beside the person's and, when given, the reason (S3 file `reason`). It goes into the drafter's prompt after the guidelines, so a
guideline still outranks an example. Nothing is scanned: `exampleKey` is cleared by `Examples.stop(..., OFF | ABSORBED, by=, why=)`, so an example a person turned off, or one an accepted guideline was
made from (absorbed, slice O4), is no longer in the index and is not loaded. A candidate and a "just this one" never had a key.

Each draft records what it read in the `inputs` line of its checks (`x_announce.inputs_of`): the guideline layers (scope, item id, version, content hash) and the example Deliveries. A blocked draft is
drafted again when the Story, the guidelines or the examples change. `papyrus announcements explain --delivery DELIVERY` prints it (`explain.explain_delivery`), with whether each example is still on.

The index is its own schema change: it ships in a release of its own.

Specs: `drafter-examples.feature`, `learned_examples_test.py`.
