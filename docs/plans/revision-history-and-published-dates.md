# Publication transparency: published and updated dates, and a public revision history

Status: design, not built. Epic: PPY-156614. First site: Machines on Machines (MoM), whose brand is openness and transparency.

## What was asked

Ryan, 2026-11-12:

1. Do we have created and updated times? Much of our ordering is based on `updatedAt`: is that right? Is there a published time? If not, add and index one so most publishing decisions use it, while `updatedAt` still changes when a published Story changes.
2. The public page shows both dates when they differ.
3. Is there a per-Story editing log we could show as a revision history? We store versions; do we store a description of each one?
4. Editors need free-form editor's notes for changes that make no new version (a section change, an added Reference, an association). The revision history combines versions and notes.
5. The history is collapsed by default and not prominent, at the foot of the article, the way a reputable publication shows it.
6. It is a general Papyrus feature any publication can turn on; MoM proves it first.

Ryan agreed that the open questions are decided by recommendation. The recommendations are in "Decisions".

Standing rules that shape this design: fix causes, no workarounds, fallbacks or shims; the simplest design that meets the need; narrative Gherkin for every behaviour; no fixed limits; DynamoDB is the catalog and text lives in S3; no whole-table reads and no O(N) work per change; no AppSync subscriptions; at most one new index per table per deploy; Lucide icons, flat fills, no borders; plain words in the UI. The site already says everything is drafted by AI, so the history adds no "edited by AI" labels; it names who or what made each change only as that entry's actor.

## Summary

- **Dates.** `publishedAt` exists and is indexed, but today it means "when the version now served was published": every new version is saved with `publishedAt: null` and publishing it stamps the current time. So a republished article jumps back to the top of every list, lands in "this week" again, and shows its republish date as its publication date, with `dateModified` equal to it. Live proof: the MoM containment article, live by 4 November, now says `datePublished: 2026-11-11` and `dateModified: 2026-11-11`. The fix is at the cause: `publishedAt` becomes the time the Story was first published and is carried to every later version, and a new field `versionPublishedAt` records when the version now served went live. Public "Updated" is `versionPublishedAt`. No new index is needed: the two existing `publishedAt` indexes become right once the value is.
- **Version descriptions.** Versions carry `versionCreatedAt`, `versionCreatedBy` and `changeReason`, but publishing and unpublishing overwrite all three on the published row (`changeReason` becomes `"publish"`), so the editor's "What changed in this version" text is lost at the moment it matters. `changeReason` is also mostly machine codes (`copywriting-assignment-run`, `created`). It stays internal. Publishing stops overwriting version fields.
- **Editor's notes.** One new Message kind, `revision_note`, on the Story's existing reporting thread (anchored to the Story lineage). Writing one is the act of making it public. Its text is a Message body in S3. No new table and no new index.
- **Revision history.** Published versions plus revision notes, merged by time, kept as one small JSON file per Story in the site store, written once when that Story is published or gets a note, and drawn at the foot of the article in a native `<details>` element, closed by default. A per-publication setting, off by default, on for MoM.

## What exists today (verified on `origin/develop` at 34e3404a)

| Field or record | Where | What it really means today |
| --- | --- | --- |
| `Item.createdAt`, `updatedAt` | `amplify/data/schema.ts` (Item, about line 2345) | Row creation; last write of any kind. AppSync stamps `updatedAt` on every update that does not pass one, including star ratings and stage index fields. |
| `Item.versionNumber`, `versionCreatedAt`, `versionCreatedBy`, `changeReason` | same | Per version. Overwritten on the published row by `publish_item` (`changeReason: "publish"`, `versionCreatedAt: now`) and by `unpublish_item` (`"unpublish"`) in `src/papyrus_content/publishing.py`. Superseded rows keep theirs (`superseding_update` passes `updatedAt` back and touches nothing else). |
| `Item.publishedAt`, `PublishedItem.publishedAt` | same | Set to `item.publishedAt or now` at publish; `save_story_version` (`story_reporting.py`) saves every new version with `publishedAt: None`, so every republish of a new version stamps now. |
| Indexes `typeStatus+publishedAt`, `sectionStatus+publishedAt` | Item and PublishedItem | Correct shape; wrong value after a republish. |
| Index `versionState+updatedAt`, `stage+updatedAt`, `headStageKey+updatedAt` | Item | Newsroom work queues. |
| Static entries `date`, `updated` | `projection/standard/entries.py` | `date` = front matter `date`, else `publishedAt`; `updated` = front matter `updated`/`modified`/`lastmod`/`dateModified`, else `publishedAt`. With no front matter dates (all newsroom-written Stories), `updated == date`. |
| Reporting thread and notes | `story_reporting.py` `append_story_message`, `papyrus stories note --kind note|research_packet|reporting_context_packet|draft_note|editor_note` | Internal notes on a `story_reporting` thread found by `messageThreadsByAnchor` (`item#<lineage>`), ordered by `messagesByThreadAndSequence`. Already supports `--version`. Nothing public reads it. |
| `SemanticRelation` | schema | Append-only links (Reference to Story, Story to Story, concept tags) with `createdAt`, `relationState` and actor in `metadata`. |

Nothing public shows a version's reason. No public page shows two dates (the Markdown twin would print "Updated" if `updated` differed, but it never does for newsroom Stories; the wiki shows "Updated" equal to the publication date).

## Audit: what orders or decides by `updatedAt` versus `publishedAt`

Grepped `src/`, `amplify/`, `lib/`, `components/`, `app/` and the MoM site repository.

**Public: these read `publishedAt` and inherit the bug. Fix the value, not the readers.**

| Reader | File | After the fix |
| --- | --- | --- |
| Listing order (`newest_first`, `sorted_by`), section fronts, includes, date grouping | `entries.py`, `includes.py`, `grouping.py`, `projector.py` | Order by first publication. Right. |
| Home page buckets and star ranking (rolling week windows) | `story_order.py`, `story_signals.py` (`story_moment`) | A republish no longer makes an old Story "new this week". Right. |
| Article and card dates | `components.py`, MoM `web/hooks.py` (`entry.date`) | Shows first publication. Right; the page header adds "Updated". |
| JSON-LD `datePublished`/`dateModified`, `article:published_time`/`modified_time` | `head.py` via `share_preview.py` | `dateModified` reads `versionPublishedAt`. |
| RSS `pubDate`, Atom `published`/`updated`, feed `updated` | `feeds.py` | `pubDate` and `published` = first publication; Atom `updated` = `versionPublishedAt`. |
| Sitemap `lastmod` | `projector.py` (`entry.updated`) | `versionPublishedAt`. |
| Markdown twin "Published · Updated" | `markdown.py` | Now prints both when the days differ. |
| Wiki "Updated" | `wiki.py` | `versionPublishedAt`. |
| Alexa story source | `amplify/plugins/alexa/content/public-site-story-source.ts` | First publication. Right. |

**Newsroom work queues: keep `updatedAt`.** These answer "what was touched recently", which is what an editor working a queue wants: the head stage board columns and "changed since" (`lib/story-stage-query.ts`, `story_head_index.py`), the Articles list (`lib/newsroom-articles.ts`), `newsroom-board.ts`, assignments, threads, Reference curation lists, `papyrus stories list --sort updated`. One known quirk stays out of scope: a star rating stamps `Item.updatedAt` and so lifts the card in its board column. It is a private signal on a work queue; nothing public reads it.

**Bugs found.**

1. `publishedAt` is reset on every republish (above). Cause: `save_story_version` writes `publishedAt: None`; `publish_item` uses `item.publishedAt or now`.
2. `publish_item` and `unpublish_item` overwrite `versionCreatedAt`, `versionCreatedBy` and `changeReason` on the row they publish, destroying the version's own record (and the editor's "What changed" text). `story_retire.py` already has to guess "was this ever public" from `changeReason in ("publish", "unpublish")`.
3. `entries.py` gives front matter `date`/`updated` precedence over the recorded fields. Imports already map front matter `date` into `publishedAt` (`publishing.py` `columns_from_front_matter`), so after the backfill the recorded fields are the one source and the precedence goes.
4. Machine-readable dates are calendar days (`2026-11-11`). JSON-LD, Atom and the sitemap get full ISO timestamps; visible text stays a day.

## Decisions

### What the dates mean

- **`publishedAt`**: the moment the Story was first published, on the lineage. Set once by the first publish and carried to every later version by `save_story_version`. Never changed by a later publish.
- **`versionPublishedAt`** (new, `a.datetime()` on Item and PublishedItem, with `versionPublishedBy`): when this version went live, and who published it. Set by `publish_item` on the row it publishes. The public "Updated" time is the served version's `versionPublishedAt`.
- **Republish after an unpublish** keeps the original `publishedAt`: the article existed in public before, and the history says so ("Taken down", then "Published again"). Unpublishing requires a public reason, recorded as a revision note.
- **Retire into another Story** (`papyrus stories retire`): the retired address redirects; the target Story gets an automatic note "Merged *<title>* into this article" with the retirement reason, and its `publishedAt` does not change. Published pages are never retired silently: retiring a published Story requires the reason.
- **What bumps public "Updated"**: publishing a new version whose content changed. Nothing else: not notes, not section moves, not added sources or links, not ratings, not re-renders, not front matter-free metadata writes. A typo fix that is published as a new version does bump it, and the history says what it was. Honest and simple; no "minor change" flag (YAGNI).
- **`updatedAt` stays** what AppSync makes it, the last write, for work queues. Nothing public reads it.
- `createdAt` is unchanged.

No new index: the existing `typeStatus+publishedAt` and `sectionStatus+publishedAt` indexes on Item and PublishedItem serve every public order once `publishedAt` is stable. No public list orders by "recently updated".

### Public dates

- **Article, post and wiki page header**: "Published 4 Nov 2026 · Updated 11 Nov 2026", each a `<time datetime="…">` with the full timestamp. "Updated" appears only when the two calendar days differ in the site's time zone. When the publication has revision history on, "Updated" links to `#revision-history` and opens it.
- **Cards and listings**: the publication date only. Two dates on a card is noise.
- **Feeds**: RSS `pubDate` = `publishedAt`; Atom `published` = `publishedAt`, `updated` = `versionPublishedAt`; the feed's own `updated` is the newest `versionPublishedAt` in it.
- **JSON-LD and Open Graph**: `datePublished` = `publishedAt`, `dateModified` = `versionPublishedAt`.
- **Markdown twin**: "Published 2026-11-04 · Updated 2026-11-11" when they differ, as `markdown.py` already prints.
- **Sitemap**: `lastmod` = `versionPublishedAt` (the page text changed then; a note added later changes only the closed history block).

The standard entry gets `published` and `updated` as ISO timestamps from the two fields; `date` stays the calendar day for display and grouping.

### Editor's notes (revision notes)

**Record.** A Message with `messageKind: "revision_note"` on the Story's existing `story_reporting` thread (`ensure_story_thread`, anchor `item#<lineage>`). Fields already on Message carry everything: author (`authorSub`, `authorLabel`, `authorKind`, `role`), time (`createdAt`), order (`sequenceNumber`), `summary` (the one-line text), and `metadata`: `{"kind": "story.revision_note", "storyLineageId", "event": "note|version|section|source|link|concept|unpublished|republished|merged", "versionNumber"?, "subjects"?: [{kind, lineageId}]}`. The body is written to S3 as the Message's `message_body` ModelAttachment (the same attachment `messages backfill-message-body` uses), not inline in `content`.

**Public is the kind, not a flag.** An internal note stays `editor_note` or `note` as today. A revision note is public by definition; the newsroom offers them as two separate actions ("Add an internal note", "Add a note to the revision history"), and the second says it is public. There is no hidden-but-present public flag to get wrong.

**Append-only.** A revision note is never edited. A wrong note is corrected by a later note; an admin can withdraw a note (status `withdrawn`, the existing Message status pattern), which removes it from the history and is itself recorded internally.

**Why the Message model.** It already is an attributed, ordered, append-only log anchored to a Story lineage, with the indexes the history needs (`messageThreadsByAnchor`, `messagesByThreadAndSequence`) and an S3 body attachment. `SemanticRelation` provenance was considered: it records links but not section moves, takedowns or free text, and reading it back as history would make a third source. A new model would add a table and indexes for nothing Message lacks.

**Who writes them.**

- People: the newsroom (the Story page, under its versions), `papyrus stories note --kind revision_note`, and the MCP tool, all generated from one operation-table entry `story.revision_note.add` (the CLI/MCP/UI parity rule).
- The version note: the publish dialog gets "What changed, for readers" (optional). If filled, publishing writes a revision note with `event: version` and the `versionNumber`. The existing "What changed in this version" field stays the internal `changeReason`.
- Tools, automatically, for public-facing changes that make no new version, and only while the Story is published: section moved, a cited Reference added or removed, a related article link added or removed, a concept tag added or removed, taken down, published again, merged. Each write path calls one shared function per kind (`record_public_change`) from the operation that makes the change, in the same request; one operation call that changes several links writes one note listing them ("Linked three related articles: …"). Consulted-only References, ratings, Cyclotron predictions, re-renders and anything not shown on the page write nothing.

Finding every write path for these changes (Python CLI, content-actions, the TypeScript `category-action` handler) and routing each through that one function is part of the work; a change made outside it is a bug, not a gap to fill later from another source. DynamoDB streams were rejected: they add infrastructure and lose the operation's actor and its grouping.

### Combined revision history

**Entries.** Merged by time, oldest first:

1. "Published" at `publishedAt` (the first version), with its version note if one exists.
2. "Revised" at each later published version's `versionPublishedAt`, with that version's revision note if one exists. Draft versions that were never published are not listed: they were never public.
3. Each revision note that is not a version note, at its `createdAt`.
4. "Taken down" / "Published again" / "Merged" from their notes.

Each entry shows the date, the plain sentence, and the actor: a person's display name from their newsroom profile (never an email or id), or a tool's public name ("Papyrus"). No "edited by AI" text anywhere.

**Old versions with no public reason.** They show "Revised" and the date, nothing more. No invented reasons, no placeholder text. `changeReason` is never shown: it is internal, and today mostly machine codes.

**Projection.** One JSON file per Story in the site store, `_papyrus/history/<lineage>.json`, like `_papyrus/bodies.json.gz`: `{fingerprint, entries[]}`. It is computed by the single-item page job, which already runs when that Story is published, and which a revision note now also triggers for its Story only (and purges only that page). Computing it is two indexed reads for that one Story: `listItemsByLineageAndVersion` and the thread's `messagesByThreadAndSequence`, plus one S3 get per note body. Whole-site renders read the file and recompute only when it is missing. No list, home page or feed reads it. Nothing else is written per change.

**Page.** At the foot of the article, after the sources and before conversations:

```html
<details class="papyrus-revision-history" id="revision-history">
  <summary>Revision history</summary>
  <ol>
    <li><time datetime="2026-11-04T15:02:11Z">4 Nov 2026</time> Published. <span>Sam Editor</span></li>
    <li><time datetime="2026-11-11T09:40:03Z">11 Nov 2026</time> Revised: shorter headline and a clearer opening. <span>Sam Editor</span></li>
    <li><time datetime="2026-11-12T10:15:00Z">12 Nov 2026</time> Added a source: <a href="…">…</a>. <span>Papyrus</span></li>
  </ol>
</details>
```

Closed by default, no JavaScript, keyboard and screen reader friendly by being native; the summary uses a Lucide `history` icon, flat fill, no border. The block appears only when the history has at least one entry after "Published": a never-revised article already says when it was published. The Markdown twin ends with `## Revision history` and the same entries as a list.

**Settings.** One publication setting, `revisionHistory: true|false` in the standard site configuration, off by default, on for MoM. When on, it covers every public Story type (articles, posts, wiki pages). No per-Story switch (YAGNI): an editor controls what appears by what they write as public notes.

**Privacy.** Only published versions and revision notes appear. Never internal notes, `changeReason`, stars, Cyclotron scores, consulted References, agent prompts, emails, Cognito ids or anything a reader cannot already see on the page. Automatic notes name only things the page shows.

### Answers to the three questions

1. **Every note public, or only marked ones?** Only revision notes, and writing one is the marking: a separate kind and a separate action that says it is public. Internal notes stay internal by construction, so nothing private can leak through a forgotten checkbox.
2. **Should automatic notes name the Reference?** Yes, when it is a cited source shown on the page: link it with its title, as the page's sources list already does. Changes to things the page does not show write no note at all, so nothing private is named.
3. **All Story types?** Every type with a public page (articles, posts, wiki pages), one rule. Wiki pages change the most and gain the most. Ideas and checklist steps are never published, so they have no history.

## Backfill

No invented history.

1. `versionPublishedAt` on each PublishedItem and its served Item row = today's `PublishedItem.publishedAt` (which is exactly the served version's publish time).
2. `publishedAt` = the earliest recorded publish time of the lineage: the earliest `versionCreatedAt` among its rows whose `changeReason` is `publish` (superseded rows keep it), or front matter `date` for imported Stories where that is earlier. A lineage whose only evidence is an `unpublish` row is listed in the dry-run report for a person to decide; it keeps today's value until then.
3. Revision history starts from the published versions found in step 2; earlier published versions show "Revised" with no reason. No revision notes are created by the backfill.
4. Reads are per published Story through indexes (`typeStatus+publishedAt` to list published Stories, then `listItemsByLineageAndVersion`), once, rate-limited, `--dry-run` first, through the signed-in `papyrus` CLI. About 100 Stories on MoM: a few hundred requests once.
5. After the backfill, the front matter date precedence in `entries.py` is removed.

## Cost

Per publish: one more field written, plus one history file put. Per revision note: one Message, one S3 body, one single-page build and one single-path purge. No new tables, no new indexes, no subscriptions, no whole-table reads, no per-change work over other Stories.

## Tests

Narrative Gherkin per behaviour (Python Behave in `features_backend/`, page output in the projection features). Each story below lists its scenarios. Unit tests for the merge (ordering ties by sequence number), the fingerprint, and the privacy filter (internal notes and `changeReason` never appear).

## First slice on MoM, in preview

Before any release: run `tools/preview_production.py` for MoM on the branch with real MoM data (read-only) after a dry-run backfill computed in memory, and check: the containment article shows "Published 4 Nov 2026 · Updated 11 Nov 2026"; a closed "Revision history" with "Published" and the later "Revised" entries; JSON-LD dates; the feed; the Markdown twin. Ryan reviews the preview, then the release follows the usual rules.

## Out of scope (noted)

- `postMessage` still writes Message text inline in DynamoDB; revision notes write their body to S3 from the start. Moving other Message writes is separate.
- A star rating lifting a card in a newsroom board column (a private work-queue quirk).

## Stories

Order: 1, then 2 and 3 in parallel, then 4, 5, 6, 7.

### 1. Dates mean what they say: `publishedAt` is the first publication, `versionPublishedAt` the served version

Goal: fix bugs 1 to 4; backfill; remove the front matter precedence.
Depends on: nothing. Deploy: schema field adds only (no index).

```gherkin
Feature: A Story keeps the date it was first published
  Readers and every list on the site order Stories by when they first appeared,
  so a corrected article does not pretend to be new.

  Scenario: Publishing a new version keeps the first publication time
    Given a Story first published on 4 November 2026 at 15:02
    And an editor saves a new version on 11 November 2026
    When the editor publishes that version at 09:40
    Then the Story's published time is still 4 November 2026 at 15:02
    And the served version's published time is 11 November 2026 at 09:40
    And the Story stays in its place in the section listing

  Scenario: Publishing keeps the version's own record
    Given a version saved by Sam with the reason "tighten the opening"
    When an editor publishes it
    Then the version still says it was saved by Sam, when, and why
    And it also says who published it and when

  Scenario: A Story published again after a takedown keeps its first date
    Given a Story first published on 4 November and taken down on 6 November
    When it is published again on 8 November
    Then its published time is still 4 November

  Scenario: A rating does not change any public date
    Given a published Story
    When an editor gives it four stars
    Then its published and updated times do not change

  Scenario: The backfill records only what history shows
    Given a published Story whose versions recorded publishes on 4 and 11 November
    When the backfill runs
    Then its published time is 4 November and its served version's published time is 11 November
    And a Story with no recorded publish time is listed for a person to decide, and is not changed
```

Open question: none.

### 2. Public dates: "Published · Updated" on pages, feeds, structured data, sitemap and Markdown

Depends on: 1.

```gherkin
Feature: Readers see when a page was published and when it last changed
  Scenario: A revised article shows both dates
    Given an article first published on 4 November and last revised on 11 November
    When a reader opens it
    Then the header says "Published 4 Nov 2026 · Updated 11 Nov 2026"
    And its structured data says it was published on 4 November and modified on 11 November

  Scenario: An article revised the same day shows one date
    Given an article published and revised on 4 November
    When a reader opens it
    Then the header says only "Published 4 Nov 2026"

  Scenario: Cards show only the publication date
    When a reader opens the home page
    Then each card shows the date its Story was first published

  Scenario: Feeds and the sitemap carry both times
    Then the Atom entry is published on 4 November and updated on 11 November
    And the RSS item's date is 4 November
    And the sitemap's last change for the page is 11 November

  Scenario: The Markdown copy carries both dates
    Then the Markdown copy says "Published 2026-11-04 · Updated 2026-11-11"
```

Open question: none.

### 3. Revision notes: the record and its tools (CLI, MCP, newsroom)

Depends on: nothing (parallel with 1).

```gherkin
Feature: Editors add public notes to a Story's revision history
  Scenario: An editor adds a public note
    Given a published Story
    When an editor adds the revision note "Moved to Security, where readers look for it"
    Then the note is saved with the editor's name and the time
    And its text is stored as a file, not in the database row
    And only that Story's page is rebuilt

  Scenario: Internal notes stay internal
    Given a Story with an internal note and a revision note
    When the revision history is built
    Then it contains the revision note and not the internal note

  Scenario: The same operation from every tool
    When an editor adds a revision note from the command line, from the MCP tool and from the newsroom
    Then all three are saved the same way by the same operation

  Scenario: A wrong note is withdrawn, not edited
    Given a revision note with a mistake
    When an admin withdraws it
    Then it no longer appears in the revision history
    And the withdrawal is recorded internally

  Scenario: Publishing with a note for readers
    When an editor publishes a version with "What changed, for readers" filled in
    Then that text appears beside the version in the revision history
```

Open question: none.

### 4. Automatic notes for section, source, link and concept changes, takedowns and merges

Depends on: 3.

```gherkin
Feature: Changes readers can see on a page are noted without a person writing it
  Scenario: Moving a published Story to another section
    Given a published Story in Research
    When an editor moves it to Security
    Then its revision history gains "Moved from Research to Security" by that editor

  Scenario: Adding a cited source names it
    When a cited Reference "A paper on agent memory" is added to a published Story
    Then the revision history gains "Added a source: A paper on agent memory", linked

  Scenario: One pass that adds several links writes one note
    When an association review links three related articles to a published Story at once
    Then the revision history gains one note naming the three articles

  Scenario: Private changes write nothing
    When a Reference is added as consulted only, or the Story is rated, or its page is rebuilt
    Then the revision history does not change

  Scenario: Drafts are not noted
    Given a Story that has never been published
    When its section changes
    Then no revision note is written

  Scenario: A takedown needs a reason
    When an editor takes down a published Story without a reason
    Then the takedown is refused and asks for the reason

  Scenario: Merging a Story is noted on the Story it joined
    When a published Story is retired into another Story
    Then the other Story's revision history gains "Merged <title> into this article" with the reason
```

Open question: none.

### 5. The combined revision history: projection and page

Depends on: 1, 3.

```gherkin
Feature: A closed revision history at the foot of each revised article
  Scenario: Versions and notes in one list
    Given a Story published on 4 November, revised on 11 November, and given a note on 12 November
    When a reader opens it
    Then a closed "Revision history" appears after the sources
    And opening it lists "Published", "Revised" and the note, oldest first, each with its date and who made it

  Scenario: An old version with no public reason
    Given a version published before revision notes existed
    Then its entry says "Revised" and its date, and nothing else

  Scenario: Never-revised articles have no history block
    Given an article published once and never changed
    Then the page has no revision history block

  Scenario: It works without JavaScript
    Given a reader with scripts turned off
    Then the revision history opens and closes

  Scenario: The history is built once per change
    When a revision note is added to one Story
    Then only that Story's history file and page are written

  Scenario: The Markdown copy lists the history
    Then the Markdown copy ends with "Revision history" and the same entries
```

Open question: whether people are named (question 2 below).

### 6. Publication setting and MoM rollout

Depends on: 2, 5. Includes the preview on MoM with real data before release.

```gherkin
Feature: A publication chooses to show revision history
  Scenario: Off unless turned on
    Given a publication that has not turned on revision history
    Then its pages show dates but no revision history

  Scenario: Machines on Machines shows it
    Given Machines on Machines with revision history turned on
    When a reader opens a revised article, post or wiki page
    Then it has the closed revision history
```

Open question: none.

### 7. Document the feature on p.apyr.us

Depends on: 6. A p.apyr.us page: what readers see, how editors write public notes, what is noted automatically, and the setting.

```gherkin
Feature: The Papyrus site explains publication transparency
  Scenario: A prospective publisher reads about it
    When a visitor opens the transparency feature page on p.apyr.us
    Then it shows an example revision history and explains how to turn it on
```

## Questions for Ryan

1. Should the history name individual editors (their newsroom display name), or say "Editors" for every person? Recommendation: name them; MoM's brand is openness, and bylines already name people.
2. Should a typo fix published as a new version change "Updated"? Recommendation: yes, always; the history explains it.
3. When a published Story is taken down, should its address show a short "This article was taken down on <date>: <reason>" page instead of a 404? Recommendation: yes for MoM, as a follow-up story.
4. Should automatic notes for concept tags be written, or only for sources, related articles and section moves? Recommendation: write them; they are visible on the page and one pass writes one note.

## Board

Epic and stories are filed under the initiative "One content item, one lifecycle" (PPY-ad3da5) as epic PPY-156614, with stories 1 to 7 as PPY-271940, PPY-de3f8f, PPY-2f197f, PPY-246574, PPY-befbd8, PPY-6cdef0 and PPY-419678 (the p.apyr.us task), because the core of this is the lifecycle record of a Story (its versions, publication and notes); the public parts render through the standard front end in core.
