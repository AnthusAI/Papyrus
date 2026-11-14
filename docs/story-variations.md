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

## What this does not do yet

Nothing writes variations yet, and no page shows them. Writing them from idea runs, the side-by-side view, carrying an accepted variation onto the Story, and the Story's
conversation agent are separate tickets under the epic.
