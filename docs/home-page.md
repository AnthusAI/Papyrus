# Home page: public data files

> Status: Beta, phase 1 of the `homePage` epic (PPY-1b83d3). This page covers the data files, the fields, the task and the CLI. The Reference grids are described under "The references include"; the freshness trigger is described under "Freshness"; the Message threads are described under "Message threads".

A Papyrus site can show part of its curation to visitors. The first piece is a public JSON file of the site's accepted References and of the pending ones the Cyclotron expects an editor to accept. It is served next to the pages, for example `https://anth.us/_data/home-page/references.json`.

## Data files

| File | Holds |
| --- | --- |
| `_data/home-page/references.json` | `generatedAt`, `corpus`, `fields` (the published field names) and `references`, accepted ones newest-accepted first, then recommended ones newest arrival first; each record has a `rank` (see [Ordering](#ordering-human-ratings-then-cyclotron-confidence)) |
| `_data/home-page/threads.json` | With `homePage.threads.enabled`: `generatedAt` and `threads`, most recently active first (see "Message threads") |
| `_data/home-page/threads/<key>.json` | With `homePage.threads.enabled`: one file per public thread with its Messages in sequence |

The file lives under the site's URL policy, so `urls.basePath` is honoured (`<basePath>/_data/home-page/references.json`). Reconcile never calls it an orphan.

## Which References

- **accepted**: `curationStatus` accepted and `versionState` current.
- **recommended**: pending (`<corpusId>#unrated`) and current, whose live P(accept) is at least `homePage.references.recommendedThreshold` (default 0.5, the threshold the console already uses to skip predicted rejects). P(accept) is the console's `acceptProbability`: the confidence of the current `relevance_decision_is` decision when it chose the positive label, one minus it otherwise, 0.6 when no confidence was recorded and 0.5 with no decision.
- Rejected, archived and superseded References are never exported.

## Public fields

`key` (the first 12 hex characters of the SHA-256 of the lineage id, so no id appears), `status` (`accepted` or `recommended`), `title`, `authors`, `url`, `host`, `mediaType`, `sourceDate`, `sourceUpdatedAt`, `retrievedAt`, `importedAt`, `arrivedAt`, `acceptedAt` (accepted only), `decidedAt`, `section` (the section's title), `reasonCode`, `actor` (`human`, `cyclotron`, `rule`, `agent` or `catalog`; never who), `shareable`, `stars` (the editors' rating, 1 to 5, of an accepted Reference; null for a pending or an unrated one), `confidence` (live P(accept), two decimals), `predictedAcceptProbability` (the original prediction), `predictionDecidedAt`, `inboundCitationCount`, `outboundCitationCount`, `versionNumber`, `medium` (`video` or null: the stored medium, else what the address certainly says), from the preview attachment `image`, `summary` and `siteName`, and `rank` (a position in the shared order, below; always written, even when `homePage.references.fields` is a list that does not name it).

The allowlist is `PUBLIC_REFERENCE_FIELDS` in `src/papyrus_content/home_page/export.py`. `homePage.references.fields` is `"all"` (every field above, the default) or a list of those names that includes `key` and `status`; any other name is a build error.

Never published, each with its reason in `EXCLUDED_REFERENCE_FIELDS`: identity (who decided, who relayed, an editor's private note, intake provenance), who gave a star rating and when (the count itself is published as `stars` on an accepted Reference since 2026-11-04, see [Ordering](#ordering-human-ratings-then-cyclotron-confidence)), the captured text of the source and its storage details, and internal ids and keys. A unit test proves every field of the Reference model is either published or excluded, exactly once, and the Gherkin scenarios scan an export with the reader-privacy scanner. `summary` is the preview's description clipped at `publicData.summaryCharacters` (default 240) on a sentence boundary. Text is also scrubbed of anything shaped like an email address, a UUID or a site subject, and a Reference whose address would carry one in its path is left out.

## Settings

The `homePage` key of `projection.json`; a site without it has no home-page behaviour. Unknown keys are a build error that names the key.

```json
{"homePage": {"layout": "latest", "perSection": 4,
  "references": {"corpus": "knowledge-corpus-example", "fields": "all", "defaultCount": 6, "recommendedThreshold": 0.5},
  "threads": {"enabled": false, "authors": "handle", "anonymousLabel": "Editor"},
  "forum": {"threadBase": "conversations", "index": {"pageSize": 50}},
  "freshness": {"debounceSeconds": 300, "intervalHours": null, "purge": false}}}
```

`layout: "sections"` (with `perSection`, `homeLead` and `homeSections`) and the `urls.sections.<name>.index` setting are described in [Section index pages and a home of sections](building-a-papyrus-static-site.md#section-index-pages-and-a-home-of-sections); a site that does not set them is unchanged.

`references.corpus` defaults to the corpus of the site's publication key (`PAPYRUS_PUBLICATION_CORPUS_KEY` in the Lambda, `--site KEY` on the CLI).

## The task

`home-page-snapshot` runs in the content-actions function (`{"projectionTask": {"task": "home-page-snapshot"}}`). It runs in one of two modes, reported as `mode`, and a change costs requests in proportion to the change in the first and to the corpus in the second (see [Cost](#cost-a-change-is-read-not-the-corpus)). Under the projection lease it builds the document, writes the file only when its content changed (the `generatedAt` stamp alone is not a change), then re-renders only the listing pages whose inputs changed and, with `freshness.purge`, purges the file on the edge. A site without a `homePage` setting ignores the task. The report is `{written, unchanged, references, pagesRewritten, purged}`.

## The CLI

```bash
papyrus home-page snapshot --site KEY --site-bucket BUCKET --static-dir SITE/web --auth iam --amplify-outputs FILE
papyrus home-page snapshot --site KEY --out DIR          # a local directory
papyrus home-page snapshot --site KEY --dry-run          # counts and file size; writes nothing
```

Mutation commands write by default; `--dry-run` prints the report and the size of the file only. `--static-dir` points at the site checkout so its `projection.json` (including `urls.basePath`) applies; without it the defaults are used.

## Stories beside the Reference grids

A home page that interleaves Stories with the Reference grids uses the ordinary `listing` include. It can show a single Story type with `types` (any of) and `notTypes` (none of), for example `::include{kind="listing" sections="articles" types="article" count="1" card="text" layout="bare"}` for the newest article even when newer posts exist. A type is only selectable if `listings.types` lists it. Pages that do not use the attributes render exactly as before.

## The references include

`::include{kind="references" select="recent|confident|recommended" count="6" [bucket="day|week"] [section="Tools"] [medium="video"] [card="tile|row"] [heading="..."] [more="/path/"] [empty="..."]}` places Reference cards on an authored page, rendered at projection time from `_data/home-page/references.json`. A site needs the `homePage` setting; without it the include is a build error that names the page file.

- `medium="video"` keeps only the References whose `medium` is `video` (a videos block, [Videos on a public page](standard-site.md#videos-on-a-public-page)); any other value is a build error. A card with a medium shows it as a small label with a Lucide icon and the word ("Video"), except in a block that is itself filtered by `medium` (every card is that medium, so the label would only repeat); a block that mixes media keeps it.
- `recent`: accepted, newest accepted first. `confident`: accepted, in the shared order of an editor's rating and then the Cyclotron's confidence (below). `recommended`: not yet accepted, in the same shared order. Without a `bucket`, `recent` ignores ratings.
- `bucket="day"` or `bucket="week"` (any selection): the newest bucket first and the shared order inside each bucket. See [Time buckets](#time-buckets).
- `count` defaults to `homePage.references.defaultCount` (6). `section` keeps References whose section label (or a configured section name's label) matches.
- Each page has one ledger. The first component to place a Reference keeps it; a later component skips it and refills up to its `count` from its own ordering. Nothing is shared between pages.
- **An accepted Reference an editor rated shows its stars** (PPY-ba2f19), in place of any confidence: five Lucide `star` icons, one filled for each star given and the rest outlined (the shape carries the value, never the colour), and the words "4 of 5 stars" visually hidden for a screen reader. The mark is `<span class="home-page-stars" data-stars="4">`, and the tile itself carries `data-stars="4"` on its `<article>` (a row carries it on its `<div>`, with a compact mark), for a site that styles or reads it. A card with no `stars` value (unrated, pending, or a snapshot written before the count was published) shows no stars and keeps the confidence rules below. A recommended (pending) card never shows stars, even if it is rated.
- A card shows confidence as "93% confidence" with a Lucide `gauge` icon and a five-segment meter drawn by shape (filled or outlined), **except on a Reference an editor accepted**: once a person accepts it the Cyclotron's confidence no longer matters, so the card shows none ("Accepted by an editor" stays). A Reference accepted by a Cyclotron or a rule with no human vote ("Accepted automatically") keeps its confidence, and so does a recommended one. The record's `actor` field (from the Reference's `curationActorKind`: `human`, `cyclotron`, `rule`, `agent` or `catalog`) tells these apart, and the snapshot itself leaves `confidence` null for an accepted record whose actor is `human`; the cards also hide it for an older snapshot that still carries it. The order is unaffected: `rank` is computed from the row. A recommended card says "Recommended by Cyclotron, not yet accepted" with a `sparkles` icon. Cards use flat tones and rounded corners, with no borders. A component with nothing left draws the `empty` text, or nothing.
- The Markdown twin keeps the include line as written. A page's digest folds in the snapshot digest, so a changed snapshot rewrites only the pages that place a references include.
- `pages[].path`, a section `base` or a collection `base` equal to `_data`, `_plugins`, `_papyrus`, `_next` or `api` is a build error. `newsroom` is also reserved on sites whose edge routes the CMS.

## Ordering: human ratings, then Cyclotron confidence

A human rating is a stronger signal than a prediction, so where an editor rated a Reference the rating overrides the Cyclotron's confidence. `confident`, `recommended` and every bucketed include use one order (`src/papyrus_content/home_page/ordering.py`, tested in `ordering_test.py` and `features_backend/home-page-human-ratings.feature`):

1. three, four and five stars, the most stars first;
2. References nobody rated, the highest Cyclotron confidence first (none recorded counts as 0.5);
3. one and two stars, the most stars first. A low rating is a real downgrade: it sinks a Reference even when the Cyclotron is sure of it, and a high one lifts a Reference the Cyclotron doubts.

Equal References go to the newest arrival, then to the key. Pending References can be rated too, so `recommended` follows the same order. **Since 2026-11-04 (Ryan, PPY-ba2f19) the star count of an accepted Reference is printed** on its tile and row and published as `stars` in the snapshot; this reverses the earlier rule that stars changed the order and were never shown. A pending Reference shows its Cyclotron confidence instead (its rating still ranks it), and a Reference nobody rated shows no stars and, if it has one, its confidence. Who rated and when are never published.

**What the snapshot publishes, and what it keeps private.** `_data/home-page/references.json` is served next to the pages, so anyone can read it. It now carries `stars` (1 to 5, accepted Reference only) and `rank`, on every record: its position (1 is first) in the shared order over every Reference in the file. The build orders by `rank`, and because any subset of an ordered list keeps its order, a section filter, a ledger or a bucket still gives the right order. This was chosen over a pre-sorted list because the file's own order (newest accepted first) is a documented contract that other readers rely on, and over a coarse tier because a tier reveals the rating band. The rest of the rating stays private: `starRatedAt` and `starRatedBy` are excluded fields. The private state in the projection lock table (below) keeps every rated Reference's count, pending ones included, because the order reads it; it never sits beside the pages, because the bucket is public. A unit test proves every Reference field is published or excluded exactly once (`starRating` is published as `stars`, `starRatedAt` and `starRatedBy` are excluded), and the Gherkin scenarios prove that no file a projection wrote mentions who rated or when. A snapshot written before ranks existed has none; its References are then ordered as unrated ones, by confidence, newest and key, which is what the build always did. A snapshot written before the count was published has no `stars` and draws none.

**Freshness.** A rating that reorders the page changes `rank` values, and a rating of an accepted Reference changes its `stars`, so the bytes of the snapshot change, and the page digest (which folds in the snapshot's digest) changes for every page that places a references include: `project_stale_listings` re-renders exactly those pages. A rating on a pending Reference that moves nothing changes nothing. `starRating` is one of the fields the trigger watches (see [Freshness](#freshness)), so a star-only change on an accepted Reference (the old and new image differ in no other field) reaches the page through the same debounce and the same incremental run as an accept: the trigger lists the row, the run reads it again (four requests), and the file is written with the new count. `starRatedAt` and `starRatedBy` are not watched.

**Deploy note.** `stars` is part of the build of the public fields, so the stored private state (whose fingerprint includes the field list) no longer matches: the first run after the release is one full read, as the first run after any change to the fields is. It needs no backend change: the trigger already watches `starRating` and no permission, index or schema field is added.

## Time buckets

`bucket="day"` or `bucket="week"` on a references include sorts by recency in buckets: the newest bucket first, and the shared order above inside each bucket. A bucket is a calendar day, or a week that starts on Monday, **in UTC** (the same rule for every site: a site has no configured time zone, and a references include has no site-level default bucket; a Story listing has `listings.bucket`). The bucket date is the one the selection already orders by: the accepted time (`acceptedAt`), and for a Reference with none (a recommended one) its arrival (`arrivedAt`); a Reference with no usable date sits in the oldest bucket. A rating never moves a Reference to another bucket, because it never changes either date. Any bucket other than `day` or `week` is a build error that names the page (`pages/home.md: ::include references bucket must be one of day, week, got 'month'`). The page ledger works as before: the first component to place a Reference keeps it. `recent` with no bucket keeps its newest-accepted order and ignores ratings. Story listings use the same order of ratings but ROLLING buckets (the last seven days, the seven before, and so on, counted back from the projection day), with `day`, `week` or `none`; References stay on calendar buckets on purpose, since changing them would reorder every home-page Reference grid and the snapshot is not re-rendered with time: see [Published Stories rank by recency bucket, then stars](content-item-lifecycle.md#published-stories-rank-by-recency-bucket-then-stars-ppy-5966d7). Story ratings stay private; only a Reference's count is printed.

## Message threads

With `homePage.threads.enabled` the same task also writes `_data/home-page/threads.json` and one `_data/home-page/threads/<key>.json` per thread, and `::include{kind="threads" select="recent" count="8" layout="list|grid" [heading="..."] [empty="..."]}` places them on an authored page, rendered at projection time. Today only `select="recent"` (most recently active first) exists. `count` defaults to `homePage.references.defaultCount`. The task owns `_data/home-page/threads/`: it deletes the file of a thread that is no longer public. With `homePage.forum` the per-thread files are drawn as pages (see [Thread pages](#thread-pages)); without it nothing reads them and the cards link nowhere.

- **Public threads**: `threadKind` is `reference_conversation` or `story_conversation`, `status` is `active`, and the anchor is public: `reference#<lineageId>` whose public key is in the current `references.json`, or `item#<lineageId>` of a published Story that has a page. Unanchored and other-kind threads, and threads on rejected or archived References, are never exported. A thread with no public Message is left out.
- **Public Messages**: `status` active, `messageKind` comment, never deleted. A deleted or moderated Message is omitted entirely and the count excludes it, because its text stays in the database after a soft delete.
- **Message fields**: `key` (first 12 hex characters of the SHA-256 of the id), `at`, `edited`, `text` (the Message as written, with raw HTML removed and anything shaped like an email address, a UUID or a site subject scrubbed) and `author`. Thread entries carry `key` (hashed the same way), `title`, `anchor` (`{kind: "reference", key, title}` or `{kind: "story", url, title}`), `messages` (the count), `lastAt` and `latest` (the latest Message). The author is `{"handle": "ryan"}` when the person set a public handle in their profile settings and `homePage.threads.authors` is `handle` (the default), otherwise `{"label": "Editor"}` (`homePage.threads.anonymousLabel`) or `{"label": "AI"}` for a Message that was not written by a person. `authors: "none"` always uses the label and reads no profile. Never written: `authorSub`, `authorUserProfileId`, `authorLabel`, `deletedBySub`, `createdBySub`, `createdByLabel`, `metadata`, `responseOwner` or any record id.
- **The card** names what the thread is on in words and a Lucide icon (`link` for a Reference, `file-text` for a Story, whose title links to its page), the title, "N messages" beside a `message-square` icon, the date of the last activity, the latest Message as plain text clipped at a sentence boundary (`publicData.summaryCharacters`, default 240) and "by" the author. Flat tones, rounded corners, no borders.
- **De-duplication**: threads claim `thread:<key>` in the page ledger, so two threads includes on one page never repeat a thread, and they do not interfere with the Reference cards.
- **Freshness**: with `threads.enabled`, the `home-page` plugin also reads the Message table's stream into the same trigger. A new comment, or a change of its `status`, `content`, `editedAt` or `deletedAt`, opens the same debounce window. A Message stream that another feature already switched on is reused, not replaced.

## Stylesheet

`css/papyrus-home-page.css` is written whenever `homePage` is set, but a page links it only when it places a references or threads include, with a `?v=` token of its own (the first 12 hex characters of that file's SHA-256). The file is left out of the site-wide `?v=`, so a page with no cards keeps the same bytes with or without `homePage`.

## Thread pages

`homePage.forum` (an object, `{}` is enough) gives every public thread its own static, read-only page at `<threadBase>/<key>/`, where `threadBase` defaults to `conversations` and `key` is the thread's opaque 12-hex-character key from `threads.json`. It needs `homePage.threads.enabled`, because the page is drawn from `_data/home-page/threads/<key>.json`. `threadBase` follows the same rule as a section `base`: `_data`, `_plugins`, `_papyrus`, `_next` and `api` are reserved (and `newsroom` on a site whose edge routes the CMS), and it may not equal a section base. `forum.index.pageSize` (default 50) and `forum.posting` are read for the forum index and posting tasks and do nothing yet. A site without `homePage.forum` renders no thread page and is byte-identical to before.

- **What is public**: exactly what the thread file holds and nothing else, so everything in [Message threads](#message-threads) applies: the title, the anchor, and each public Message with its time, edited flag, text and author handle or role label. No email address, sign-in subject or id is written.
- **The page**: a header with the thread's anchor (a Reference's `row` card when the snapshot still holds it, otherwise a line; a Story is a line that links to its page), the title and "N messages", then one flat block per Message in sequence. A Message shows a Lucide `user` icon and the handle, or a `badge-check` icon and the role label (`Editor`, `AI`), a `<time datetime>` and, when edited, the word "edited" beside a `pencil` icon. Text is escaped and set as paragraphs (blank line, new paragraph; single line break, `<br>`), with no Markdown rendering and no borders. It works without a script.
- **Twin and llms.txt**: each page has a Markdown twin (`<threadBase>/<key>/index.md`), a "Conversations" group in `llms.txt` and an entry in the sitemap.
- **Links**: with a forum, the title of a thread card from `::include{kind="threads"}` links to `/<threadBase>/<key>/`.
- **Freshness**: the page's digest folds in its own thread file (and the anchor Reference's record), so the snapshot task rewrites a thread page, its twin, `llms.txt` and the sitemap only when the thread set or that file changed. When a thread stops being public the task deletes its file and then its page and twin.

## Public handles

A public handle is held by a `PublicHandleClaim` record keyed by the lowercase handle (`ownerKind`, `ownerId`, `claimedAt`), written by a conditional put in `setPublicHandle`, so two people claiming the same handle at once leave exactly one owner; changing or clearing a handle releases the old claim, and a failed profile write releases the new one.
Sites that had handles before the claim records existed run `scripts/backfill-public-handle-claims.ts` once (an operator with IAM, idempotent, it reports conflicts).

## Freshness

Curation changes reach the pages without anyone running a command. The backend plugin `home-page` (`backend.plugins: ["home-page"]` in `papyrus.config.ts`) wires four things, and only for a site that lists it: every other site synthesizes exactly what it did before.

1. The DynamoDB stream on the Reference table (old and new images). Reference is a realtime model, so the table already streams old and new images; the plugin only asks for the same specification and consumes the stream, so the table itself is not updated.
2. A small trigger function, `homePageTrigger` (Python 3.12, arm64, 256 MB, 30 s). It reads batches of up to 100 records (waiting at most 10 seconds to fill one) and ignores a record unless `curationStatus`, `feedStateKey`, `predictionSortKey`, `versionState`, `title`, `curationSectionId`, `starRating` or `medium` differs between the old and new image (a rating orders the pages without being printed on them; who rated and when are not watched), and unless a page can show the Reference: it is accepted, or it is pending and the Cyclotron has predicted it (`predictionDecidedAt` or `predictedAcceptProbability` is set), before or after the change. A new pending Reference that nobody has predicted, and any edit to a Reference that cannot be on a page, changes nothing and runs nothing. An insert or a removal of a Reference a page can show counts as a change.
3. A list of what changed and a trailing-edge debounce. Each change adds the id of its Reference to a string set in the shared projection lock table (partition key `publication`, value `home-page-dirty#<site scope>`; a changed Message raises the counter `messageSeq` beside it). The first change in a quiet period then claims a slot with a conditional write (`home-page-debounce#<site scope>`, expiring by TTL) and creates a one-off EventBridge Scheduler schedule `papyrus-home-page-snapshot-<site scope>-<epoch>` at the end of the window. It invokes content-actions with `{"projectionTask": {"task": "home-page-snapshot", "incremental": true, "scope": "<site scope>"}}`, runs once and deletes itself. Changes inside the window find the slot taken and only extend the list. If creating the schedule fails the slot is released and the batch is retried by the stream. The site scope is a short hash of the site's content-actions function name, so sites that share an account never share a slot, a list or a schedule name. A window with more than 2,000 changed Reference ids (a mass import; one DynamoDB item holds 400 KB) raises the flag `home-page-full#<site scope>` instead, and that one run reads the whole corpus.
4. The run itself reads the list, reads again those rows, and takes out of the list exactly what it read once it has succeeded (a change that lands meanwhile stays for the next run). The snapshot is written only when it changed, and `project_stale_listings` re-renders only the pages whose digest includes the changed selection. A burst of ten accepts costs one run.

| Setting | Default | Meaning |
| --- | --- | --- |
| `homePage.freshness.debounceSeconds` | 300 | Quiet time between the first change and the run. The default equals the HTML `s-maxage` the writers set (`PAPYRUS_HTML_S_MAXAGE_SECONDS`, 300): with purge off a page can never be fresher than its edge lifetime, so a shorter window buys nothing. Lower it together with `publication.cache.htmlSMaxAgeSeconds`. |
| `homePage.freshness.intervalHours` | none | Adds an EventBridge rule that runs the snapshot at this interval even without changes, as a safety net. Each such run reads the whole corpus (it names no list of changes), so leave it off unless the stream has been missing changes. Off by default. |
| `homePage.freshness.purge` | false | The task invalidates the snapshot file on the edge after writing it. Invalidation paths are free for the first 1000 a month, then billed per path. |

The plugin reads `debounceSeconds` and `intervalHours` from the site's `projection.json` when the backend is synthesized (and the task reads the whole block at run time), so there is one place to set them. A plugin request may override the first two: `plugins: [{ name: "home-page", debounceSeconds: 120 }]`. The plugin refuses to synthesize when the site has no publication or its `projection.json` has no `homePage` setting, because the stream would schedule runs that the task ignores.

To turn it on for a site: add `homePage` to `projection.json`, add `"home-page"` to `backend.plugins`, and deploy the backend. The plugin needs no other setting. The trigger has no dead-letter queue: a batch that still fails after two retries is dropped, and its changes are not listed. The interval rule, when set, reads the whole corpus and so catches them up; without it, they reach the pages the next time that Reference changes, or when an operator runs `papyrus home-page snapshot`.

## Cost: a change is read, not the corpus

Reading a corpus costs requests in proportion to its size: a list is a request per 100 rows, and each row then needs a relations request (its Cyclotron decision) and an attachments request (its preview). The snapshot used to read all of that at every run, and a run follows every change, so a site that takes in dozens of References an hour paid for its whole corpus several times an hour (measured on Machines on Machines: about 8,000 requests a run). Derived work now runs once when something changes.

An **incremental** run (`mode: "incremental"`) reads again only the rows on the trigger's list: one section list, then for each row the Reference itself, its decision, and, only when it will show (accepted, or pending and at or above the threshold), its preview. That is 4 requests for one change at any corpus size, 3 for a pending Reference that will not show, and none when the list is empty. Everything else comes from what the previous run left:

- the previous `references.json`, which holds every public record as it was last built, and
- a private state, one entry for each public record: an editor's stars, the confidence the shared order reads (an accepted-by-editor record does not publish it), the arrival time, the Reference version and the section. The state holds the counts of pending References too (which only order the page and are not shown), and the site bucket is public, so the state lives in the projection lock table, not beside the pages: `home-page-state#<site scope>` is a header (`fingerprint`, `snapshotSha`, a digest of every entry) and `home-page-state#<site scope>#0` to `#f` are sixteen compressed shards of the entries (about 190,000 References fit; a state that does not fit is not saved and each run reads the corpus). The header is written last, so a run that stopped half way leaves one that does not match.

Ranks are positions among all the records, so they are recomputed in memory from the entries; the file is rebuilt with the same code a full read uses, and a test proves the two produce the same file and the same ranks. Section labels are looked up again from the one section list the run reads, so a renamed section reaches every record. Threads (`threads.enabled`) are read again only when a Message changed, or when a Reference created before the file was last built entered or left the page or changed its title (a Reference created since cannot have a thread yet); other runs leave the thread files alone.

A **full** run (`mode: "full"`) reads the whole corpus, as every run used to. It happens once to start a site's state, and again whenever the state cannot be trusted: none stored, written for other `homePage.references` settings or another build of the public fields, not the one that goes with the file now in the bucket (someone else wrote it, or a run stopped before saving), the trigger asked for it (a mass import), or the run was started by hand or by the interval rule, which name no list. The report says why in `fullBecause`.

**Known limit.** A Cyclotron decision written for a Reference that does not change in any watched field is not seen until that Reference changes. The first decision always changes the row (the prediction is written onto it), so recommendations arrive; a later re-decision of the same Reference does not, and the live `confidence` on its card is as of its last change. A relation stream on the decision table would close this; it is not built.

**What a site needs to deploy.** Backend deploy with the trigger and content-actions code in this release. Nothing to configure: the trigger gets `dynamodb:UpdateItem` on the lock table beside the `PutItem` and `DeleteItem` it had, and content-actions already holds Get, Put, Update and Delete on it. The first run after the deploy is a full read (there is no state yet) and leaves the state; the runs after it are incremental. Until the trigger is deployed, a task without a list is a full read, so the order of the two does not matter.

## Monitor deliveries read the Reference table once per run

The identity gate that a monitor delivery passes through (`ReferenceIntake`) needs to see every Reference to prove an item is new, and it read the whole table for each delivery: a web monitor delivers 25 to 40 items a run. A run now shares one read of the table (`ReferenceListing`), and puts each Reference it creates into its copy so a later delivery in the run still finds the earlier one. At 5,000 References that is 50 requests for a run of 30 deliveries instead of 1,529. It is still a read of the corpus per run; an index on the identity keys would make it a lookup (not built).
