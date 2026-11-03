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

## In the newsroom: side by side

`components/story-variations.tsx`, read through `components/story-variations-client.ts` (the API) and `lib/story-variations.ts` (the pure parts). It shows in three places, all the same
component: the **Story detail** (the article editor, under the idea's own Accept and Reject), the **Stories board's card detail** (the same editor, embedded), and each idea of the
**Needs me idea batch** (a "3 variations" button under the idea opens them in place).

Each variation is one card: its **point** first, then headline, deck, **what it connects to** (each connection a link: a Reference, a Story or a concept, with how it is connected), the
point check's verdict, the body behind a "Read the body" button, a "Why? (optional)" box and **Accept** and **Reject**. Cards sit side by side on a wide pane and stack in one column on a phone.
Accept and Reject are words with Lucide icons and so are the states (On offer, Accepted, Rejected), never colour alone; there are no dropdowns and no outlines (flat rounded backgrounds from the
feed tones). With one variation the card says "Only one way to connect this was found"; with none nothing shows.

**Accept** makes that wording the Story's next version, then records the decision. In the editor it saves a new version (`saveItemDraft` with `newVersion`, the same action as "Save as new
version") whose front matter has `title` set to the variation's headline, `deck` to its deck (unchanged when it has none), the body replaced by its body (unchanged when it has none) and
**`variationId`** set to the variation's id; the change reason reads "Accepted variation 2: &lt;point&gt;". Every other front matter line and comment is kept. From the Needs me batch the same
version is saved from the Story's latest version. If the version cannot be saved the variation is **not** recorded as accepted and the card says so. With unsaved edits in the editor, Accept is
disabled with the reason, so no edit is lost. `papyrus_content.story_variations.variation_id_of` and `versions_from_variations` read it back: which version came from which variation.

**Accepting a second variation:** the simplest rule, and the one the model already had. A Story has one accepted wording at a time, so accepting another makes **another version** with that
wording and puts the earlier variation back **on offer** (it can be accepted again; its wording stays in the version history, where its `variationId` still points at it). Nothing is deleted.

**Reject** records the decision and the reason (optional) and changes nothing on the Story. A rejected variation can still be accepted later.

The idea's own Accept and Reject (move it forward, or to Spiked) is separate from accepting a variation: choosing a wording does not move the idea.

**Tenants.** `StoryVariation` is not a tenant model, so reading and writing it needs no stamping: the rows are keyed by the Story's lineage id and the newsroom reads them through the site's own
API. The new version is written by the content-actions Lambda, which has `PAPYRUS_TENANT_ID` (Machines on Machines: `machines-on-machines`), and `save_story_version` keeps the `tenantId` of the version
before it (`features_backend/story-variations-accept.feature`). Editors write the variation decision through the API (`updateStoryVariation`, group `editor` or `admin`).

Specs: `features/newsroom-story-variations.feature` (a real browser against fixtures: `npm run test:story-variations`), `features_backend/story-variations-accept.feature`, `scripts/test-story-variations.ts`.
The local preview (`npm run dev:preview`) has sample variations on the board's second idea (three), on `Draft in progress: the last ferry crossing` (one) and on the Needs me sample batch.
Documented for readers at p.apyr.us under PPY-656e1d.

## What this does not do yet

The Story's conversation agent (a requested variation that combines others, with `origin: requested`) is PPY-73f557 and waits for Chatticus: nothing here adds a conversation.
