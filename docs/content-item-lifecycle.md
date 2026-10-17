# One content item, one lifecycle

Kanbus: initiative `PPY-ad3da5`, milestone `PPY-b73600`. Decided by Ryan on
2026-10-17.

## The problem

Today one piece of content changes record type as it moves through the
newsroom:

| Stage | Record today |
| --- | --- |
| Idea / charter | pod Kanbus `story`, or an `Edition`/`EditionSlot` plan |
| Research | `Assignment` `research.*` + `Message` `research_packet` |
| Reporting | a second `Assignment` `reporting.*` + `Message` `reporting_context_packet` |
| Editor selection | `AssignmentEvent` `reporting_select` / `reporting_brief` / `reporting_merge` |
| Copywriting | a third `Assignment` `copywriting.article-draft` or `copywriting.brief-draft` |
| Draft copy | a new `Item` lineage (`type` `article` or `brief`) |
| Publication | `PublishedItem`, then `EditionItem` placement |

These records are joined only by `derived_from` and `produces`
`SemanticRelation` chains. `lib/reporting-story-budget.ts` is the one place
that walks the chain back together. A reporting packet can produce more than
one copywriting Assignment, and therefore more than one `Item` lineage
(`select` and `brief` on the same packet, or a select on each rerun). A
`merge` lets many stories feed one Item. The local pod is the opposite case:
one Kanbus `story` carries the whole lifecycle as files, but Papyrus never
maps it to an `Item`.

For a person or an agent the question "where is this story now?" has no single
answer, and the Board can only show three unrelated kinds of card.

## The model

**The content item is the `Item` lineage.** It is created at the idea stage
and keeps its `lineageId` through publication. Every stage below is a value of
one lifecycle field on that lineage, not a new record type:

```
idea → assignment → research → report → editor_select → copywriting → published
```

This is the stage vocabulary the pod story workflow already uses, so the local
and cloud backends describe the same thing.

- **Lifecycle stage is separate from version state.** `Item.versionState`
  (`draft`, `current`, `superseded`) and `PublishedItem` keep their meaning:
  they version the copy. A new `Item.stage` field holds the lifecycle stage.
- **Work attaches to the content item.** Research, reporting and copywriting
  stay as `Assignment` records, because they are work done by agents and people
  with claims, retries and audit events. Each one carries the content item's
  `itemLineageId`. An Assignment is never a second piece of content.
- **Packets attach to the content item.** Research and reporting packet
  `Message` records stay private work products, linked to the item through
  their Assignment.
- **Format is an attribute, not a type.** Brief versus full article becomes a
  format on the item (`Item.metadata.format` or a dedicated field), chosen at
  editor selection. `select` and `brief` move the same item to `copywriting`
  with a format; they do not mint a new lineage.
- **One idea becoming two pieces is an explicit split.** A split creates a new
  content item with a `derived_from` relation to the original. Combining two
  ideas is an explicit merge that retires one lineage into the other. Neither
  creates a parent/child hierarchy of content types.
- **Edition placement is unchanged.** `EditionItem` still places a published
  item in an edition; it is layout, not lifecycle.

## The configurable name

Editors see one noun for the content item, set per publication:

```ts
contentItemName: { singular: "Story", plural: "Stories" }
```

It is a required `SiteBrand` field. Every surface that names the content item
reads it: Newsroom navigation, the Board, Assignment views, operator CLI
output and agent skills. Stored data, GraphQL models and code paths are
identical whatever the noun is. Code uses the neutral term *content item*.

The layout `PublicationItemType` union (`article`, `brief`, `promo`, `ad`,
`correction`, `sectionHeader`) is a rendering format and is not the content
item name.

## Delivery order

1. **Name and design.** `SiteBrand.contentItemName`, Newsroom navigation reads
   it, this document. (First PR.)
2. **Lineage at creation.** Add `Item.stage` and `Assignment.itemLineageId`
   with indexes. Edition planning, Coverage Theme dispatch and
   `create_research_assignment` / `create_reporting_assignment` create or
   reuse the content item and stamp its lineage on every Assignment.
3. **Selection and copywriting keep the lineage.** `reporting_packet_review`
   moves the item to `copywriting` with a format instead of minting a new
   copywriting identity; `copywriting.py` writes the next draft version on the
   inherited lineage. The TypeScript plan in
   `components/topic-steering-workspace.tsx` follows the same contract. `merge`
   becomes the explicit merge operation; split is added.
4. **Board by stage.** `lib/newsroom-board.ts` projects one card per content
   item in the column for its stage, with its Assignments as work on the card.
   `lib/reporting-story-budget.ts` relation walking is replaced by a lineage
   query.
5. **Local pod parity.** The local backend maps a pod story to a content item
   and its workflow status to `stage`, so `papyrus` lists the same thing on
   both backends.
6. **Retire the legacy path.** The `Item` `type="assignment"` path in
   `src/papyrus_newsroom/newsroom.py` is removed.

Per AGENTS.md there is no compatibility layer: existing in-flight Assignments
and draft Items are migrated by a one-time script, not read through dual
shapes.

## Out of scope for now

Board write actions (status transitions `PPY-caf6e5`, drag-to-publish
`PPY-86eda3`) stay deferred. The Board remains read-only.
