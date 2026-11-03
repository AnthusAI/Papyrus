# Reference feed indexes

The newsroom References page used to download every Reference, every ReferenceAttachment and every relevance decision on each visit and rank them in the browser. It now reads one page at a time from one of two indexes on `Reference`. This page says what the keys are, who keeps them right, and how to fill them for References that already exist.

The page's search box does not use these indexes; it asks `searchReferences` ([reference search](reference-search.md)).

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

The page reads `<corpusId>#unrated` for "Unrated" and both partitions for "All", merging the two streams with the same comparator.

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
| `records.py` supersede | A superseded version loses `feedStateKey`. |

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

It reads each current Reference of a corpus by curation status (`referencesByCurationStatusKey`, partition `<corpusId>#pending|accepted|rejected|archived`, no other filter), takes the current `relevance_decision_is` decision as its prediction, and writes only the five fields above (`id` plus the fields it changes). It never touches a vote, a curation field or a relation, keeps a prediction a Reference already has, and writes nothing on a second run. A Reference with no decision gets keys and sorts as 0.5. Writing a Reference refreshes its `updatedAt`, which Amplify maintains; `curationStatusUpdatedAt` is untouched. The first write also makes a site's home-page trigger schedule one debounced snapshot, because `feedStateKey` is one of its watched fields.

`--site KEY` means the corpus `knowledge-corpus-KEY`. It does not choose the backend: the CLI talks to the backend it is configured for (`PAPYRUS_GRAPHQL_ENDPOINT` or `amplify_outputs.json`). A publication whose References sit in corpora named for something else than its site key (Machines on Machines holds `knowledge-corpus-ai-ml-research`, `-journalism` and `-history`, not `knowledge-corpus-machines-on-machines`) needs `--all-corpora` or `--corpus-key`; `--site machines-on-machines` alone finds nothing.

Order: deploy the data API (schema and indexes) and the engine, dry-run, write, dry-run again (every corpus must report `changed 0`), then release the index-backed References page to the site. Backfill before the page is released: until then the page would show only keyed References.

## Rollout

The Python client now asks for these fields on every Reference read and write, so a site's backend must have the schema before the engine that carries these writers reaches that site's tools: deploy the data API first, then the router and operator tools. Adding the two indexes makes DynamoDB build them from existing items, which have no keys until the backfill runs: the page sees only References the backfill or a writer has keyed.
