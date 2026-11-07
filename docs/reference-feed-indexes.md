# Reference feed indexes

The newsroom References page used to download every Reference, every ReferenceAttachment and every relevance decision on each visit and rank them in the browser. It now reads one page at a time from one of two indexes on `Reference` (and, for the Quality sort and the Minimum stars row, a third, sparse one). This page says what the keys are, who keeps them right, and how to fill them for References that already exist.

The page's search box does not use these indexes; it asks `searchReferences` ([reference search](reference-search.md)). The Quality sort and the Minimum stars row read a third, sparse index: see [the star index](#the-star-index).

## The fields

| Field | Meaning |
| --- | --- |
| `feedStateKey` | `<corpusId>#unrated` for a pending Reference, `<corpusId>#rated` for an accepted or rejected one. Null (so in no feed) for an archived Reference or one that is not the `current` version. |
| `feedArrivalAt` | When the Reference reached the newsroom: the first parseable of `createdAt`, `importedAt`, `retrievedAt`, `sourcePublishedAt`, `versionCreatedAt`, as a UTC instant with milliseconds. The epoch if none parses, so a Reference never drops out of the index. |
| `predictedAcceptProbability` | The Cyclotron's original P(accept): the confidence of the include label, or one minus the confidence of the exclude label. Null until the Cyclotron has decided it. |
| `predictionDecidedAt` | When that decision was made. Every route that creates a pending Reference without a decision queues one request for it (`papyrus references queue-predictions` does it by hand for older ones); the router records it ([monitoring-cloud](monitoring-cloud.md#predictions-for-references-created-without-one)). |
| `predictionSortKey` | `<P to six places>#<feedArrivalAt>#<id>`. An unpredicted Reference sorts as 0.5: after every predicted Accept, before every predicted Reject. That is the editors' queue only (an editor must be able to find an unpredicted Reference); the public home page never reads the key and never treats a missing prediction as 0.5: a pending Reference with no `predictedAcceptProbability` is not published there ([home page](home-page.md)). |
| `captureState` | `full`, `thin`, `none` or `running`: how much of the Reference's content the newsroom holds; empty means `none`. Not a key and in no index. See [the capture state](reference-curation-pipeline.md#4a-referencecapturestate-whether-a-person-is-still-needed-2026-11-03). |
| `mediumFeedKey` | `<corpusId>#<medium>#<pending\|accepted\|rejected>` while the Reference has a medium (`video`), is current and not archived. Null (so in no medium partition) otherwise. See [the medium index](#the-medium-index). |
| `contentNeededKey` | `<corpusId>#<medium>#needs_content#<pending\|accepted\|rejected>` while a current, not archived Reference with a medium (`video`) has no captured content and no settled `captureReason`. Null otherwise. See [the content-needed index](#the-content-needed-index). |
| `captureReason` | `no_transcript`, `unavailable` or `unsupported_platform` once the transcript worker found nothing it can capture on a video; empty otherwise. Not a key and in no index; it only keeps a settled video out of the content-needed list. |
| `starFeedKey` | `<corpusId>#stars#<n>` while the Reference has a whole star rating of 1 to 5 and a corpus. Null (so in no star partition) when it has no stars. Not part of the feed keys above: see [the star index](#the-star-index). |

The prediction is a value on the original record, written once. A later decision, a vote and a re-delivery do not rewrite it.

## The indexes

Both are partitioned by `feedStateKey`.

- `listReferencesByFeedStateAndPrediction` (sort key `predictionSortKey`), read descending: **Predictions**. Highest P(accept) first, ties newest first.
- `listReferencesByFeedStateAndArrival` (sort key `feedArrivalAt`), read descending: **Newest**.

The page reads `<corpusId>#unrated` for Reviewed **No** and both partitions for Reviewed **Any**, merging the two streams with the same comparator. Reviewed **Yes** reads `<corpusId>#rated` alone, and Reviewed **Accepted** reads the same partition and keeps only the rows whose `curationStatus` is `accepted` (the partition holds the rejected too, so the page filters each page as it reads it, `acceptedRows` in `lib/reference-feed-pages.ts`). The saved browser values keep their old names: `unrated` is No, `all` is Any, `rated` is Yes, and `accepted` is Accepted; only the words changed.

## The star index

`listReferencesByStarFeedAndArrival` (partition `starFeedKey`, sort key `feedArrivalAt`), read descending, serves the **Quality** sort and the **Minimum stars** row (Any, 3+, 4+, 5). It is sparse: a Reference with no stars has no `starFeedKey` and is in no star partition. There is one partition per corpus and star level (`<corpusId>#stars#5` down to `#1`), and the reader merges the levels it needs with the same `MergedFeedReader` as the feed:

- **Quality** (minimum Any) reads levels 1 to 5 and merges them by stars, then arrival: most stars first, newest first within a level. Only starred References are in it.
- **Newest with a minimum** (`4+`) reads only the levels from that number up (`#5` and `#4`) and merges them by arrival, newest first.
- **Predictions cannot be combined with a minimum**: the star index is by arrival and cannot order by prediction. The page moves Sort to Newest when a minimum is chosen, and Predictions sets the minimum back to Any. Choosing Quality or a minimum while Reviewed is No moves Reviewed to Any, because stars are separate from the vote and most starred References have one.

The star key does not look at the feed state, so a star partition also holds a Reference that was superseded by a new version or archived while it kept its rating. That is the **ghost-row rule**: the reader (`liveStarRows` in `lib/reference-feed-pages.ts`) drops every row with no `feedStateKey`, so a superseded or archived Reference never shows, and keeps the rest by the chosen Reviewed (the `#unrated` or `#rated` suffix of `feedStateKey`, and for Accepted the row's `curationStatus`). The filter is on the client on purpose: star partitions are small, and it keeps the key writer to one rule. A page can come back short, or empty with a next token; the reader keeps going (`MergedFeedReader` places only what no unread partition could still beat, and the feed's "Load more" row stays while it has more), so a page of ghosts does not stop the list.

The key writers: `setReferenceStars` (`amplify/functions/category-action/handler.ts`) sets `starFeedKey` with the rating and clears it when the rating is cleared, and gives a Reference with no `feedArrivalAt` one (a row without it is not in the index). The Python twin is `reference_stars.star_fields(stars, corpus_id=...)`. The key function is `starFeedKeyFor` (`lib/reference-feed-keys.ts`) and `star_feed_key` (`src/papyrus_content/reference_feed_keys.py`), tested against the same vectors (`starFeedKey` in `scripts/fixtures/reference-feed-key-vectors.json`). It is deliberately **not** in `referenceFeedKeys` / `feed_keys`: callers spread those on partial patches whose input may lack `starRating`, which would wrongly clear the key. A new version of a Reference does not carry the star rating today (the new version's record has none and `moveReferenceCorpus` does not copy it), so it has no star key either; the old version's key stays until the backfill or the reader's ghost rule hides it. Stars are not relevance and never reach the Cyclotron.

## The medium index

`listReferencesByMediumFeedAndArrival` (partition `mediumFeedKey`, sort key `feedArrivalAt`), read descending, lists the References whose address is a video, newest first, without a scan. It is sparse: a Reference with no medium has no `mediumFeedKey` and is in no medium partition. The partition is `<corpusId>#<medium>#<status>`, for example `knowledge-corpus-site#video#accepted`; `<status>` is `pending`, `accepted` or `rejected`, so **a public page reads the `accepted` partition and nothing is filtered out of it in the browser**: pending, rejected, archived and superseded References are in other partitions or none. The corpus in the key keeps one site's (or one corpus's) videos out of another's, the same isolation `feedStateKey` has (a site has its own backend; a Reference has no `tenantId`).

| Writer | What it does |
| --- | --- |
| `catalog.reference_record` (and through it every intake path), `reference_url_text` citation stubs | Set `medium` and `mediumFeedKey` with the feed keys when the address is a video; an ordinary address names no medium field at all (an explicit null on a new row's index key is not a missing attribute) |
| `feed_keys` (`reference_feed_keys.py`) | Includes the key only when there is one to set or one currently stored to clear |
| `reviewReferenceCuration`, `rateReferenceQuality` (`category-action`), `review_reference_curation` (chat), `auto_accept.py`, `auto_reject.py`, `reference_citation_stubs.py` | Move the key with the vote: `<corpus>#video#accepted`, `#rejected`, `#pending`, or null on archive (`medium_key_patch`, `referenceMediumKeyPatch`) |
| `records.py` supersede, `moveReferenceCorpus` | A superseded version loses the key; the moved version is keyed for its new corpus |
| `papyrus references backfill-medium` | Sets `medium` and the key on existing References (below) |

The Python twin of the key is `medium_feed_key` (`reference_feed_keys.py`; it reads the medium off the address when none is stored yet, so a vote written before the backfill still lands in the right partition) and the TypeScript one `referenceMediumFeedKey` (`lib/reference-feed-keys.ts`, stored medium only; the backfill repairs a Reference voted in the browser before its medium was stored). Both are tested against `scripts/fixtures/reference-feed-key-vectors.json`. Read it from Python with `iterate_references_by_medium(client, corpus_id)` (`reference_medium.py`), which pages newest first and stops when you stop.

The newsroom References page reads this index for its **Medium** row (All, Videos): see [the Medium filter](#the-medium-filter). The public videos block reads the home-page snapshot, which the snapshot task builds from the accepted References it already reads (it does not use this index either); the index is for a reader that needs the videos alone, quickly, such as a future videos feed, an Alexa skill or a count. It is **one** new global secondary index on `Reference`: DynamoDB allows one index change per deploy per table, so deploy it on its own. Until the backfill runs, the index holds only the References created or voted on since the writers shipped.

```bash
papyrus references backfill-medium --site KEY                      # preview, writes nothing
papyrus references backfill-medium --site KEY --write              # writes medium, playlistUrl, evidenceLevel (aggregation only, only where empty), mediumFeedKey and contentNeededKey
```

Rollout order, with the other Reference fields: data API first (schema and index), then the engine, then the backfill, then a videos page. See [the curation pipeline](reference-curation-pipeline.md#4b-referencemedium-what-kind-of-thing-the-address-is-2026-11-04).

## The medium filter

The References page has a Medium row beside Reviewed: **All** and **Videos** (the mediums the rule can name; `lib/reference-medium-feed.ts`). Videos reads `listReferencesByMediumFeedAndArrival` newest first, one partition per vote state and corpus, merged by arrival (`MergedFeedReader`), so a page of 24 is one read per partition and nothing is read that is not shown. The vote state is in the key, so Reviewed picks the partitions and nothing is filtered in the browser:

| Reviewed | Partitions read, per corpus |
| --- | --- |
| No (default) | `<corpusId>#video#pending` |
| Accepted | `<corpusId>#video#accepted` |
| Yes | `<corpusId>#video#accepted`, `<corpusId>#video#rejected` |
| Any | `pending`, `accepted` and `rejected` |

- **The address holds the choice**: `/newsroom/references?medium=video` (any other value is All). It is not saved in the browser, so a link opens the same list and the next visit starts on All.
- **Sort**: the index is by arrival, so a medium reads Newest. While the saved Sort is Predictions the page shows Newest and leaves the saved choice alone; choosing Predictions takes the medium off the address. Quality and Minimum stars work with a medium: they read the star partitions and keep that medium's rows (the star partitions are small).
- **Captured** applies on top as for any list. A search ignores the medium and hides the row while one is open.
- **References with no medium are in no medium partition.** The rule names a medium only where the address is certain (a video on a known platform), so an ordinary article has none and is listed under All only. There is no Articles, Papers or Podcasts button because no such medium exists; one is added by teaching the rule a new medium (a `MEDIUMS` entry in `reference_medium.py`, then `FEED_MEDIUMS` here). A video written before the key writers shipped, or voted in the browser before its medium was stored, has no key until `papyrus references backfill-medium --site KEY --write` runs; that command covers exactly those, and it leaves the articles unset on purpose.
- **Who reads**: `readReferenceMediumStream` (`components/news-desk-taxonomy-client.ts`) is the page's reader; the local preview and the test mock serve the same keys from memory (`mediumReaderFromRecords`).

## The content-needed index

`listReferencesByContentNeededAndArrival` (partition `contentNeededKey`, sort key `feedArrivalAt`), read descending, lists the videos the newsroom holds no content for, newest first, without a scan. It exists for `papyrus references capture-transcripts` ([the transcript worker](reference-curation-pipeline.md#4d-video-transcripts-the-worker-2026-11-04)).

**Why the medium index plus a filter is not enough.** `listReferencesByMediumFeedAndArrival` lists every video of a corpus and vote. A corpus can hold thousands of them, nearly all waiting for a transcript at first and captured over weeks. Reading that partition and dropping the captured ones (what `lib/capture-needed.ts` does with the star partitions for its short list) reads the whole partition on every run to find the few that matter: a scan with a filter in front of it. So the index is keyed on the one thing the worker asks for.

**The key.** `<corpusId>#<medium>#needs_content#<status>`, for example `knowledge-corpus-site#video#needs_content#accepted`. It is present while the Reference is current, not archived, has a medium, its `captureState` is `none`, `thin` or empty (not `full`; a capture `running` finishes by itself), and it has no settled `captureReason`. It is removed the moment the content arrives (`captureState` becomes `full`) or the worker records that nothing can be captured. The status is in the key so that the default run reads `accepted` and `pending` and never touches the rejected videos, which are usually most of them; `--status` reads others. The medium is in the key because it costs nothing: it is already in the medium key, and another medium with a reader later needs no new index. Nothing else is general.

**Not sorted by stars.** Stars change often (any vote on a star level) and the index sorts by one field, so "stars before arrival" would mean a composite sort key rewritten by every star write. Not worth it for a list read once a week: the order is newest first.

**Who keeps it right.**

| Writer | What it does |
| --- | --- |
| `catalog.reference_record`, `reference_url_text` citation stubs, accession (`feed_keys`) | A new video has no content: the key is set with the other feed keys. A page that is not a video gets no field at all |
| `sync_capture_state` (every writer of captured text or of the curation card) | Sets and clears the key with `captureState`, and sets `captureReason` from the card's `capture.textReason` |
| `correctReferenceCapture` with `captureReason` | The worker's record of a video it cannot capture; `sync_capture_state` takes the key out |
| Votes (`reviewReferenceCuration`, `rateReferenceQuality`, chat, auto-accept, auto-reject), archive, retiring a citation stub | The held key moves to the new status, or is cleared on archive (`medium_key_patch`, `referenceMediumKeyPatch`); it needs no capture state, so a writer that read only part of the Reference cannot get it wrong |
| New version, superseded version, corpus move (`records.py`, `category-action`) | The new version carries `captureState` and `captureReason` and gets its key; the old one loses it |
| `papyrus references backfill-medium` | Sets and clears it for existing References, from the stored capture state (below) |

The key functions are `content_needed_key` and `moved_content_key` (`reference_feed_keys.py`) and `referenceContentNeededKey` and `referenceMediumKeyPatch` (`lib/reference-feed-keys.ts`), tested against the shared vectors; `reference_creation_paths_test.py` covers every creating path, a vote, a supersede and a retire.

**Rollout.** This is **one** new global secondary index on `Reference`, and DynamoDB allows one index change per deploy per table. The medium index ships in the release before this one, so this index must go out in a later, separate deploy: do not release the two together (the two index lines in `amplify/data/schema.ts` and `amplify/data/resource.ts` are the last commit of the pull request that added them, so they can be held back). The fields (`captureReason`, `contentNeededKey`) are plain attributes and can ship with anything; the engine tolerates a site whose data API does not have them yet (the client drops them and retries). Order, per site: (1) the deploy with the fields (no index), (2) the deploy with the index alone, (3) `papyrus references backfill-feed-keys --site KEY` if the site's capture states were never stored, then `papyrus references backfill-medium --site KEY` to preview and `--write` to set `contentNeededKey` (it reports `contentKeysSet`), (4) `papyrus references capture-transcripts` from a non-cloud connection. Until step 3 the index is empty for existing videos, and until step 2 the command says the index is not there yet.

## The public-blocks attributes

A public block (the three newest accepted References, the six most confident recommended ones) will ask an index for exactly the rows it shows and draw each card from the row it gets back, instead of reading the whole table ([the design](plans/public-blocks-from-indexes.md), PPY-7f1e54). This page covers the first stage: six plain attributes on `Reference`, the writers that keep them right, and the backfill. **There is no index yet** (it is the next, separate deploy), and no page reads these attributes yet: a site renders exactly as before.

| Field | Meaning |
| --- | --- |
| `publicFeedKey` | The partition: `<corpusId>#accepted` for an accepted Reference, `<corpusId>#recommended#<UTC day of arrival>` for a pending one with a stored prediction of at least 0.5. Absent (null) otherwise, so the row is in no partition. |
| `publicOrderKey` | The sort key: `p<P to six places>#<arrival>#<id>`, where P is the Cyclotron's original `predictedAcceptProbability`; `n#<arrival>#<id>` for an accepted Reference nobody scored, which sorts after every scored one (`p` sorts above `n`). A pending row's key is written once: its prediction and arrival never change. Star ratings are in neither key. |
| `cardImage` | The address of the card picture. The preview's image address with anything that carries identity removed; for a video, our own thumbnail copy (`/assets/reference-thumbnails/...`), never an address on the platform, and empty until the thumbnail is recorded; for a picture an editor chose (`via: editor` on the preview), that picture. |
| `cardSummary` | The preview's description, scrubbed and **not clipped**: the clip to `publicData.summaryCharacters` happens when the card is drawn, so a site that changes its length changes nothing in the table. |
| `cardSiteName` | The preview's site name, scrubbed. |
| `cardPageTitle` | The title the page declared for link previews, scrubbed. A Reference titled with its own address shows this, or a readable name made from the site name and the address, never the address ([PR #1236](https://github.com/AnthusAI/Papyrus/pull/1236) adds the rule, `displayed_title`). It is the page's title and not the displayed one, so a repaired row title needs no rewrite here: the card computes the displayed title from the live row and this. |

**A missing prediction is never a number.** A pending row with no stored prediction, or one below 0.5, has no key and is in no partition; an accepted row nobody scored is public and sorts last. The keys come from one pure function, `public_feed_keys` (`reference_feed_keys.py`), with the TypeScript twin `referencePublicFeedKeys` (`lib/reference-feed-keys.ts`); `scripts/fixtures/public-feed-key-vectors.json` holds the vectors both test. Like the medium keys they are sparse: written when the row can be public, cleared only when the row currently holds them, and never an explicit null on a row that has none (a null on an index key of a new row is not a missing attribute).

**Who keeps them right** (in each writer, not in the stream trigger, so a failed trigger batch can never leave a row invisible):

| Writer | What it does |
| --- | --- |
| `feed_keys` (`reference_feed_keys.py`): `catalog.reference_record`, `reference_url_text`, accession, `records.py` new versions, `original_prediction_fields` | Include the public keys when the row can be public or holds them. A row accepted at import is public from the start. |
| `monitoring_router.record_original_prediction`, `relevance_sweep`, the router's copy of an earlier decision (`original_prediction_fields`) | The first prediction of at least 0.5 brings a pending row into the recommended partition; a lower one writes no key. |
| `reviewReferenceCuration`, `rateReferenceQuality` (`category-action`), `review_reference_curation` (chat), `auto_accept.py`, `auto_reject.py`, `reference_citation_stubs.py` | Move the keys with the vote (`referencePublicKeyPatch`, `public_key_patch`): the partition follows the vote, the sort key keeps the original prediction's place; a reject or an archive clears both. A patch for a row that neither has nor will have keys names no public field, so it works on a backend that does not have the attributes yet. The chat tool's `getReference` query selects the prediction and arrival the keys are made from. |
| `records.py` supersede, `moveReferenceCorpus` | The superseded version loses its keys. The new version is keyed from its own facts (its own id is in the sort key) and carries the card copies, which belong to the preview and are read by lineage. |
| `reference_images.attach_preview` (the router, URL intake, email submission), `enrich-images` | After the preview attachment, `card_update` writes the card copies in one more mutation per new Reference, and none when the row already holds the same values. A failed card write does not fail the preview; the backfill repairs it. |
| `reference_thumbnails.record_thumbnail` (`correctReferenceCapture`, `papyrus references capture-thumbnails`) | Writes `cardImage` with `thumbnailPath` in the same update, so a video's thumbnail ends up in `cardImage`. |
| `papyrus references backfill-public-fields` | The one command that reads existing rows (below). |

An editor-chosen picture (`via: editor` on the preview attachment) is honoured by `card_fields`, but nothing in this tree writes one yet; whichever writer adds it calls `card_update`.

The home-page trigger watches `CHANGE_FIELDS`, which does not include any of these attributes, so writing them (the backfill included) schedules no snapshot. The six fields are in `EXCLUDED_REFERENCE_FIELDS` (`home_page/export.py`): none is published under its own name.

### Backfill

```bash
papyrus references backfill-public-fields --site KEY                      # preview: one line per row it would change, then counts; writes nothing
papyrus references backfill-public-fields --corpus-key KEY1,KEY2 --write  # writes
papyrus references backfill-public-fields --all-corpora                   # preview of every corpus the backend lists
```

It reads the accepted rows of a corpus from the curation-status index and its pending rows from the prediction index, **highest first, stopping at the first row under 0.5**; for each row that can be public it reads the preview attachments once, and writes only the six fields. Rejected, archived, unpredicted and low-scored rows are not read past that point or touched. It changes no vote, writes nothing on a second run, and reports `public`, `accepted`, `recommended`, `keysSet`, `keysCleared`, the card fields set, `videosWithoutImage` (videos whose thumbnail copy is not recorded yet; run `capture-thumbnails` and then this again) and `longestSummary` (so the stored summary length is learned from data). It previews by default, like `backfill-medium`, and is an operator command. The rows must already carry `feedStateKey` and `predictionSortKey` (`backfill-feed-keys`) for the pending ones to be found. Cost per site, once: one list of the accepted rows, the pending index down to 0.5, one attachment read per public row, and one write per changed row.

**Rollout.** (1) Deploy the data API with the five attributes (no index) and the engine with the writers. The router and chat tolerate a site whose schema lacks the attributes (`NEWER_REFERENCE_FIELDS`, `MEDIUM_REFERENCE_FIELDS`), but the TypeScript Lambdas and the chat's own GraphQL path have no such retry: they ship with the schema in the same site deploy. (2) `backfill-public-fields` per site, preview then `--write`. (3) The index, alone, in a later deploy: one new index per table per deploy, and with the keys already in place it is complete the moment it is active. No IAM change: the attributes ride on `createReference` and `updateReference`, which every worker already holds (`procedures/newsroom/tests/test_reference_medium_iam.py` fails if a grant is lost or if the monitoring template ever names one of the new fields).

### The public index

`listReferencesByPublicFeed` (partition `publicFeedKey`, sort key `publicOrderKey`), read descending, is the one new global secondary index for the public blocks. It is sparse, so a row without the keys is in it nowhere and costs nothing. It is **one** new index on `Reference`; deploy it alone, after the attributes (the release before) and after `backfill-public-fields` has run on the site, so it is complete the moment it is active. Nothing reads it until the engine release (`homePage.references.source: index`); a site that has not opted in is unchanged. No worker role reads it, so no IAM grant is added.

## The Captured filter and the capture list

**Captured** (Any, Yes, No, saved in this browser, default Any) filters on `Reference.captureState` (`full`, `thin`, `none` or `running`; empty means `none`). Yes keeps `full`; No keeps every other value, a capture still `running` included. It is applied on the client to each page as it is read, like the ghost-row rule: `capturedRows` in `lib/reference-feed-pages.ts` wraps the feed-state reader and the star reader, over whichever partitions the Sort, Reviewed and Minimum stars choices read, and it restricts no Sort. A page can come back short, or empty with a next token, however many rows are dropped; the reader keeps going and the feed's sentinel asks again, so a run of filtered pages never ends the list (tested with sixty filtered rows ahead of the three that match). The search takes the same choice (`captured` in [reference search](reference-search.md)). The field has no index: nothing is read by it. Sort, Reviewed and Minimum stars keep their rules; Captured is independent of all three.

A page address can open the feed on choices of its own without saving them: `/newsroom/references?reviewed=accepted&captured=no&sort=newest&minStars=0` (`feedChoicesFromSearch`, `lib/reference-feed-view.ts`). The newsroom home's "See all" for accepted References that need a capture links there; changing a control inside such a view changes the view, not what the editor saved.

The home page's list (`lib/capture-needed.ts`, `readCaptureNeeded`) reads without scanning: the star partitions 5 down to 1, merged by stars then arrival and filtered to accepted, live and not captured (not `running` either), then the `#rated` partition by arrival for the unstarred ones, stopping as soon as it has enough. See [the Notification Center](notification-center.md).

## What the page reads

On open, the References page reads the site's `KnowledgeCorpus` ids (a handful, once per session) and then one page of 24 from each partition, in parallel: `<corpus>#unrated` for Reviewed No, plus `<corpus>#rated` for Reviewed Any. `lib/reference-feed-pages.ts` merges the partitions into one list in feed order, so a site with several corpora shows them in one feed. Scrolling near the end reads the next round (a partition is read again only when its buffer has run dry). Attachments for the cards shown are read in one batched request, and predictions in one batched request per page, never for a Reference not shown. Nothing reads a whole table: the List view and the Assignments and Search pages read every Reference only when opened (`loadAllEditorReferences`).

A failed read shows the error with a Retry; an empty site shows the empty message; a slow read shows skeletons. A Reference with no `feedStateKey` is not in either partition, so it is not in the feed: run the backfill below before a site gets this page.

## Who keeps the keys right

| Writer | What it does |
| --- | --- |
| `catalog.reference_record` (monitor intake, imports, accession, GROBID citations) | Sets `feedStateKey`, `feedArrivalAt` and an unpredicted `predictionSortKey` when it creates a Reference. An import of an existing Reference never rewrites a stored prediction or arrival. |
| `monitoring_router.record_original_prediction` | After a delivery, writes the prediction fields once from the Cyclotron's decision. |
| `relevance_sweep` | Same, for References the decide-relevance sweep decides. |
| `auto_accept.py`, `auto_reject.py` | Move the Reference to `#rated`. |
| `reviewReferenceCuration` (`amplify/functions/category-action/handler.ts`) | An editor's accept or reject moves it to `#rated`; reopen moves it to `#unrated`; archive clears the key. A corpus move recomputes the keys for the new version. |
| `records.py` supersede | A superseded version loses `feedStateKey`. It keeps its `starFeedKey`: the reader drops it by its missing feed state (the ghost-row rule, below). |
| `setReferenceStars` (`category-action`) | Writes `starFeedKey` with the rating, clears it with the rating, and gives a Reference with no `feedArrivalAt` one. |
| `sync_capture_state` (`reference_capture_state.py`), from `write_card` (the curation run and every editor correction) and `apply_record_changes` (older extracted text); `_feed_keys_for_new_version` carries it | Keeps `captureState` right (and, for a video, `captureReason` and `contentNeededKey`); writes only when it differs, and never writes `none`. |

The key functions live in `src/papyrus_content/reference_feed_keys.py` and `lib/reference-feed-keys.ts`; `scripts/fixtures/reference-feed-key-vectors.json` holds the vectors both test.

## Every way of creating a Reference is in the feed

The feed shows a Reference only if it has the keys, whatever its source. Every creating writer sets all three (`src/papyrus_content/reference_creation_paths_test.py` and the scenario "Every way of creating a Reference is in the feed" run each offline, in two corpora):

| Source | Writer |
| --- | --- |
| `papyrus references import`, assignment registration, email submission (`papyrus_newsroom/email_submissions.py`), Slack and console chat `Reference.create` (`papyrus_newsroom/newsroom.py`), named imports | `catalog.reference_record`, through `build_reference_catalog_registration_records` |
| Monitor delivery (`papyrus-monitoring-worker`) | `monitoring_intake.ReferenceIntake`, through `catalog.reference_record` |
| Console and email hand-off Lambda (`intakePendingReferences`, `intakeEmailSubmissionReferences`) | `reference_intake.find_or_create_source_reference`, through `catalog.reference_record` |
| Accession (next version, or a replacement lineage) | `accession.py` |
| Citations found in a paper (GROBID) | `reference_url_text._resolve_or_build_cited_reference_record` |
| A new version of an existing Reference | `records.prepare_versioned_knowledge_records`: the old version loses its key; the new one is keyed and keeps the original prediction and arrival |
| Moving a Reference to another corpus | `category-action` `moveReferenceCorpus` (TypeScript, `referenceFeedKeys`) |
| An agent's accept, reject, reopen or archive from chat | `papyrus_newsroom/reference_actions.review_reference_curation` sets `feedStateKey` |

The console's "Paste a URL" calls `intakePendingReferences` and creates a pending Reference (it used to write a Cyclotron priming request, which created no Reference, so a pasted page never appeared in the list). "Import a file" still creates Cyclotron priming examples, not References.

A re-import does not repair a Reference that has no keys: it reuses a current Reference with the same import run or content. Only the backfill below keys existing rows.

## Backfill

```bash
papyrus references backfill-feed-keys --site KEY --dry-run                       # counts only, corpus knowledge-corpus-KEY
papyrus references backfill-feed-keys --corpus-key KEY1,KEY2,KEY3 --dry-run      # named corpora (comma-separated), one report each
papyrus references backfill-feed-keys --all-corpora --dry-run                    # every KnowledgeCorpus the backend lists
papyrus references backfill-feed-keys --all-corpora                              # writes
```

It reads each current Reference of a corpus by curation status (`referencesByCurationStatusKey`, partition `<corpusId>#pending|accepted|rejected|archived`, no other filter), takes the current `relevance_decision_is` decision as its prediction, and writes only the six fields above (`id` plus the fields it changes), `starFeedKey` among them: it sets it from `starRating` where it differs and clears it where a Reference has a key and no stars. The report counts them as `starKeysChanged`. It also sets `captureState` from each Reference's attachments (the rule in [the curation pipeline](reference-curation-pipeline.md#4a-referencecapturestate-whether-a-person-is-still-needed-2026-11-03); it reads the attachments of every Reference except an archived one with the field empty) and counts `captureStatesChanged`; a Reference with no capture stays empty and is not written, and the dry run writes nothing. It never touches a vote, a curation field or a relation, keeps a prediction a Reference already has, and writes nothing on a second run. A Reference with no decision gets keys and sorts as 0.5. Writing a Reference refreshes its `updatedAt`, which Amplify maintains; `curationStatusUpdatedAt` is untouched. The first write also makes a site's home-page trigger schedule one debounced snapshot, because `feedStateKey` is one of its watched fields.

`--site KEY` means the corpus `knowledge-corpus-KEY`. It does not choose the backend: the CLI talks to the backend it is configured for (`PAPYRUS_GRAPHQL_ENDPOINT` or `amplify_outputs.json`). A publication whose References sit in corpora named for something else than its site key (Machines on Machines holds `knowledge-corpus-ai-ml-research`, `-journalism` and `-history`, not `knowledge-corpus-machines-on-machines`) needs `--all-corpora` or `--corpus-key`; `--site machines-on-machines` alone finds nothing.

Order: deploy the data API (schema and indexes) and the engine, dry-run, write, dry-run again (every corpus must report `changed 0`), then release the index-backed References page to the site. Backfill before the page is released: until then the page would show only keyed References.

## Rollout

The Python client now asks for these fields on every Reference read and write, so a site's backend must have the schema before the engine that carries these writers reaches that site's tools: deploy the data API first, then the router and operator tools. Adding the indexes makes DynamoDB build them from existing items, which have no keys until the backfill runs: the page sees only References the backfill or a writer has keyed. The star index is the same: until the backfill runs, Quality and a minimum show only References starred since `setReferenceStars` began writing `starFeedKey`. A site whose schema lacks the star index fails a Quality or minimum read with an error and a Retry (the feed and Newest are unaffected); the Python client drops `starFeedKey` from its reads on such a site (`NEWER_REFERENCE_FIELDS`) rather than failing every Reference read.
