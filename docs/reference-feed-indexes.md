# Reference feed indexes

The newsroom References page used to download every Reference, every ReferenceAttachment and every relevance decision on each visit and rank them in the browser. It now reads one page at a time from one of two indexes on `Reference` (and, for the Quality sort and the Minimum stars row, a third, sparse one). This page says what the keys are, who keeps them right, and how to fill them for References that already exist.

The page's search box does not use these indexes; it asks `searchReferences` ([reference search](reference-search.md)). The Quality sort and the Minimum stars row read a third, sparse index: see [the star index](#the-star-index).

## The fields

| Field | Meaning |
| --- | --- |
| `feedStateKey` | `<corpusId>#unrated` for a pending Reference, `<corpusId>#rated` for an accepted or rejected one. Null (so in no feed) for an archived Reference or one that is not the `current` version. |
| `feedArrivalAt` | When the Reference reached the newsroom: the first parseable of `createdAt`, `importedAt`, `retrievedAt`, `sourcePublishedAt`, `versionCreatedAt`, as a UTC instant with milliseconds. The epoch if none parses, so a Reference never drops out of the index. |
| `predictedAcceptProbability` | The Cyclotron's original P(accept): the confidence of the include label, or one minus the confidence of the exclude label. Null until the Cyclotron has decided it. |
| `predictionDecidedAt` | When that decision was made. |
| `predictionSortKey` | `<P to six places>#<feedArrivalAt>#<id>`. An unpredicted Reference sorts as 0.5: after every predicted Accept, before every predicted Reject. |
| `starFeedKey` | `<corpusId>#stars#<n>` while the Reference has a whole star rating of 1 to 5 and a corpus. Null (so in no star partition) when it has no stars. Not part of the feed keys above: see [the star index](#the-star-index). |

The prediction is a value on the original record, written once. A later decision, a vote and a re-delivery do not rewrite it.

## The indexes

Both are partitioned by `feedStateKey`.

- `listReferencesByFeedStateAndPrediction` (sort key `predictionSortKey`), read descending: **Predictions**. Highest P(accept) first, ties newest first.
- `listReferencesByFeedStateAndArrival` (sort key `feedArrivalAt`), read descending: **Newest**.

The page reads `<corpusId>#unrated` for "Unrated" and both partitions for "All", merging the two streams with the same comparator.

## The star index

`listReferencesByStarFeedAndArrival` (partition `starFeedKey`, sort key `feedArrivalAt`), read descending, serves the **Quality** sort and the **Minimum stars** row (Any, 3+, 4+, 5). It is sparse: a Reference with no stars has no `starFeedKey` and is in no star partition. There is one partition per corpus and star level (`<corpusId>#stars#5` down to `#1`), and the reader merges the levels it needs with the same `MergedFeedReader` as the feed:

- **Quality** (minimum Any) reads levels 1 to 5 and merges them by stars, then arrival: most stars first, newest first within a level. Only starred References are in it.
- **Newest with a minimum** (`4+`) reads only the levels from that number up (`#5` and `#4`) and merges them by arrival, newest first.
- **Predictions cannot be combined with a minimum**: the star index is by arrival and cannot order by prediction. The page moves Sort to Newest when a minimum is chosen, and Predictions sets the minimum back to Any. Choosing Quality or a minimum while Show is Unrated moves Show to All, because stars are separate from the vote and most starred References have one.

The star key does not look at the feed state, so a star partition also holds a Reference that was superseded by a new version or archived while it kept its rating. That is the **ghost-row rule**: the reader (`liveStarRows` in `lib/reference-feed-pages.ts`) drops every row with no `feedStateKey`, so a superseded or archived Reference never shows, and keeps the rest by the chosen Show (the `#unrated` or `#rated` suffix of `feedStateKey`). The filter is on the client on purpose: star partitions are small, and it keeps the key writer to one rule. A page can come back short, or empty with a next token; the reader keeps going (`MergedFeedReader` places only what no unread partition could still beat, and the feed's "Load more" row stays while it has more), so a page of ghosts does not stop the list.

The key writers: `setReferenceStars` (`amplify/functions/category-action/handler.ts`) sets `starFeedKey` with the rating and clears it when the rating is cleared, and gives a Reference with no `feedArrivalAt` one (a row without it is not in the index). The Python twin is `reference_stars.star_fields(stars, corpus_id=...)`. The key function is `starFeedKeyFor` (`lib/reference-feed-keys.ts`) and `star_feed_key` (`src/papyrus_content/reference_feed_keys.py`), tested against the same vectors (`starFeedKey` in `scripts/fixtures/reference-feed-key-vectors.json`). It is deliberately **not** in `referenceFeedKeys` / `feed_keys`: callers spread those on partial patches whose input may lack `starRating`, which would wrongly clear the key. A new version of a Reference does not carry the star rating today (the new version's record has none and `moveReferenceCorpus` does not copy it), so it has no star key either; the old version's key stays until the backfill or the reader's ghost rule hides it. Stars are not relevance and never reach the Cyclotron.

## What the page reads

On open, the References page reads the site's `KnowledgeCorpus` ids (a handful, once per session) and then one page of 24 from each partition, in parallel: `<corpus>#unrated` for "Unrated", plus `<corpus>#rated` for "All". `lib/reference-feed-pages.ts` merges the partitions into one list in feed order, so a site with several corpora shows them in one feed. Scrolling near the end reads the next round (a partition is read again only when its buffer has run dry). Attachments for the cards shown are read in one batched request, and predictions in one batched request per page, never for a Reference not shown. Nothing reads a whole table: the List view and the Assignments and Search pages read every Reference only when opened (`loadAllEditorReferences`).

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

The console's "Paste a URL" and "Import a file" create Cyclotron priming examples, not References.

A re-import does not repair a Reference that has no keys: it reuses a current Reference with the same import run or content. Only the backfill below keys existing rows.

## Backfill

```bash
papyrus references backfill-feed-keys --site KEY --dry-run                       # counts only, corpus knowledge-corpus-KEY
papyrus references backfill-feed-keys --corpus-key KEY1,KEY2,KEY3 --dry-run      # named corpora (comma-separated), one report each
papyrus references backfill-feed-keys --all-corpora --dry-run                    # every KnowledgeCorpus the backend lists
papyrus references backfill-feed-keys --all-corpora                              # writes
```

It reads each current Reference of a corpus by curation status (`referencesByCurationStatusKey`, partition `<corpusId>#pending|accepted|rejected|archived`, no other filter), takes the current `relevance_decision_is` decision as its prediction, and writes only the six fields above (`id` plus the fields it changes), `starFeedKey` among them: it sets it from `starRating` where it differs and clears it where a Reference has a key and no stars. The report counts them as `starKeysChanged`. It never touches a vote, a curation field or a relation, keeps a prediction a Reference already has, and writes nothing on a second run. A Reference with no decision gets keys and sorts as 0.5. Writing a Reference refreshes its `updatedAt`, which Amplify maintains; `curationStatusUpdatedAt` is untouched. The first write also makes a site's home-page trigger schedule one debounced snapshot, because `feedStateKey` is one of its watched fields.

`--site KEY` means the corpus `knowledge-corpus-KEY`. It does not choose the backend: the CLI talks to the backend it is configured for (`PAPYRUS_GRAPHQL_ENDPOINT` or `amplify_outputs.json`). A publication whose References sit in corpora named for something else than its site key (Machines on Machines holds `knowledge-corpus-ai-ml-research`, `-journalism` and `-history`, not `knowledge-corpus-machines-on-machines`) needs `--all-corpora` or `--corpus-key`; `--site machines-on-machines` alone finds nothing.

Order: deploy the data API (schema and indexes) and the engine, dry-run, write, dry-run again (every corpus must report `changed 0`), then release the index-backed References page to the site. Backfill before the page is released: until then the page would show only keyed References.

## Rollout

The Python client now asks for these fields on every Reference read and write, so a site's backend must have the schema before the engine that carries these writers reaches that site's tools: deploy the data API first, then the router and operator tools. Adding the indexes makes DynamoDB build them from existing items, which have no keys until the backfill runs: the page sees only References the backfill or a writer has keyed. The star index is the same: until the backfill runs, Quality and a minimum show only References starred since `setReferenceStars` began writing `starFeedKey`. A site whose schema lacks the star index fails a Quality or minimum read with an error and a Retry (the feed and Newest are unaffected); the Python client drops `starFeedKey` from its reads on such a site (`NEWER_REFERENCE_FIELDS`) rather than failing every Reference read.
