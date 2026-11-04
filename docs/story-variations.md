# Story variations

A new item could connect to what the newsroom knows in more than one way: to another Reference, to another Story, to a Concept. A `StoryVariation` is one of those ways, with
its own point, wording and connections. An editor sees them side by side and chooses.

A variation is not a version. Versions (`Item.lineageId`, `versionNumber`) are a Story's one line of edits. Variations are alternatives that exist at the same time, and the
Story's version history carries on from the one an editor accepts.

## The record

| Field | Meaning |
| --- | --- |
| `storyLineageId` | The Story, as an Item lineage. Variations are read with `listStoryVariationsByStoryAndNumber`. |
| `variationNumber` | Its place in the order offered, from 1. |
| `status` | `offered`, `accepted` or `rejected`. A Story has one accepted variation at a time; accepting another puts the earlier one back on offer. |
| `point` | What this variation claims that a reader could not get from the source alone. Required: a Story with nothing to add gets no variation. |
| `headline`, `deck`, `bodyMarkus`, `section` | The wording. |
| `connections` | JSON list of `{kind, id, title, how}`, where `kind` is `reference`, `story` or `concept`. Required unless a person wrote the variation. |
| `origin` | `generated` by an idea run, `requested` in the Story's conversation, or written by a `person`. |
| `basedOnVariationIds`, `requestMessageId` | For a requested variation: the variations it combines, and the Message that asked. |
| `pointCheck` | The "so what" check's verdict (`ideas/point_check.py`). |
| `decidedBySub`, `decidedByLabel`, `decidedAt`, `decisionReason` | The latest decision. |

Nothing is deleted: the model has no delete access, and an editor rejects with a reason, so what was turned down and why stays readable by people and by the Story's conversation.

`papyrus_content.story_variations` has `offer_variation`, `variations_of` and `decide_variation`. Specs: `features_backend/story-variations.feature`.

## Offered by idea runs

When an idea run files an idea it also offers variations of it (`papyrus_content/ideas/variations.py`, called from `ideas/monitor_stories.py` right after the idea is filed). They are
the real ways to connect the same item to what the newsroom knows, and no others:

| Connection | Found from |
| --- | --- |
| `reference` | Another accepted Reference related to this one: a link people confirmed, or a close match as close as the site's typical nearest neighbour (the same neighbours the idea writer is shown). |
| `story` | Another Story, at any stage after Idea and not spiked, that rests on one of those Reference (`uses_evidence`) or is tagged with a concept the Reference has. |
| `concept` | A concept the Reference carries (`mentions` or `related_to`), including the hashtags editors typed, editors' tags first. |

How it works:

1. **Variation 1 is the idea as filed**, with the point it passed on and the connections it rests on (the related Reference it cites; or the source Reference itself when it rests
   only on what editors said). It is written without a model call, so a Reference with no other connection ends with exactly one variation and the writer is not asked anything.
2. Every other connection the idea does not already rest on is an *option*. One model call (the run's own, `gpt-6-luna`) writes a version for each option: its point, headline, dek and
   body, built on that option. The prompt is the idea writer's rules plus two handles only this writer sees (`S` for a Story, `C` for a concept). An empty `point` is a good answer and
   offers nothing for that option.
3. Each version must pass what the idea passed: the citation rules, the "more than a summary" rules (`connections.standard_problems`), its dek and a body sentence must cite its own option,
   it must not repeat the idea's or another version's headline or point, and then `point_check.judge` (the same judge, failing closed). A version that fails is not offered, and the
   run record says why.
4. There is **no count**. What stops it is a real constraint: the run's cost limit (`--max-cost-usd`, shared with the idea runs), a prompt too large for the model (the last options are
   left out and counted in `optionsDropped`), or a failing write.
5. **The idea is never lost.** The pass runs after the idea is filed. A failure is recorded in `variationErrors`; the same error twice in a row (a missing grant, a backend without the model)
   is systemic, so the pass turns itself off for the rest of the run (`variationsDisabled`) instead of paying for versions it cannot keep.
6. **Idempotent.** A Story that already has generated variations is left alone (`skipped: already_offered`), and `offer_variation` is itself idempotent on the wording. A dry run asks and
   checks (and pays) but writes nothing: the run record lists what would have been offered.

### In the run record

`run["variations"]` has one line per idea: `offered` (id, number, anchor, headline, point), `dropped` (anchor, reason: `no_point_offered`, `point_check_failed` with `failures`,
`anchor_not_cited`, `citation_check_failed`, `repeats_another_variation`, `refused`, `write_failed`, `not_answered`), `options` (what the writer was asked about), `costUsd`, and
`skipped` (`cost`, `time`, `input_too_large`, `already_offered`, `disabled`). The totals are `variationsOffered` and `variationCost` (`calls`, `costUsd`). The variation calls are also in
`modelCalls` and `usage`, so the run's total and the existing cost meter include them, and the router's per-publication line carries `variationsOffered` and `variationCostUsd`.
Every verdict is in `pointChecks` (with `variation` set to the option's handle).

### What it needs deployed

* **Router change set.** `RouterIdeaPolicy` in `infra/monitoring/papyrus-monitoring.yaml` gets two grants on any publication API, `Query listStoryVariationsByStoryAndNumber`
  and `Mutation createStoryVariation` (read first so a rerun adds nothing, then create; never update or delete). Like every change to that template it is applied by hand with a
  change set; the router code release carries the new module (the zip is built from the import closure).
* **The `StoryVariation` model on each site's backend.** It is in the `variations` optional model group (`amplify/data/schema.ts`), which is **on by default**. A site needs a backend
  release from 5.73.0 on, and no site setting, unless its `papyrus.config.ts` lists `"variations"` in `backend.excludeModelGroups` (then remove it). Without the model the first write fails, the
  pass turns itself off after two failures and the ideas are filed as before.
* **Multi-tenant backends.** `StoryVariation` is not a tenant model: rows are keyed by the Story's lineage id, which is already the tenant's own Item, so a router client built with
  `tenantId` (Machines on Machines: `machines-on-machines`) creates and lists them with no stamping (`features_backend/idea-variations.feature`, last scenario).

## What this does not do yet

The side-by-side view and carrying an accepted variation onto the Story are PPY-9e7a4a. The Story's conversation agent (a requested variation that combines others) is PPY-73f557 and waits
for Chatticus. Pack ideas (themes joining several References) are filed as before, with no variations.
