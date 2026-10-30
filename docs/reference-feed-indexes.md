# Reference feed indexes

The newsroom References page used to download every Reference, every ReferenceAttachment and every relevance decision on each visit and rank them in the browser. It now reads one page at a time from one of two indexes on `Reference`. This page says what the keys are, who keeps them right, and how to fill them for References that already exist.

## The fields

| Field | Meaning |
| --- | --- |
| `feedStateKey` | `<corpusId>#unrated` for a pending Reference, `<corpusId>#rated` for an accepted or rejected one. Null (so in no feed) for an archived Reference or one that is not the `current` version. |
| `feedArrivalAt` | When the Reference reached the newsroom: the first parseable of `createdAt`, `importedAt`, `retrievedAt`, `sourcePublishedAt`, `versionCreatedAt`, as a UTC instant with milliseconds. The epoch if none parses, so a Reference never drops out of the index. |
| `predictedAcceptProbability` | The Cyclotron's original P(accept): the confidence of the include label, or one minus the confidence of the exclude label. Null until the Cyclotron has decided it. |
| `predictionDecidedAt` | When that decision was made. |
| `predictionSortKey` | `<P to six places>#<feedArrivalAt>#<id>`. An unpredicted Reference sorts as 0.5: after every predicted Accept, before every predicted Reject. |

The prediction is a value on the original record, written once. A later decision, a vote and a re-delivery do not rewrite it.

## The indexes

Both are partitioned by `feedStateKey`.

- `listReferencesByFeedStateAndPrediction` (sort key `predictionSortKey`), read descending: **Best bets**. Highest P(accept) first, ties newest first.
- `listReferencesByFeedStateAndArrival` (sort key `feedArrivalAt`), read descending: **Newest**.

The page reads `<corpusId>#unrated` for "Unrated only" and both partitions for "Include rated", merging the two streams with the same comparator.

## Who keeps the keys right

| Writer | What it does |
| --- | --- |
| `catalog.reference_record` (monitor intake, imports, accession, GROBID citations) | Sets `feedStateKey`, `feedArrivalAt` and an unpredicted `predictionSortKey` when it creates a Reference. An import of an existing Reference never rewrites a stored prediction or arrival. |
| `monitoring_router.record_original_prediction` | After a delivery, writes the prediction fields once from the Cyclotron's decision. |
| `relevance_sweep` | Same, for References the decide-relevance sweep decides. |
| `auto_accept.py`, `auto_reject.py` | Move the Reference to `#rated`. |
| `reviewReferenceCuration` (`amplify/functions/category-action/handler.ts`) | An editor's accept or reject moves it to `#rated`; reopen moves it to `#unrated`; archive clears the key. A corpus move recomputes the keys for the new version. |
| `records.py` supersede | A superseded version loses `feedStateKey`. |

The key functions live in `src/papyrus_content/reference_feed_keys.py` and `lib/reference-feed-keys.ts`; `scripts/fixtures/reference-feed-key-vectors.json` holds the vectors both test.

## Backfill

```bash
papyrus references backfill-feed-keys --site KEY --dry-run     # counts only
papyrus references backfill-feed-keys --site KEY               # writes
```

It reads each current Reference of the publication's corpus (`knowledge-corpus-KEY`, or `--corpus-key`) by curation status, takes the current `relevance_decision_is` decision as its prediction, and writes only the five fields above. It never touches a vote, a curation field or a relation, keeps a prediction a Reference already has, and writes nothing on a second run. Writing a Reference refreshes its `updatedAt`, which Amplify maintains.

## Rollout

The Python client now asks for these fields on every Reference read and write, so a site's backend must have the schema before the engine that carries these writers reaches that site's tools: deploy the data API first, then the router and operator tools. Adding the two indexes makes DynamoDB build them from existing items, which have no keys until the backfill runs: the page sees only References the backfill or a writer has keyed.
