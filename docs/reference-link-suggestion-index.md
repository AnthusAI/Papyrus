# Link suggestion index

The Needs me queue shows the links the vector index suggests (a Reference to a Reference, or to a concept) and an editor works through them from the top, so the most likely ones must come first out of all of them. It used to read the reference-link feed newest first, filter to open suggestions in the browser, and rank only the rows it had read. A site with thousands of suggestions showed whichever few were newest. It now reads one page at a time from a sparse index on `SemanticRelation` that holds only open suggestions, sorted by their close match.

## The fields

| Field | Meaning |
| --- | --- |
| `openSuggestionKey` | `reference-links#suggested` while the row is a `suggested` link, null (so in no index) otherwise. One shared value, so the whole queue is one partition. |
| `openSuggestionScore` | The sort value (a float): the row's `score` (the close match, a cosine similarity), or `-2` when the row has no usable score, which is below every real similarity, so a row with no close match is still returned, last. Null whenever the key is null. |

`score` is nullable, which is why the index does not sort on it directly: DynamoDB leaves a row out of an index when its sort attribute is missing.

## The index

`listSemanticRelationsByOpenSuggestionAndScore` (partition `openSuggestionKey`, sort `openSuggestionScore`), read descending. `ReferenceLinksStore.listSuggested(cursor)` asks for 50 rows, resolves both ends of each, and returns the page with the `nextToken` as its cursor: one request is one page, in the server's order, and "Load more link suggestions" asks for the page after it. Ties in the close match come out in an order DynamoDB chooses and keeps stable across pages. There is no post-read filter, no read-on loop and no client-side sort.

## Who keeps the fields right

| Writer | What it does |
| --- | --- |
| `reference_links._write_edge` (`link_references`, `link_concept`; the vector pass, `suggest-links`, the `suggestReferenceLinks` action) | A `suggested` write sets both fields from the score. A write that makes the row `current` over an existing row (a person's link over a suggestion) sets both to null. A new row that is not a suggestion carries neither field. A suggestion written over a row that is no longer `suggested` is not written at all (a person's decision is never overwritten and the row never returns to the index). |
| `reference_links.decide` | An accept or a reject sets both to null in the same update. |
| `buildHumanEdgeRow` and `decideReferenceLink` (`amplify/functions/category-action/reference-links.ts`, the editor's `createReferenceLink` and `decideReferenceLink` mutations) | The same clearing, byte-for-byte (`scripts/fixtures/reference-link-row-vectors.json` holds the vectors both languages test). |

## Backfill

```bash
papyrus references backfill-suggestion-index --dry-run     # counts only
papyrus references backfill-suggestion-index               # writes
```

The `papyrus` CLI writes unless `--dry-run`. It reads every row of the `reference-links` feed (all states), sets both fields on each `suggested` row, clears them from any other row that carries them, and writes only those two fields, so it undoes no decision. A row that is already right is not written, so a second run writes nothing. `--json` prints the counts (`scanned`, `openSuggestions`, `keyed`, `unscored`, `keysCleared`, `alreadyRight`, `written`).

## Rollout

Adding the index makes DynamoDB build a global secondary index on `SemanticRelation` from the existing rows. They carry no key, so the index starts empty.

1. Deploy the site backend that carries the schema change (the new fields, the index, the `category-action` change). DynamoDB allows one index creation or deletion per table update, so this must be the only schema change in that site deploy: do not bundle another new index on any model with it, and wait for the index to be `ACTIVE`.
2. Run `papyrus references backfill-suggestion-index --dry-run`, then without `--dry-run`, for that site.
3. Only then let the monitoring router and the operator tools of that site carry the writer: they send the two new fields on every suggestion they write, which a backend without the schema refuses.

Between steps 1 and 2 the Needs me Links pill shows only the suggestions written or rewritten after the deploy: the new reading has no fallback to the old feed read. Related sections are unaffected (they read by state key). Decisions made in that window clear the key as usual.
