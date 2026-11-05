# Public blocks that ask an index for what they show (PPY-7f1e54)

> Status: design, for Ryan to read before anything is built. Nothing in this page is implemented. It replaces no behaviour until a site opts in.

## The short version

Today the public pages are made from one file, `_data/home-page/references.json`, that holds every Reference a site might show. Machines on Machines has 4,555 rows in it and Anth.us has 3,373. A first run or a rebuild reads all of them from AppSync, one decision and one preview per row, and every block then picks its few cards from the file in memory.

The design below throws the file away as an input. Each block asks an index for exactly the rows it shows, in the order it shows them, and each row already carries everything its card needs. A change in the table arrives on the DynamoDB stream with the old and new copy of the row, and that is enough to say which blocks it can touch, without reading anything. Only those blocks run their query again.

What it takes:

- **One new index** on `Reference` (`publicFeedKey` and `publicOrderKey`), sparse, so it holds only rows that can be public: accepted ones, and pending ones with a real prediction of at least 0.5.
- **Four plain attributes** on the row: `cardImage`, `cardSummary`, `cardSiteName` (copied from the preview when it is captured) and the two index keys.
- **Everything else already exists**: `curationStatusKey` for the accepted list by time, `feedStateKey` with `predictionSortKey` for pending by prediction, `starFeedKey` for starred rows, `mediumFeedKey` for videos, and the thread indexes.

The measured result, on today's two sites (details in [What it costs](#what-it-costs)):

| | Today | This design |
| --- | --- | --- |
| Whole-site render from nothing, Machines on Machines | about 8,200 AppSync requests (4,555 rows at about 1.8) | about 21 |
| Whole-site render from nothing, Anth.us | about 6,100 (3,373 rows at about 1.8) | about 29 |
| One new, low-confidence Reference arrives | 4 requests, then the 4.6 MB file and every page that places a Reference are written again | 0 requests, no page written |
| One Reference is accepted | 4 requests, then the file and every such page again | about 1 request per block it enters (a few), only those pages written |

Both "today" numbers are lower bounds: a full read also reads the decision of every pending row predicted below 0.5, and public data cannot tell me how many there are.

One finding changes the shape of the answer, so it comes first.

## What I measured, and why it forces day partitions

I read the two public snapshot files as they are served (public URLs, no AppSync). Both sites are young, and a handful of bulk days hold almost everything:

| | Machines on Machines | Anth.us |
| --- | --- | --- |
| Rows in `references.json` | 4,555 (76 accepted, 4,479 recommended) | 3,373 (71 accepted, 3,302 recommended) |
| Rows that arrived in the last seven days | 4,009 | 3,031 |
| Recommended rows on the busiest single day | 2,265 | 1,773 |
| Rows with an image, with a summary | 3,217 and 3,612 | 2,540 and 2,769 |
| Rows with a stored prediction | 4,382 | 3,360 |
| Starred rows | 43 | 0 |
| Bytes per row in the file | about 1,030 | about 1,020 |
| Threads, public Messages | 2 and 2 | 6 and 7 |

The idea in the ticket was a sparse index sorted by arrival, read for the current window and sorted in memory. That is right for accepted Reference. A window of accepted rows is what editors accept in seven days: tens. It is wrong for recommended ones. On Machines on Machines a seven-day window holds 3,933 recommended rows, so "read the window and sort it" is 40 requests for one block, per render, and 90 percent of the table. The block needs the three or six most confident rows of the window. So the new index is partitioned by day and sorted by confidence: the top six of a window is one small query per day in it, whatever the day holds.

(The live files still carry about 170 and 10 rows with no prediction. The fix that stops showing them, PR #1227, is merged to develop and not released yet. The tables above count what is served today.)

## What a public row is

A `Reference` row gets five new plain attributes. They are written by the code that already writes the row, at the moment the fact becomes known, and never recomputed on a schedule.

| Attribute | What it holds | Written when |
| --- | --- | --- |
| `cardImage` | The address of the card image, decided: the preview image address, or for a video our own thumbnail copy (the existing `public_image` rule), or the picture an editor chose. Empty when there is none. | The preview is captured, an editor chooses a picture, or a video thumbnail is copied |
| `cardSummary` | The preview's description, scrubbed, not clipped. The clip to `publicData.summaryCharacters` happens when the card is drawn, so a site that changes its length changes nothing in the table. | The preview is captured |
| `cardSiteName` | The preview's site name, scrubbed | The preview is captured |
| `publicFeedKey` | The partition, see below. Empty (the attribute absent) unless the row can be public. | Whenever a vote, a prediction, an archive or a new version changes the facts it is made from |
| `publicOrderKey` | The sort key, see below | Same |

Prediction is already on the row (`predictedAcceptProbability`, written once and, since PR #1230, requested when a Reference is created). The title, address, authors, dates, medium, section id and star count are already on the row too. After this, a card can be drawn from the one row the index returned, with no decision request and no preview request. Public fields stay the allowlist in `export.py`; the private ones (who decided, who rated, intake provenance) are still never copied into anything a page can show. The new attributes hold nothing private, and the star count stays on the row exactly where it is.

### The one new index

`Reference` gets one new global secondary index: partition `publicFeedKey`, sort `publicOrderKey`, query field `listReferencesByPublicFeed`. It is sparse, so a row without the keys is not in it and never costs a read.

The key is built by one pure function (`public_feed_keys(row)`, with a TypeScript twin and shared test vectors, the way `feed_keys` already works):

- A row that is not the current version, or is rejected or archived: no keys.
- An **accepted** row: partition `<corpus>#accepted`, sort `p<probability>#<arrival>#<id>`, or `n#<arrival>#<id>` when it was never scored. `p` sorts above `n`, so the scored come first and the unscored last, which is the rule PR #1227 put in `ordering.py` (an unscored row is not 0.5).
- A **pending** row whose stored prediction is a finite number of at least 0.5: partition `<corpus>#recommended#<UTC day of arrival>`, sort `p<probability>#<arrival>#<id>`.
- A pending row with no prediction, or a prediction below 0.5: no keys. That is the whole of "only predicted or accepted rows are ever public": the rest never enter the index.

The probability is six decimals, as `predictionSortKey` already does it. A row's day and probability never change while it is pending (the prediction is written once, and arrival is fixed), so a pending row's keys are written once and cost no further index writes until a vote moves it to `#accepted` or clears it. Star ratings are not in either key: they change often and are private, and the star index already serves them.

The index is sparse and the partitions are small relative to the table: accepted rows are the editorial throughput, and a day partition holds one day of pending rows.

## Every read a public page needs

`c` is a block's `count`. `p` is how many References the page already placed (the page ledger skips them), so a block asks for `c + p` rows. A request returns up to 100 rows, as the AppSync client reads today; "1" means one page of 100. A superseded or archived row can still sit in an older key partition, so rows are checked for `versionState` current after reading, as `current_references` does today; the index writes of the design clear the key on supersede, so this is a guard and not a filter that hides work.

| Block | What it asks | Index | Requests per render |
| --- | --- | --- | --- |
| `select=recent`, no bucket (Anth.us, Machines on Machines) | accepted rows, newest accepted first, `c + p` of them | existing `curationStatusKey`, sort `curationStatusUpdatedAt`, partition `<corpus>#accepted`, descending | 1 for up to 100 |
| `select=recent` or `select=confident` with `bucket` (accepted rows) | accepted rows whose accepted time falls in the window being filled, newest window first; sorted by stars then confidence in memory | the same index, with a sort-key range on `curationStatusUpdatedAt` | 1 per window, usually 1 (tens per week); one more window only if the first leaves the count unfilled |
| `select=confident`, no bucket (Anth.us) | accepted rows by stars, then confidence | **new index**, partition `<corpus>#accepted`, descending | 1 |
| `select=recommended`, no bucket (both sites) | pending rows by prediction, highest first, stopping at the site's threshold | existing `feedStateKey` partition `<corpus>#unrated`, sort `predictionSortKey`, descending; a row with no `predictedAcceptProbability` is skipped (it sorts at `0.500000`, at the very bottom of the range read) | 1 for up to 100 rows |
| `select=recommended` with `bucket` | the best rows of the current window, then the next window | **new index**, one query per day in the window (7 for `week`, 1 for `day`), each asking for `c + p` rows by confidence, merged in memory | 7 per `week` window, 1 per `day` window |
| `medium=video` | videos only | existing `mediumFeedKey`, partition `<corpus>#video#accepted`, sort `feedArrivalAt` | 1 |
| `section=` | the section filter | no index. The block reads its list as above and keeps reading until it has `c`, dropping rows of other sections. Note that on both sites today no row has a section label (every record's `section` is empty), so I could not test this path on real rows. | 1 per 100 rows read; unbounded in principle, see [Risks](#risks-and-what-i-could-not-determine) |
| Section front (`index.references`) | the same block as above with `section=` set | as above | as above |
| `paged="true"` list (the wire) | the whole selection in order, cut into chunks | the same indexes, read to the end | `rows / 100` for the whole list, see [Paged lists](#paged-lists) |
| `kind=threads select=recent` | the most recently active public threads | existing `messageThreadsByKindAndUpdatedAt` for each of the two public kinds, newest first; for each candidate, its Messages from `messagesByThreadAndSequence`, and whether its anchor Reference is public (below) | 2 for the lists, plus 2 per thread read (its Messages, its anchor), plus one profile read per distinct author handle |
| Thread page (forum) | one thread | the thread's own row, its Messages, its anchor Reference by lineage (`listReferencesByLineageAndVersion`) | 3 to 4 |
| `kind=listing` (Stories) | not through `references.json` | the Story table, read by the projector's own site index | unchanged by this design, see below |

Stars. The order inside a window or a list is "3 to 5 stars first, then unrated by confidence, then 1 and 2 stars". A starred row is placed by its stars wherever it arrived, so it cannot be found by confidence. The star index (`starFeedKey`, one partition per level, sorted by arrival) holds exactly the starred rows. The task reads the five star partitions once per run (5 requests, memoized across every page, so the cost does not grow with pages; Machines on Machines has 43 starred rows, Anth.us none) and a day-partition read drops the rows it knows are starred, so that each row is placed once. This keeps the private star count out of every key and out of every public file; a page's digest is taken over the public records it places, in the order they sit.

The threshold. `homePage.references.recommendedThreshold` defaults to 0.5, and no site sets it. A higher value works for free: the confidence order stops reading at the threshold. A value below 0.5 cannot be served by a sparse key that starts at 0.5, so the index path refuses it with a build error that names the setting.

Threads. The two live sites have 2 and 6 threads, so this is a small part of any render. The one new question is "is the anchor Reference public", which today is answered from the in-memory snapshot. In the design it is answered by reading the anchor row by lineage and checking that its keys are set. That is one request per thread read, and a thread page already needs that row to draw the anchor card.

Story listings. `::include{kind="listing"}` and the section and archive pages read Stories through the projector's site index (`list_records("PublishedItem")`), a full read of the Story table on every projection. That is independent of `references.json` and I have not changed it here: the Story count is small compared with the Reference count, it is needed whole for the sitemap and tag pages, and `PublishedItem` already has `typeStatus` and `sectionStatus` indexes sorted by `publishedAt` for a later change that makes a single listing a single query. It is listed under [Not in this design](#not-in-this-design).

### Paged lists

A paged list shows the whole selection, so some part of every row has to be written to a file. What the design changes is what a change costs.

- **Whole list**: the chunks are cut from the ordered keys (`chunks.py`, unchanged), and each chunk's cards come from the rows the same query returned. For `recommended` that is `rows / 100` requests (45 for Machines on Machines' 4,479). Today it is the whole file.
- **A change**: both the recommended order (original prediction, fixed) and the accepted order (accepted time, fixed unless a row is re-accepted) are keys that do not move after they are set, so a changed row's position is known from its keys alone. The task keeps each list's chunk layout (the chunk names and the sort key each starts at, a few hundred bytes for a hundred chunks) in the lock table. A change reads the range of the index from the previous chunk start to the next chunk start (1 to 2 requests), recuts from the known start, and stops when a cut lands on an old start again. This is the same property `chunks.py` already has, now used to bound the read as well as the write.

This is the least obvious piece of the design and the one I would build last. A paged list is also the one block whose whole-site render is proportional to the table, and no design avoids that: its chunk files have to contain every row.

## How a change reaches the pages

The DynamoDB stream trigger stays. What changes is what it remembers.

1. The trigger gets the old and the new image of a row. For each change it records a small coordinate instead of only an id: the row's key, its `publicFeedKey` and `publicOrderKey` before and after, its accepted time, its star count before and after, and a hash of its card fields (title, image, summary, site name, medium, section). That is a few hundred bytes, larger than an id, so the one-item limit on the changed set arrives sooner than today's 2,000. When it overflows, the task does not read the corpus: it treats every block as touched, which re-renders every page that places a Reference (about 21 and 29 requests on the two sites).
2. After the debounce the task loads one small record per block that a page places: the keys of the rows it placed and the order coordinates of its last row (its frontier), or a flag that it came up short. These are written whenever a block is rendered. They are in the same lock table as today's state, a few hundred bytes per block.
3. For every change the task asks, in memory, of each block: was the row in its placed set (then the card or its place changed, so re-render), or does its new coordinate sort ahead of the block's frontier (then it enters), or is the block short and the row matches its filters (then it enters)? A row that touches no block is dropped. That is the usual case: a 0.62 recommended row does not reach a block that shows the top six by confidence, or the top 500.
4. The pages with at least one touched block are the "readers" that `project_stale_listings` already takes. Each is rendered again: its blocks run their queries (the table above), the page digest is the digest of the public records the page placed, in order, and the page is written only when that digest changed. A page whose blocks nothing touched is never queried.

So a change costs nothing to decide, and the cost it does have is the queries of the blocks it touched, once per page, shared between pages that ask the same query in the same run.

A state record that is missing, written by another build, or does not match is not repaired: the page is simply treated as touched. There is no "read the whole corpus once to start a state" step any more. A block's record is rebuilt as a side effect of rendering it.

The rolling windows add no job. A day crossing moves a row to an older window, which changes a page's order; that is the "quiet-page lag" Ryan accepted on 2026-11-05 (a page whose order the day changed catches up the next time anything re-renders it). The design does not make that worse: a window is a set of day partitions counted back from the render's day, so the queries are right whenever they run.

## References.json: can it go

Yes, for the pages. I looked for every reader.

| Reader | Where | What happens |
| --- | --- | --- |
| The `references` include and the Markdown twin | `home_page_blocks.py` through `HomePageSource.references()` | Reads from a source object instead of the file. A site that has not opted in keeps the file source; an opted-in site gets the index source. The tile, the row, the stars (`data-stars`), the confidence meter and the "Recommended by Cyclotron" label are drawn by the same `home_page_components.py`, from the same public record shape, so their HTML does not change. |
| Paged lists | `projector._paged_list`, `home_page_lists.py` | Candidates come from the index source (above). Chunk names and files are unchanged. |
| Thread pages, anchor card | `projector._public_threads` | The anchor Reference record comes from the one row read for the thread page, instead of the file. |
| Page digests and `home_page_reader_keys` | `projector._home_page_inputs` | A page's digest is over the records it placed, not over the whole file. The set of pages that read the home page is still derived from the authored sources. |
| Page twins, `llms.txt`, `llms-full.txt`, sitemap | rendered output of the above | Follow the pages. No separate reader. |
| `papyrus home-page snapshot` CLI and the `home-page-snapshot` task | `task.py`, `commands.py` | Becomes the render task: with `--dry-run` it prints the blocks it would query and the pages it would touch. |
| The private state in the lock table | `state_store.py`, `incremental.py` | The per-row `Standing` shards go. The block records above replace them, and they are small. |
| Alexa, feeds, newsletters | `amplify/plugins/alexa` reads the newsroom through AppSync; `feeds.py` is Stories | Do not read the file, so nothing changes. |
| A site hook | Machines on Machines `web/hooks.py` | It rewrites the stock `<article class="home-page-tile">` markup in `page_finish` and reads no JSON. I checked every `web/` directory I have for `home-page/references` and for the tile classes: only that one hook touches the tile, and it sees the same HTML. A custom hook sees no break because the thing it reads is the rendered tile, which this design keeps byte for byte. |
| An outside reader of `https://<site>/_data/home-page/references.json` | unknown | I cannot know. It is public, and the docs describe it. See the decision below. |

The file also has a cost of its own: 4.7 MB and 3.4 MB on the two sites, rewritten on every change that moves a rank, which is almost every change.

## Staging

A deploy may add only one global secondary index per table, and the design adds one. The release order, per site:

1. **Release A, all sites, nothing visible.** The five attributes are added to `Reference`, no index. The writers learn to fill them (`reference_images.attach_preview` and the other places that write a preview attachment, the editor picture chooser, the video thumbnail copy, and every writer that moves a Reference between votes: the same list as the existing keys in `reference-feed-indexes.md`). The home-page trigger starts recording coordinates next to ids, and ignores a change to the new attributes alone. A site that has not opted in renders exactly as before.
2. **Backfill, per site.** One command, `papyrus references backfill-public-fields --site KEY`, run once. Cost below.
3. **Release B, all sites.** The index alone, as the medium and content-needed indexes were.
4. **Release C, all sites, nothing visible.** The index source, the block records, the render task. `homePage.references.source` (`snapshot` by default, `index`) is new in `projection.json`.
5. **Per site, one at a time.** Machines on Machines first, then Anth.us (the one that gets caution, as always). Before the flip, a parity command renders the site's pages from the file and from the index into two scratch directories and compares the HTML of every page that places a Reference (a differing page is listed with the first differing card). The flip is one line in `projection.json`. After it the site's file is no longer written.
6. **Later**, when every site that places References has flipped: the file source and the old state code are removed in their own change.

Per the batching rule, steps 1 to 3 go to the site under test first and are rolled to the rest in one batch once the site works. A site with no references include only carries the attributes and the index.

What stays the same for a site until it opts in: everything it renders and writes. The attributes and the index are additive; the old task and file keep running. Changing all sites at once is possible after step 3 because the code is selected by a setting, but I recommend the flip stay per site, because the parity command costs a full read and the two sites that use it are the only ones that need it.

## What it costs

**Per-render numbers** use the table above. Machines on Machines:

| Step | Requests |
| --- | --- |
| Home: `recent` 3, `recommended` 3 | 1 + 1 |
| Wire: `recent` 500, `recommended` 500 | 1 (76 accepted rows) + 5 |
| Stars, once per run | 5 |
| Section labels, once per run | 1 |
| Threads (2 threads, 1 author) | 2 + 4 + 1 = 7 |
| **Whole site from nothing** | **about 21** |

Anth.us, `newsroom` page (`recent` 6, `confident` 6, `recommended` 6) with its 6 threads: 3 for the blocks, 5 for stars, 1 for sections, about 20 for threads, so **about 29**. If the wire were a paged list on Machines on Machines, its recommended list is 45 requests for all rows, so that site would be about 62.

Today's whole-site number is the full read: the two rows lists, one decision per listed row and one preview per shown row. At about 1.8 per Reference, **8,200** and **6,100**, plus the same thread reads (about 7 and 20), plus section labels. It happens on the first run of a site, whenever the stored state is refused (every format bump, such as the one PR #1227 made, forces it), on every manual run and on a mass import.

**Per change.** Today every change that is public is 4 requests (the section list, the row, its decision, its preview), then a 4.6 MB file written, then every page that places a Reference written again, because rank positions shift when a row is inserted. In the design, deciding costs 0. A row that touches no block costs nothing at all; one that touches a block costs about 1 request per touched block (2 for a threshold-sized refill), shared between pages that ask the same query. On Machines on Machines, with a typical day of mostly 0.6 to 0.9 rows arriving, nearly every arrival touches no block.

**Backfill, once.** Public rows only (about 4,555 and 3,373 today). Each needs its preview attachments read (1 request) and its row written (1 mutation), plus the list pages (46 and 34), so about **9,200** and **6,900** requests, once per site, about the same as one of today's full reads and never again. Non-public rows (rejected, unpredicted, below 0.5) are not touched; they get their card fields the moment their preview is next captured, or never, which does not matter because a page cannot show them. Writing the keys makes DynamoDB build the index from the rows that carry them, so doing the backfill before Release B means the index is complete the moment it is active.

**Ongoing.** One extra field set written per new Reference at capture (the card fields), merged into the row update that already happens when the preview is attached where possible, otherwise one more mutation per new Reference. On a bulk day such as the 2,265 on Machines on Machines this is up to 2,265 more mutations; it replaces the per-row decision and preview reads that the full read made for the same rows.

## Alternatives that were seriously in play

1. **The ticket's first idea: a sparse index by status sorted by arrival, one window read and sorted in memory.** Right for accepted rows (a window is tens of rows, and the existing `curationStatusKey` index already serves it). Wrong for recommended rows: a seven-day window holds 3,933 rows on Machines on Machines and 2,997 on Anth.us, which is 40 and 30 requests for one block. It would work on a mature site and fail on the sites we have. Day partitions sorted by confidence make the window cost one small query per day whatever the day holds.
2. **Keep the rows' keys current from the stream trigger instead of from every writer.** One place computes the keys and the card fields; no list of ten writers to edit. I did not choose it because the trigger has no dead-letter queue (a batch that fails twice is dropped), so a failure would leave a row invisible with nothing to say so, it adds a second write to the row for every change, and the existing four indexes all use the writers. The cost of the chosen way is that each writer has to carry the new keys; the existing creation-paths test and a shared vector file catch a writer that forgets.
3. **Keep `references.json` but build it from the indexes.** Removes the per-row reads, not the size: the file would still be 4,555 rows, rewritten on every rank shift, with a gap that grows with the table. This is the "whole file" design with a cheaper input, and the paged chunk files already prove that the block does not need the file.
4. **Two indexes, one for all-time confidence and one for day windows.** The existing prediction index already gives all-time recommended, and the accepted list is small enough that one partition of the new index gives all-time confident. One index with two key shapes (an accepted partition and a day partition) covers both without a second deploy.

## Not in this design

- Story listings and the Story table's full read per projection (above).
- A relation stream so that a re-decided Reference moves a card (the "known limit" in `home-page.md`). This design reads the stored prediction, which is what the index sorts by, see the decisions.
- A second index for the section filter. Only worth it once a section block is measured to read many rows.

## Risks and what I could not determine

Risks:

- **Writer drift.** A writer that changes a vote or a prediction and does not move the keys leaves a row in the wrong partition or out of the index, and the page would silently miss it. The same risk exists for the four indexes that are already in, and the answer is the same: one shared function, shared vectors, the creation-paths test, and the parity command before each flip. A repair command (`backfill-public-fields`) can be run again by hand; nothing runs on a schedule.
- **The index is eventually consistent.** A query right after a write can miss the row. The debounce is minutes and a run that read stale shows nothing wrong for longer than the next change, but a block that reads in the same second as a vote could miss it until the row next changes. In practice the stream event that triggered the run comes after the index update.
- **A section block on a rare section** reads until it has its count. On a mature site with a rare section that could be many pages. It is bounded by the table and not by anything I chose, and I would rather measure it than add a second index in advance.
- **Starred rows** are read whole, five partitions per run. Fine at 43. Editors' stars grow with the corpus, and past a few hundred they would be pages of their own.
- **Item size.** `cardSummary` is stored unclipped. A description from page metadata is a few hundred characters; a row is nowhere near the 400 KB item limit, but I did not look at the longest one.
- **A mass import** marks blocks instead of forcing a full read. A day of 2,000 arrivals that all enter a block costs that block a re-query, not 2,000 reads. The changed set still has to fit in one item; past that, every block counts as touched (above).
- **The paged-list layout record** is new state. A missing one is not an error: that one list is cut again from the whole index, `rows / 100` requests.

What I could not determine:

- **The full-read number today is a lower bound.** The public file shows the 4,555 and 3,373 rows that are shown. The full read also reads the decision of every pending row with a prediction below 0.5, and the total of those is not in any public data. I used the ticket's 1.8 per Reference.
- **How many requests one AppSync page actually returns at a larger limit.** The client uses 100. If `limit` can be raised the counts for 500-item blocks fall; I counted at 100.
- **Whether `ModelStringKeyConditionInput` is available on the new query field the way it is on `listReferencesByVersionStateAndUpdatedAt`.** The existing index queries in this repo use it for a range on a sort key, and a model index generated the same way should offer it; I did not generate the schema to check.
- **Section fronts on real data.** No row on either site has a section label, so I could not see what a section filter returns or how many rows it would read.
- **Anth.us's own wire usage.** I have its three blocks (`recent`, `confident`, `recommended`, count 6) and no paged list; any list on another site could change the paged-list numbers.
- **Whether any outside program reads `references.json`.** Only the site's HTML is mine to check.

## Decisions for Ryan

1. **Which probability a card shows and a list sorts by.** Today a card shows the live decision's confidence when there is one, otherwise the stored prediction; the index can only sort by one value on the row. I propose the stored prediction (the Cyclotron's first one, never rewritten) for sorting and showing. That removes one request per row and changes nothing today, since the stored value is the decision's the first time and re-decisions are not seen by the pages until the row changes anyway. If you want a later re-decision to move cards, that is a separate change that writes a second field.
2. **What happens to the public file.** Remove it for opted-in sites (my recommendation: it is 4.7 MB of rows nobody on the pages needs), or keep a public file that is built from the first page of each list. I would remove it and say so in the release note.
3. **Where the keys are written.** In each writer (my recommendation, like the other four indexes) or by the stream trigger (alternative 2).
4. **A threshold below 0.5** becomes an error on the index path. No site sets it.
5. **Order of sites.** Machines on Machines first, then Anth.us.
6. **Paged lists last.** They need the layout record and are the one place a render is still proportional to the table. I would build everything else first and flip a site that has no paged list.
