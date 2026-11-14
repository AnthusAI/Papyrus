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
idea → assignment → reporting → copywriting → illustration → typesetting → published
```

`held` (a finished story kept for later) and `spiked` (a killed story) sit
after `published`. The stories board
shows **Idea** as its first column, before Reporting: stories that a machine
generated and stories that a person started share the stage, and each Idea card
carries a labelled marker ("Generated" or "Started by a person") so an editor
can tell them apart. Every idea the pipeline generates (monitor stories, Cited Trends, synthesized ideas) is an Item at this stage, never a Proposal; an editor accepts one by moving it forward and declines it by moving it to `spiked` with a reason ([idea-pipeline.md](idea-pipeline.md)). Assignment-stage work appears on the assignments board and
not on the stories board.
Spiked is a collapsed column that loads its cards only when it is opened.

What an editor does to a Reference before any idea exists steers which ideas are written first: a star rating, their messages and their accept reason are read
by the idea pipeline ([editor interest](idea-context-packs.md#editor-interest-stars-messages-and-accept-reasons)). Stars are on the Reference, not the Item, and
never move an Item between stages.
Items still carrying the retired `research`, `report` or `editor_select`
stages are read as `reporting`; `papyrus assignments migrate-content-item-stages`
rewrites them (dry run by default).

Illustration and typesetting follow copywriting so the board shows the whole
production line up to publication. Nothing moves an item into them yet; editors
place items there by hand until those agents exist. See [story-illustration-typesetting.md](story-illustration-typesetting.md).

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

A person can also start a Story from any Reference with one tap (**Create Story**, [reference curation pipeline](reference-curation-pipeline.md#create-story-ppy-3c11bd)):
it is an Item at the `copywriting` stage that skips the idea stage, linked to the Reference.

## Story types and sections

A story is an `Item` of a story type, and the type is its own attribute, separate from
the section. Papyrus lists no story types. Three Item types are not stories, the fixed **system set**
`SYSTEM_ITEM_TYPES = ["wiki_page", "doctrine", "page"]` (`lib/content-item-lifecycle.ts`, mirrored in
`src/papyrus_content/content_item_lifecycle.py`; `scripts/test-story-types.ts` and `procedures/newsroom/tests/test_story_types.py` keep the two equal),
and **every other type is a story type**, so a site's own new type (`guide`, `case_study`, the type its newsletter issues use) needs no engine change.
Nothing else is special: a newsletter issue is an ordinary Story of whatever `issueType` the site's roundup list names, and the brief is not a type (see below).
The Stories board's queries (`loadNewsroomContentItemStagePage` and `loadNewsroomContentItemsChangedSince`) filter with `type ne` for each system type and never
count those; a stage query filters after DynamoDB reads a page, so a column keeps reading until it has a page of stories (`lib/story-stage-paging.ts`). The idea
context and the duplicate cut use `is_story_item_type`, the same rule.

**A site defines the types it offers** in `web/projection.json`, the file the projector already reads:

```json
"storyTypes": { "default": "post", "types": ["article", "post"] }
```

Both keys are optional. `default` is the type a new Story gets; **with no default a new Story has no type** until an editor chooses one. With no `types`, the
offered types are the default (when there is one) plus every type the site gives a URL base in `urls.types`. The newsroom gets the same file through `withPapyrus`, which
copies the few settings it needs (`storyTypes`, `urls`, `listings.types`) into `NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES` at build time (`lib/site-story-types.ts`); Python
reads it from `PAPYRUS_SITE_STATIC_DIR` (`src/papyrus_content/story_types.py`: the content-actions Lambda has it as `site_static/`, a local run exports the variable as
the home-page commands do). `scripts/fixtures/story-types-cases.json` holds the cases both languages' tests run. A system type, or `untyped`, in `storyTypes` fails
the projection settings.

**A Story with no type.** `Item.type` is required and `typeStatus` (`<type>#<status>`) is an index key, so the unset state is an explicit stored value,
`UNTYPED_ITEM_TYPE = "untyped"` (the same string in both languages), rather than a missing field: no schema change and no data migration, and existing rows are untouched.
It is an ordinary Story type for the board (it shows in its stage column), the editor shows Type as **Not set** with buttons to choose, and it can be drafted and edited.
It cannot be published: `publish_item` refuses with `type-required` and the editor turns Publish off and says why, because the site decides where a page lives from
the type. `untyped` is never offered as a choice. Create Story, the idea pipeline, monitor promotion, `papyrus stories create`, copywriting drafts and promoted
reader submissions (`submissions.itemType` defaults to `untyped`) all use `type_for_new_story()`: the site's default, else `untyped`.

**The brief is not a type.** Copywriting briefs (`copywriting.brief-draft`, the editor's "Brief" decision) are a shorter draft of a Story: the assignment keeps that
form, but the draft Item gets the site's default type or none, like any Story. No Item is written with `type: brief` any more; existing rows are left as they are.

**Create Story is one action**: it makes a Story of the default type (or no type) and opens it, and the **Type** field in the Story editor (buttons, one per offered type, plus
the page) sets or changes it. The type is not locked after creation; it follows versioning:

- **Save as new version** carries the type: the new version has the new type, and the published version keeps the type it was published with, so the live address
  does not move.
- **Save draft** saves in place; on a published Story that republishes at once, so the engine refuses to change the type that way (`type-locked`) and the editor turns
  Save draft and Publish off and points at Save as new version.
- **Publishing** a version of another type moves the live page to the address of the new type (`urls.types`); the projection leaves a redirect from the old address
  (the redirect store of the site), and the publish result says `typeChangedFrom`. The editor shows both addresses before that happens. Publishing a version whose
  type has no page would remove the live page, so the editor turns Publish off in that case (unpublish is the explicit way).

**Retired** (`retired`, not a board column). `papyrus stories retire --story X --redirect-to Y` unpublishes X and moves its head version to this stage, the stage a
machine write that was undone also uses (`machine_writes.RETIRED_STAGE`; `CONTENT_ITEM_STAGES` is unchanged). X keeps every version and records `metadata.retiredInto`
(the lineage it redirects to); the projection redirects every address X was served at, including the ones before a type change (`typeChangedFrom`), to Y's current
address, and follows Y when it moves. `--undo` publishes the retired version again. See [story reporting](story-reporting.md#retiring-a-story-and-redirecting-its-address-stories-retire).

**A type with no public URL.** A page is built for a Story only when its section is declared in `urls.sections`, or its type has a `urls.types` entry, or it has
no section and its type is projected at all (`article`, `page`, and the types in `listings.types` or `urls.types`). A Story of any other type, or in a section
the site does not declare, is recorded as published but gets no page. The editor says so under the Type field ("No public URL"), and the publish result carries
`noPublicPage` so the notice after Publishing says nothing is live.

**Pages** (`page`) are not Stories and stay editable in the same editor for now (the Page button); a way to edit pages as pages is a follow-up.

**A section is a topic.** `Item.section` holds the id of a `NewsroomSection` (`agent-security`) or nothing. It never holds the
name of the type (`articles`) or a placeholder (`unsectioned`), and the type never has to match it. Where it is written:

- The article editor's Section menu offers the enabled newsroom sections by id (and "No section"); an old value outside that list is shown as
  "Old section value". The menu no longer collects the values other rows happen to have.
- A new content item (`build_new_content_item_version`) and a copywriting draft store no section when the Assignment names none (they stored
  `unsectioned`; the generated draft slug `draft-unsectioned-<hash>` keeps its shape).
- The idea pipeline files an idea under the id of the section it names (`section_id_of`, the lookup the editorial checks use: id, the id's local
  part, then title), not under the slug of its title (`Before You File` is the section `guides`, not `before-you-file`). It offers only the site's
  newsroom sections; a site with none offers the real values its stories already have, never `articles` or `unsectioned`.
- Editorial context resolves a story's section the same way (`section_ids.match_section`), and a story with no section simply runs without
  section guidance.
- Not changed here: the reader-steering plugin's `submissions.section` default (`unsectioned`) for briefs, the `--section wiki` / `topics` the
  wiki sync files its pages under, and the newsletter archive's `roundup`. Those are folders a feature finds its Items by, on Items that are not
  stories; `section_migration` leaves them alone.

**Public URLs** key on the type (`urls.types`), on the section (`urls.sections`) or on both; see
[building a Papyrus static site](building-a-papyrus-static-site.md#sections-and-types).

**Migrating stored values.** `python -m papyrus_content.section_migration plan` classifies every stored `(type, section)` pair of a site as
`keep` (empty, already an id, or the folder of an Item that is not a story), `map` (a section's title or short title becomes its id),
`clear` (only the type's name, or `unsectioned`) or `decision` (anything else, left for an editor). It never writes, and a change is blocked
until the `projection.json` it is checked against (`--static`) gives the Item the same page and listing before and after. `apply` writes
only a saved plan with nothing blocked, with `--confirm-site` and `--yes`, one `update` per `Item` row (current and draft versions) and per
`PublishedItem` row; superseded versions keep what they had.

## The configurable name

Editors see one noun for the content item. The default is **Story**, the word
a newspaper newsroom uses for a piece it researches and publishes. A
publication overrides it in its `SiteBrand`, for example a marketing operation
that publishes posts:

```ts
contentItemName: { singular: "Post", plural: "Posts" }
```

`getContentItemName(brand)` returns the configured name or the Story default.
This Story is the newsroom content item, not a Kanbus behavior story; nothing
in Papyrus ties the two together. Every surface that names the content item
reads it: Newsroom navigation, the Board, Assignment views, operator CLI
output and agent skills. Stored data, GraphQL models and code paths are
identical whatever the noun is. Code uses the neutral term *content item*.

The layout `PublicationItemType` union (`article`, `brief`, `promo`, `ad`,
`correction`, `sectionHeader`) is a rendering format and is not the content
item name.

## Delivery order

1. **Name and design.** `SiteBrand.contentItemName` with a Story default, Newsroom navigation reads
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

## Star ratings (PPY-f1c1fd)

An editor can rate a Story one to five stars at any stage, from Idea through after publication. The rating is a private signal about what to publish and,
later, how to rank and feature it. It lives on the Item in `starRating`, `starRatedAt` and `starRatedBy`, the same three fields a Reference has, and follows
the same rules as `setReferenceStars`: it is separate from the stage, the newest rating wins, tapping the star already chosen clears it (and clears who and
when), and it needs no reason. The writer is the `setItemStars` mutation (`amplify/functions/category-action`, editor and admin groups). It is a plain update of
the Story's working record (the row marked current, as `current_story_version` reads it): it creates no version, never touches `stage`, `status`, `updatedAt`
or the content hash, and does not republish a published Story. Only Stories can be rated; a wiki page, doctrine or page cannot.

Item is versioned, so **every path that creates a new version carries the rating onto it**, through `carry_item_stars` in `src/papyrus_content/item_stars.py`
(a Reference once lost its stars because one version path built its row without them):

| Path | How the rating survives |
| --- | --- |
| `papyrus stories save-version`, the editor's "Save as new version" (`save_story_version`) | The new row is built from the working record and `carry_item_stars` copies the rating explicitly |
| Saving the draft in place, `papyrus` import and Story creation (`save_item`) | An in-place update of the existing row, which keeps every field it already has |
| A copywriting run that drafts the next version (`_draft_item_for_copywriting`) | `carry_item_stars` on the drafted row, because that row is built from the packet and not from the old version |
| Moving a Story to another stage (`move_story_stage`), publishing and unpublishing (`publish_item`, `unpublish_item`) | In-place updates of named fields only; the rating is never among them |

The Python authoring client asks for the three fields in `ITEM_FIELDS` and, like the Reference fields, reads a site whose schema does not have them yet without them
(`NEWER_REFERENCE_FIELDS`), so a router serving sites on different versions keeps working. The legacy `type="assignment"` Item path in `newsroom.py` builds assignment
Items, not Stories, and is not a rating path.

**Stars are never published.** (A Reference's stars are: see [Home page](home-page.md). A Story's are not.) They order things for editors and, privately, public listings (below), and never reach `PublishedItem`, a projection or any page: the three fields are not on the
`PublishedItem` model in either schema file, `project_item_to_published` writes an explicit field list and then runs `assert_no_item_stars` on the row, and
`GraphQLItem`, the type draft previews are built from, does not carry them. `scripts/test-story-stars-api.ts` and `features_backend/story-stars.feature` fail if a
star reaches published output.

On the newsroom side the drawer and the Story editor show `components/star-rating.tsx` (label "Rating · optional") and the Stories board card shows the rating read-only, one solid star and the number in its top row: optimistic, kept in one
store (`components/use-story-stars.ts`) so the three show one rating, and a failed save puts the saved rating back with a message. The Kanbus card has no slot for a
mark, so each Story card gets one container in its top row that the rating is drawn into (`components/story-board-stars.tsx`). A card read from a published-only row (not from the
Item) has no control, because its rating is not known there; the drawer has it. The board's ordering does not use the rating.
A schema change: it needs the site backend deployed.

### Published Stories rank by recency bucket, then stars (PPY-5966d7)

The rating is private, but it orders the public listings. Listing includes, the featured slot, the home page's list, a section's listing page (`/articles/`),
a collection page (`/posts/`) and tag pages put the newest bucket first and, inside a bucket, five, four and three stars first, then Stories nobody rated, then
two and one stars; equal Stories keep their newest-first order. The order of ratings is the one References follow, and the code is shared (`rank_in_buckets` in
`src/papyrus_content/home_page/ordering.py`; the Story side is `projection/standard/story_order.py`). **A Story bucket is a rolling window** (Ryan, 2026-11-04:
"rolling last seven days for the week"): counted back from the UTC day of the projection, `week` (the default of `listings.bucket`) is the last seven days, the
seven before that, and so on; `day` is the last day, the day before, and so on; `none` is the old newest-first list. An include can say `bucket="day|week|none"`.
A Reference's bucket rolls the same way (Ryan, 2026-11-05; see [Home page](home-page.md#time-buckets)). The feeds, the sitemap and `llms.txt` stay in date order.

**Time moves Stories between buckets with no write.** The order depends on the UTC day (never the time of day), so a listing can change at most once a day. There is
no schedule and no pass over a corpus for it. A page holds the order of its last render and is corrected whenever something that already re-renders it runs: a publish
(it rewrites the listings the new Story appears in, computed as of that day, which are the pages most likely to be stale), a rating (`story-stars` runs the whole
stale-listings pass), the post-release render, or `papyrus ops content project --reconcile`. A page nothing touches can lag by days; that cannot be closed
without a scheduled pass, which Ryan's rule forbids, so it is the stated limit. The home-page snapshot run only rewrites pages that read the snapshot, so it corrects those and no others.

**What happens to older Stories.** Nothing is dropped. A Story from an earlier bucket follows every Story of the newer buckets and is ranked inside its own, so
an old five-star Story never rises above a newer week. A listing with `count` shows the first `count` of that ranked list, so it reaches an earlier bucket only
when the newer ones have fewer Stories than `count`. A listing page shows all of them, page after page, in the same order. Stories nobody rated sort between the
high and the low ratings in newest-first order, and a site where nothing is rated lists exactly as before (the stable sort leaves the list alone, and the pages
are byte for byte the same).

**Where the rating comes from.** The rating sits on the Story's working Item version, which is not the published row. At projection time the source reads
`{lineage: stars}` from a private item in the projection lock table, `story-stars#<site scope>` (`projection/story_stars.py`), in one request. A Story the item
has not seen is read once from its Item rows and remembered, so a site starts with an empty item and a Story rated before it was published counts at its first
projection. The ratings travel inside the `SiteIndex` to the projector and are used only to order; `StandardEntry`, `PublishedItem` and every fingerprint carry no
star, and no public file mentions one. The rule `assert_no_item_stars` still guards every published row.

**What a rating change costs.** `setItemStars` asks the site's content-actions function, once, to run the `story-stars` projection task for the Item version it
changed (`PAPYRUS_CONTENT_ACTIONS_FUNCTION` on the category-action function; an asynchronous invocation, best effort because the rating is already saved). The
task (`projection/story_stars_task.py`) reads that one row, sets the Story's entry, and, when the Story is published, runs the ordinary stale-listing pass:
every listing is ordered with the new rating, and only the pages whose digest (their entries in order) changed are written. It reads the published summaries
once, as every listing refresh does, and renders no Story page. The same rating twice, or one that moves nothing, rewrites nothing.

**Not ranked.** A listing include inside a Story page (a wiki page) keeps date order, because a Story page is not re-rendered when only a rating changes.

## Out of scope for now

Board write actions (status transitions `PPY-caf6e5`, drag-to-publish
`PPY-86eda3`) stay deferred. The Board remains read-only.
