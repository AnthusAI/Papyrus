# What the newsroom console loads, and how to page it

Ryan asked on 2026-11-10: "Is our newsroom UI loading the whole entire list of stories every single time? We need a better method of pagination and lazy loading."

This audit traced every console surface on `origin/develop` at 5.104.0 (`0e3a72c0`). It covers what each surface asks the backend for, how much, and how often. Scale assumed is Machines on Machines today: about 270 story lineages, about 900 Item rows (versions), several hundred References, a few thousand SemanticRelations and a few hundred Message threads. Sites will grow ten times.

The findings come from reading the code, with a file and line for every claim. Two of them were also measured: the board column and the story open were run with fake backends that count every request and every row read (`scripts/test-board-head-index.ts`, `scripts/test-story-open-reads.ts`). No live site was used. Nothing was written to AWS.

## The short answer

**The Stories board does not load every story.** Each column loads 25 stories, newest first, and the next 25 only when the editor scrolls to the end of that column. A refresh asks each column only for stories changed since its newest card. It runs every five minutes while the tab is visible, on focus at most once a minute, and after the editor's own edits. The Spiked column loads nothing until it is opened. There are no realtime subscriptions on the board. This has been in place since the board-refresh work (`components/use-paged-content-item-versions.ts`, `lib/board-refresh.ts`, `features/newsroom-board-refresh.feature`).

The board still has two costs:

1. **Each column reads old versions it then hides.** The stage index holds every saved version of every story. The `versionState ne superseded` filter runs only after DynamoDB has read the rows. On MoM, 456 of the 580 rows in the Published partition are superseded, so a Published page reads about 4.7 rows for each card it shows. That cost grows with every save. **Fixed in this PR, per site:** the columns read the head stage index, one row per story. See "What this PR changes" below.
2. **It re-reads every Assignment every time.** This happens on the Stories board too, on every load and every refresh (`components/newsroom-board-view.tsx:49-58, 115-130`). Not fixed here; the design is below.

**The whole-table reads are elsewhere.** The worst ones are the Topics, Desks, Concepts and Administration tabs, which read about 16 whole tables on every visit, and opening a story, which read the whole relation table twice. The ranked list follows.

## Every surface, ranked by cost

How to read the table:

- **Whole read** means a loop `while (nextToken)` over a table or partition that grows with the site, done to show a handful of items.
- **Bounded** means the loop is keyed to one owner (one story's versions, one thread's messages), so it grows only with that owner.
- **Request counts** are at MoM scale today; multiply by ten for the ten-times case.

| # | Surface | What loads | How much | How often |
| --- | --- | --- | --- | --- |
| 1 | **Topics, Desks, Concepts, Administration tabs** (`components/topic-steering-workspace.tsx:1344-1377` → `loadEditorFullNewsDeskDashboard`, `components/news-desk-taxonomy-client.ts:921-1019`) | Whole reads with `listUserPoolModel` (a `list` scan, 500 per page, until exhausted; taxonomy client 3329-3349). Tables: KnowledgeCorpus, KnowledgeImportRun, CategorySet, Category, CategoryKeyword, LexicalSteeringRule, KnowledgeArtifact, **Reference, ReferenceAttachment, SemanticNode, Message, SemanticRelation**, EditionSlot and NewsroomSection. Also SteeringProposals, 50 Assignments, AssignmentEvents and one doctrine read per category. | About 20-30 requests and 5-10k rows; about 150-300 requests and 50-100k rows at ten times. | **Every visit** to any of the four tabs. Each tab is its own route, so the workspace remounts and `loadedSections.fullDashboard` resets. Again after each of 7 topic and category edits (`W:2455`) and after a procedure run (`W:2760`). The category tree is read a second time on each tab change (`W:1177-1217`). |
| 2 | **Opening a story** (board drawer and full page, `components/newsroom-article-editor.tsx`, `components/story-reporting-trail.tsx`) | `loadStoryReportingTrail` (`components/story-reporting-trail-client.ts:131-176`). It used to read the **whole SemanticRelation table** (a filtered `listSemanticRelations`, 200 per page, until exhausted) and the **whole MessageThread table** (a filtered `listMessageThreads`), then per assignment, per thread and per cited Reference. | ceil(relations / 200) + ceil(threads / 200) requests one after another, about 10-25 per call today. | Twice per open: once by the editor only to learn the newest version number, and once by the Messages/References tab. Again on every save and version switch. Every 30 s while a research assignment is open. **Changed in this PR**: see below. |
| 3 | **Notification Center** (console home, `components/notification-center.tsx`) | Each tick runs:<br>• `loadReviews` (`lib/review-client.ts:37-76`): a scan of all ReviewRequests (500 per page, up to 10 pages), an **`updateReviewRequest` write for each overdue request**, and ReviewReadMarks scanned with a `userKey` filter at limit 5000 and no paging, so marks are lost past 5000 rows.<br>• Held emails, paged until exhausted.<br>• One `listItemsByLineageAndVersion(50)` per open story request, fetching the body of every version just to show a title. | About 3-15 requests per tick, growing with every review ever raised. | **Every 60 s, including in a hidden tab** (`setInterval`, no visibility check, line 338). |
| 4 | **Search tab** and the References list view (`W:1282-1300` → `loadAllEditorReferences`, taxonomy client 2026-2037) | Every Reference, by four curation statuses, 200 per page, until exhausted, with a filter applied after the read. The search results themselves come from the server-side `searchReferences`, 24 per page (`components/newsroom-search-results.tsx`), so the search tab's whole read is never used. | About 4-8 requests and about 700 rows; about 40 and 7k at ten times. | Every visit to Search, every switch to list view, every assignment deep link. |
| 5 | **Board: Assignments** (`components/newsroom-board-view.tsx:49-58`) | Every Assignment through the assignment feed (`listAssignmentsByNewsroomFeedAndCreatedAt`, 100 per page, until exhausted), filtered on the client. The Stories board uses them only for the cards of the stories it shows. | ceil(assignments / 100) requests, about 8 today and about 80 at ten times. | Mount; every 5 min while visible; on focus after 60 s; on closing or switching the open card; after each checklist change. All three board kinds (Stories, Desk, Assignments). |
| 6 | **Board: story columns** (`components/use-paged-content-item-versions.ts`, `loadNewsroomContentItemStagePage`) | 25 stories per column from `listItemsByStageAndUpdatedAt`, with the superseded filter applied after the read (100 rows per read). Default stages are 7 (Spiked deferred until opened) plus the 3 legacy stage keys, so about 9 request chains. | Today about 9-15 requests and up to about 4.7 rows read per card in Published. **On the head index (this PR): one request and 25 rows per column.** | Mount. Each refresh asks every loaded stage only for rows changed since its newest card (a key condition, so a quiet board gets empty answers). "Load more" happens on scroll to a column's end. |
| 7 | **References tab** (`W:3303`, `components/newsroom-references-view.tsx`) | **Good:** the feed itself is one indexed page of 24 per partition. Predictions and attachments are batched per page of shown ids. **Bad:**<br>• Message counts read **every** `reference_conversation` thread (`C:1614-1625`, 500 per page, until exhausted) to badge 24 cards. A per-lineage reader, `loadReferenceConversationCountsFor`, exists but is unused.<br>• The Cyclotron status loaders read every payload attachment of the Cyclotron and download each from S3, to keep only the newest; shadow and site-section read the same owner twice (`C:4278-4300`).<br>• **Unfiltered realtime subscriptions** on SemanticRelation create, update and delete (`W:1576-1583`): every relation written anywhere reaches every open tab. | Feed: about 2-5 requests, flat. Counts and Cyclotron grow with the site. | Each visit; feed pages on scroll; subscriptions while the tab is open. |
| 8 | **Messages** (`/newsroom/messages`, `components/conversations-view.tsx`) | 6 lanes × 20 threads, from an index (`listMessageThreadsByKindAndUpdatedAt`). Then **N+1** enrichment: a Reference and its attachments for each Reference thread, and a version list for each story thread. The workspace also loads 50 Messages that this view never shows (`W:1400`). | About 6 + 2-4 per thread shown. | Mount; on focus after 60 s. |
| 9 | **Proposals panel**, concept editor (`components/proposals-panel.tsx`, `components/section-concepts-editor.tsx`) | A scan of Proposals (500 per page, up to 20 pages) on mount and after every action. `searchConcepts` on every keystroke, with no debounce. | Grows with every proposal ever filed. | Mount; each action; each keystroke. |
| 10 | **Story detail, apart from the trail** | Bounded reads:<br>• `Item.get` and `PublishedItem.get`.<br>• Media by item (indexed), then one URL per image.<br>• Editorial feedback by item (indexed).<br>• Checklist sub-tasks by parent (indexed, 100 per page).<br>• `deriveMarkus` 600 ms after an edit, `checkEditorial` 2 s after an edit. | A handful of indexed requests. | On open and after edits. |
| 11 | **Shell** (`components/news-desk-client-provider.tsx`, in `app/newsroom/layout.tsx`) | One stored summary payload (`getNewsroomSummary`), a session refresh, and the user directory for admins. | 2-3 requests. | Once per visit to `/newsroom`; client navigation keeps it. `NewsroomOpsShell` also fetches `/api/auth/prospectus/session` twice on every navigation. |

Also found:

- **Subscriptions.** Apart from row 7, the only other subscriptions are in `SemanticDetailPanel` (`W:8695`), which nothing renders.
- **Dead code.** `OverviewDeskView` (`W:3427`), `ReferencesDeskView` (`W:6510`) and `SemanticDetailPanel` (`W:8515`) are never rendered.
- **A paging bug in `loadNewsroomFeedPage`** (`C:3695-3762`). It reads up to 10 inner pages until it has `limit` matches, then returns `items.slice(0, limit)` with the cursor of the last page read. When one call collects more than `limit` matches over two or more pages, the extra matches are skipped for good. The assignment feed and the 50-message read both go through it.
- **No cache across tab routes.** Nothing caches across the workspace tab routes: no SWR, no React Query, no module cache, apart from the KnowledgeCorpus ids and a 60 s message head start. Display snapshots in local storage paint the last view first but save no reads.
- **The board header's record count** is the number of cards loaded, not the number of stories.

## What this PR changes

Two slices. Both are front-end only, need no schema change and no deploy of a backend, and keep today's behaviour wherever their precondition is missing.

### 1. Board columns read the head stage index (PPY-52f3da, step 5 of the head-index plan)

- **New pure module.** `lib/story-stage-query.ts` holds the column paging with the GraphQL call passed in. It has two modes:
  - `head` reads `listItemsByHeadStageAndUpdatedAt` with only the story-type filter, asking for exactly a page.
  - `stage` is today's query and filter, unchanged.
- **The switch.** `lib/story-stage-mode.ts` picks the mode. It uses the head index only when the site's brand sets **`storyHeadStageIndex: true`** (`lib/site-brand.ts`). A site sets it once its backend has the index and `papyrus stories head-index` (dry run) reports nothing left to write.
- **Why a site setting rather than detection.** Writers have kept the head key on every save since that deploy, so after the deploy and before the backfill a column would show only recently saved stories. Nothing the browser can cheaply check tells "filled" from "partly filled".
- **Fallback when the index is missing.** If the backend answers that the index does not exist (an older data deploy), the board drops back to the stage index for the rest of the session. Any other error is shown as before.
- **Refresh.** On the head index a changed row stands for its whole story, so `applyChangedVersions(..., { oneRowPerLineage: true })` removes every loaded row of that lineage. A story saved as a new version in another stage then shows once, in its new stage. Without the flag the merge replaces rows by id, exactly as before.
- **Not for shared stacks yet.** On a shared (multi-tenant) stack the head key is tenant-prefixed, and the browser does not know its tenant yet. The setting's doc says to leave it unset there.
- **Measured** with the fake index, 30 stories each published five times:
  - the head index reads **25 rows in 1 request** for the first Published page;
  - the stage index reads **150 rows** to fill the same column.
- **Specs:** `features/newsroom-board-head-index.feature` (was `@wip`, now five passing scenarios; `npm run test:board-head-index`).
- **To turn it on for MoM** (backfilled 2026-11-10, 267 heads): set `storyHeadStageIndex: true` in `publication/brand.ts` in the Machines-on-Machines repo with the Papyrus version bump that carries this change. Other sites follow after their backfill.

### 2. Opening a story no longer reads the whole relation table

- **Newest version.** The editor asks for the newest version with `loadNewestStoryVersion`: `listItemsByLineageAndVersion`, newest first, `limit: 1`, so **one request and one row**. Before, it loaded the entire reporting trail to read `versions[0]`.
- **References.** The trail reads the story's References from `listSemanticRelationsBySubjectState` with key `item#<lineage>#current`. That is the read `papyrus stories references` already makes (`story_reporting.story_references`). Before, it paged through every relation in the site.
- **Result.** An open now costs one trail load, not two, and that load has no relation scan.
- **Still left:** the trail's MessageThread scan. Threads anchored to the story's assignments, and console threads anchored to it, carry keys the anchor index cannot find by story. It needs the index in the design below.
- **Specs:** `features/story-open-reads.feature` (`npm run test:story-open-reads`).

## Design: paging and lazy loading everywhere

### Rules

1. **Query what is displayed.** Every list reads an index whose partition is "this list" and whose sort key is the display order, one page at a time: 25 for the board, 24 for feeds. User-interface code never loops `while (nextToken)` over a table or a site-wide partition. Loops are allowed only over one owner's partition (one story's versions, one thread's messages), with a cap.
2. **No filter that throws away most of what it reads.** If a filter discards more than it keeps, the data needs a sparse key or a narrower partition (as `headStageKey` did for stages).
3. **Detail loads on open, per tab.** A drawer loads its header row. Each tab (versions, References, messages, checklist) loads when it is shown, from its own index.
4. **Refresh is "changed since"** on an `updatedAt` sort key. It runs on one timer per page, only while the tab is visible (`lib/board-refresh.ts startBoardRefresh` is the model), and after the user's own edits. No realtime subscriptions, following the standing rule.
5. **Cache and revalidate.** A small module-level cache in `lib/` holds each list's loaded pages. It is keyed by query and variables and lives for the session, because `app/newsroom/layout.tsx` survives client navigation.
   - On remount, the page renders from the cache at once, then revalidates with a changed-since read (or the first page, where there is no `updatedAt` key).
   - Entries older than 5 min, or touched by one of the user's own writes, are revalidated before use.
   - This replaces the per-tab whole reads that tab remounts repeat today.
6. **Counts come from stored counters, not from loaded rows.** The board's column counts and record count come from the newsroom summary payload, which is computed once on change, not from the cards loaded.

### Per surface

| Surface | Design | Schema and index implications |
| --- | --- | --- |
| Board story columns | **Done here.** Per-column cursor paging on the head index, 25 at a time, with load more on scroll to the column's end (Kanbus `onColumnNearEnd`, already wired). Follow-ups:<br>• a visible "Load more" button at the foot of a column, for keyboard users;<br>• stored column counts;<br>• dropping the three legacy stage keys once `papyrus stories head-index` shows no head in them;<br>• removing the superseded filter and `latestVersionPerContentItem` once every site reads the head index. | None for dedicated stacks: the index exists and is filled per site by `papyrus stories head-index --apply`. Shared stack: the console must know its tenant id to read `<tenant>#<stage>`, from site config or the Prospectus account (`lib/tenant-keys.ts tenantScopedValue`). |
| Board assignments | The Stories board stops reading assignments site-wide. It asks only about the lineages on screen: one aliased request per 25 shown lineages on `listAssignmentsByItemLineageAndCreatedAt`, the same batching as Reference predictions. The Assignments board pages each status column with `listAssignmentsByStatusAndUpdatedAt`, 25 at a time, and refreshes changed-since on its `updatedAt` key. Fix the `loadNewsroomFeedPage` slice bug, or retire it with this change. | None: both indexes exist. Optional later: an open-assignment count on the head Item, written by the assignment writers, so a card needs no assignment read at all. |
| Story detail | The editor loads the item and the newest version (done). Each trail tab loads its own data when shown: versions by lineage; References by subject state (done); threads by anchor lineage. The 30 s research poll reads only the assignment row. | **One GSI on MessageThread:** `primaryAnchorLineageId` + `updatedAt`. Alternatively, writers set `primaryAnchorKey` to the story key on assignment and console threads anchored to a story. One GSI per table per deploy. |
| Stories list and search | A server-side `searchStories` query, built like `searchReferences` (word index, 24 per page, cursor). The live article list (`lib/newsroom-articles.ts loadArticleRows`, today reachable only with `?demo=1`) reads `PublishedItem` by type and status one page at a time, not every pair until exhausted. | A story word index, like the Reference word index (title and deck words of the head row only, under the "text in S3, catalog in DynamoDB" rule). It is written on head change through the existing stream path. One new model or GSI. |
| Topics, Desks, Concepts, Administration | Delete `loadEditorFullNewsDeskDashboard`. Each tab loads what it shows:<br>• categories by set (`listCategoriesBySetAndKey`);<br>• proposals by status (`listSteeringProposalsByStatusAndProposedAt`);<br>• topics and concepts by corpus (`listSemanticNodesByCorpusAndNodeKey`), paged;<br>• the graph view reads one node's neighbourhood by subject and object state indexes when a node is opened, never all relations, References, attachments and Messages. | Mostly none: those indexes exist. Check whether a topic list needs a `nodeType` partition; if topics are a small fraction of SemanticNodes, a sparse key such as `topicKey` instead. |
| Notification Center | Use `startBoardRefresh` (a visible-only timer, 5 min). Overdue escalation moves to a backend scheduled job: a reader view writes nothing. Requests are read by state, newest first; read marks by user. Story titles come from the head row (title fields only), not every version's body. | **Two GSIs, one per table:** ReviewRequest `state` + `updatedAt`, and ReviewReadMark `userKey` + `readAt`. Neither table has any index today (`amplify/data/schema.ts:1535-1567`). |
| Search tab | Drop the unused `loadAllEditorReferences` call on the search tab. The References list view pages by status index, 24 at a time, instead of reading all four statuses until exhausted. | None. |
| References tab | Message counts for the shown lineages only (`loadReferenceConversationCountsFor`, which exists). Cyclotron status reads the newest payload attachment, `limit: 1`, newest first, with one S3 download, and reads it once for shadow and site-section. Remove the SemanticRelation subscriptions, and filter or remove the Reference ones; refresh changed-since on a visible-only timer. | Only if the attachment sort key cannot order by newest: an `updatedAt` sort key on that index. |
| Messages | Batch the enrichment: one aliased request per page for References, and the head row per story from the head index. Remove the workspace's unused 50-message read. | None. |
| Proposals, concept editor | Page proposals by status (index). Debounce concept search by 250 ms. | Proposal `status` + `createdAt` GSI if Proposal has none. |

### Order

Each step is small and ships on its own:

1. This PR. Then set `storyHeadStageIndex` on MoM with its bump. Other sites follow after their backfill.
2. Board assignments for the shown lineages only, plus the feed slice fix. Front end only.
3. Topics, Desks, Concepts and Administration per-tab loaders. Front end only. Biggest win.
4. Search tab and References list view; References tab message counts and Cyclotron status; drop the subscriptions. Front end only.
5. Notification Center: visible-only timer and the backend escalation job. Then the two review GSIs, one data deploy, which needs Ryan's approval per site.
6. The MessageThread anchor-lineage GSI and lazy trail tabs. One data deploy.
7. Server-side story search. New index and writer.
8. The session cache with revalidation (rule 5), once the per-surface reads above are small enough that caching them is worth it.

## What could not be verified

- **No browser measurement.** No Playwright request count was taken against a running console. The local preview (`npm run dev:preview`) serves seeded data without GraphQL, so it has no requests to count, and the live site was out of bounds. Request counts here come from the code and from the two fake-backend meters.
- **Table sizes are estimates.** Sizes other than MoM's stage partition (580 rows, 456 superseded) and its 267 heads are estimates; the relation, thread, assignment and review counts were not measured.
- **Tab remounts are inferred.** That every workspace tab navigation remounts the workspace comes from how Next keys route segments. It was not observed in a browser.
