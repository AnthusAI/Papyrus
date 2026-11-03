# Reference search

The newsroom References page has one search box above Sort and Show. It runs a word search and a meaning search together over every Reference of the site, whether it is unrated, accepted or rejected, and answers with the ordinary cards the feed shows. It exists so an editor can find a Reference again. (`/newsroom/search` is a different page and is unchanged; it searches accepted References only.)

## What an editor sees

- Press Enter to search. The query is in the address as `?q=`, so a search can be linked and the browser's Back button follows it.
- While a search is open, Sort reads **Relevance** (the saved Best bets or Newest comes back when the search is cleared) and Show opens on **All** without changing the choice saved in this browser. Unrated, All and Rated still narrow the search.
- Cards are the feed's own cards with no lead card and no new-items pill. Each says how it matched, in words: `Matched: title, author`, `Matched: meaning`, `Matched: title and meaning`. A card voted on stays where it is. Paging is the feed's infinite scroll.
- Nothing matches: `No References match "..."`. Nothing matches within a narrowed Show: `No unrated matches` (or `No rated matches`) with a **Show all** button.
- One search could not run: the other's results stay, with `Searched by words only: meaning search is unavailable` (or the reverse) and a Retry. Both could not run: the feed's own error with its Retry.

## The query

`searchReferences(input: AWSJSON!): AWSJSON` is a query on the same Lambda as `knowledgeQuery` (`amplify/functions/knowledge-query`, dispatched on the AppSync `fieldName` in `src/papyrus_knowledge_query/lambda_handler.py`). It is for the `editor` and `admin` groups (`allow.groups(categoryWriteGroups)`), has no subscription, and the Lambda checks the caller's groups again. It is defined in both `amplify/data/schema.ts` and `amplify/data/resource.ts`.

```
input:  { query, show: "unrated" | "rated" | "all", limit?: 24 (1 to 100), cursor? }
output: { items: [{ reference, matchedBy: ["keyword"|"meaning"], matchedFields: ["title"|"authors"|"sourceUri"|"externalItemId"] }],
          nextCursor, lanes: { keyword: { status, message? }, meaning: { status, message? } } }
```

`reference` is the whole Reference row the feed reads, so the page draws it as any other card. `status` is `ok` or `failed`; a failure carries a sentence that is safe to show.

## Word search

`src/papyrus_knowledge_query/reference_search.py`. A plain-Python inverted index held in the Lambda's memory over four fields of the Reference row: title, authors, source URL and `externalItemId`. Nothing is read per Reference. Body and summary words are not searched.

- **Filling it.** The first query after a cold start reads every current Reference from `listReferencesByVersionStateAndUpdatedAt` (partition `current`, oldest first, 1000 a page; a Reference's curation status does not change its version state, so rejected References are in it) and logs `reference-search index built: N rows read, M kept, T ms`. Each later query reads only rows whose `updatedAt` is at or after the last row seen less two minutes, keyed by lineage, so a Reference changed a moment ago is found. A row with no `feedStateKey` (archived, or not the current version) is dropped; an older version never replaces a newer one. Because the read is oldest first and resumes from the greatest `updatedAt` seen, a cold read cut short by AppSync's 30 second limit continues on the next query. Nothing is cached outside the Lambda in this phase.
- **Terms.** Lower-cased, accents folded, split on anything that is not a letter or digit. Stop words are dropped unless nothing else is left. A term of three or more letters also matches the beginning of a longer word, as one types it.
- **Order.** Exact title phrase, all terms in the title, all terms across the four fields, then some terms; inside a class, more terms and heavier fields first (title and authors, then id, then link), then the most recent arrival.

## Meaning search

`QueryVectors` through `S3VectorsProvider.query_by_vector` with the query embedded once by `embed_text`: `reference_summary` vectors whose `curationStatus` is in what Show asks for (unrated: `pending`; rated: `accepted`, `rejected`; all: the three), top 100 (S3 Vectors' limit), nearest first, one entry per Reference, cut where the similarity drops most (`papyrus_knowledge_query/cuts.py`, `knee_cut_count`). The result is held in the Lambda for five minutes per query so paging does not embed again. A meaning result for a Reference the word index does not hold (no `feedStateKey`) is dropped, and Show is checked again against the Reference's own feed state, not the vector's.

**Rejected References have no vectors today**, so only the word search can find a rejected Reference. That is expected for this phase.

## Merging, paging, failure

Reciprocal Rank Fusion, `1 / (60 + rank)` summed over the lanes a Reference is in, one entry per lineage. A Reference found by every word of the query (a strong word match) always sits above one found only by meaning or by some of the words; inside each group, a Reference found both ways ranks above the same rank in one lane. The cursor is opaque: an offset and a hash of the query and Show choice, and a cursor from another search is refused. If one search fails the other's results are returned with the failed search's status; the meaning search is given 20 seconds.

## From the command line

`papyrus references search "agent memory" [--site HOST] [--show unrated|rated|all] [--limit N] [--cursor C] [--json]` asks the same query with the `papyrus login` session. It is read-only: one query, no mutation, no AWS credentials. Without `--json` it lists each Reference with how it matched and the next cursor.

## Deploying

The schema (one new query) and the `knowledgeQuery` Lambda change, so the data API and function deploy together through the site's Amplify pipeline; nothing else changes and no backfill is needed (the feed keys are the ones in [reference feed indexes](reference-feed-indexes.md)). The meaning search needs the site's `OPENAI_API_KEY` secret and the vector index, as `knowledgeQuery` does; without them the page still searches by words and says so. The Lambda is a Lambda-backed query, not a JavaScript resolver, so it has no resolver entry file or APPSYNC_JS lint to get wrong.

## Tests

`procedures/newsroom/tests/test_reference_search.py` (index, ranking, fusion, cursor, failure), `test_references_search_cli.py` (the command, no mutation), `features_backend/reference-search.feature` (behave), `scripts/test-reference-feed-search.ts` and the `search` scenario of `scripts/test-reference-feed.ts` at 375 and 1440 pixels, and `features/newsroom-reference-search.feature` (Cucumber).
