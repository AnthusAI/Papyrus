# Reference search

The newsroom References page has one search box above Sort and Show. It runs a word search and a meaning search together over every Reference of the site, whether it is unrated, accepted or rejected, and answers with the ordinary cards the feed shows. It exists so an editor can find a Reference again. (`/newsroom/search` is a different page and is unchanged; it searches accepted References only.)

## What an editor sees

- Press Enter to search. The query is in the address as `?q=`, so a search can be linked and the browser's Back button follows it.
- While a search is open, Sort reads **Relevance**, **Newest** and **Quality**. It opens on Relevance (how well each Reference matches) and is not saved; the saved Best bets or Newest comes back when the search is cleared. Show opens on **All** without changing the choice saved in this browser. Unrated, All and Rated still narrow the search.
- **Minimum stars** (Any, 3+, 4+, 5) applies to a search too, and is the same saved choice the feed uses: a search keeps only the matches with at least that many stars. Newest orders the matches by arrival. Quality puts the most stars first, newest first within a star level, and keeps the unstarred matches after the starred ones (a search never loses a match to Quality; only a minimum drops them). Choosing Quality or a minimum while the search's Show is Unrated moves it to All. Nothing matches under a minimum: `Nothing matches "..." with 4 or more stars.` with a **Show any stars** button.
- Cards are the feed's own cards with no lead card and no new-items pill. Each says how it matched, in words: `Matched: title, author`, `Matched: meaning`, `Matched: title and meaning`. A card voted on stays where it is. Paging is the feed's infinite scroll.
- Nothing matches: `No References match "..."`. Nothing matches within a narrowed Show: `No unrated matches` (or `No rated matches`) with a **Show all** button.
- One search could not run: the other's results stay, with `Searched by words only: meaning search is unavailable` (or the reverse) and a Retry. Both could not run: the feed's own error with its Retry.

## The query

`searchReferences(input: AWSJSON!): AWSJSON` is a query on the same Lambda as `knowledgeQuery` (`amplify/functions/knowledge-query`, dispatched on the AppSync `fieldName` in `src/papyrus_knowledge_query/lambda_handler.py`). It is for the `editor` and `admin` groups (`allow.groups(categoryWriteGroups)`), has no subscription, and the Lambda checks the caller's groups again. It is defined in both `amplify/data/schema.ts` and `amplify/data/resource.ts`.

```
input:  { query, show: "unrated" | "rated" | "all", limit?: 24 (1 to 100), cursor?,
          sort?: "relevance" (default) | "newest" | "quality", minStars?: null | 3 | 4 | 5 }
output: { items: [{ reference, matchedBy: ["keyword"|"meaning"], matchedFields: ["title"|"authors"|"sourceUri"|"externalItemId"] }],
          nextCursor, lanes: { keyword: { status, message? }, meaning: { status, message? } } }
```

`sort` and `minStars` are checked: another `sort`, or a `minStars` that is not 3, 4 or 5 (never "only 3" or "only 2"), is refused with a `SearchError`. They apply after fusing: `minStars` drops the matches with fewer stars (an unstarred match has none), then a stable sort orders what is left (`newest`: `feedArrivalAt` descending; `quality`: stars descending, unstarred last, then `feedArrivalAt` descending; `relevance`: the fused order, unchanged). A stars value that is a float, null or absent never breaks the order: only a whole number from 1 to 5 counts as stars, anything else is none. Stars order and narrow; they never decide what matches and never reach the Cyclotron.

`reference` is the whole Reference row the feed reads, so the page draws it as any other card. `status` is `ok` or `failed`; a failure carries a sentence that is safe to show.

## Word search

`src/papyrus_knowledge_query/reference_search.py`. A plain-Python inverted index held in the Lambda's memory over four fields of the Reference row: title, authors, source URL and `externalItemId`. Nothing is read per Reference. Body and summary words are not searched.

- **Filling it.** The first query after a cold start reads every current Reference from `listReferencesByVersionStateAndUpdatedAt` (partition `current`, oldest first, 1000 a page; a Reference's curation status does not change its version state, so rejected References are in it) and logs `reference-search index built: N rows read, M kept, T ms`. Each later query reads only rows whose `updatedAt` is at or after the last row seen less two minutes, keyed by lineage, so a Reference changed a moment ago is found. A row with no `feedStateKey` (archived, or not the current version) is dropped; an older version never replaces a newer one. Because the read is oldest first and resumes from the greatest `updatedAt` seen, a cold read cut short by AppSync's 30 second limit continues on the next query. Nothing is cached outside the Lambda in this phase.
- **Terms.** Lower-cased, accents folded, split on anything that is not a letter or digit. Stop words are dropped unless nothing else is left; they include question words (`why`, `how`, `what`, `do`, `does` and the like), so a typed question is searched by its content words. A term of three or more letters also matches the beginning of a longer word, as one types it.
- **Order.** Exact title phrase, every term in the title or the authors, every term across the four fields, then some terms; inside a class, the larger share of the query's distinctive weight first, then heavier fields (title and authors, then id, then link), then the most recent arrival.
- **Rarity.** Each term is weighed by how rare it is in this site's index, `ln(1 + N / df)` where `df` is how many References hold the term (or a word it begins). "neural" in a third of the titles counts for little; "forget" in a few counts for a lot. A Reference's `coverage` is the weight of the terms it holds over the weight of the query.
- **Partial matches of a long query.** For a query of three or more distinctive terms, a Reference holding only some of them is kept only if its `coverage` is at least `PARTIAL_COVERAGE_FLOOR` (one half). A title with only "neural networks training" from a seven-word question is a common-word match, and the meaning search answers such a question better. Queries of one or two terms keep every partial match (with two terms, one is already half the question), ranked by `coverage` so the rarer word comes first. Because the floor is applied in the word lane, it also holds when the meaning search is down.

## Meaning search

`QueryVectors` through `S3VectorsProvider.query_by_vector` with the query embedded once by `embed_text`: `reference_summary` vectors whose `curationStatus` is in what Show asks for (unrated: `pending`; rated: `accepted`, `rejected`; all: the three), top 100 (S3 Vectors' limit), nearest first, one entry per Reference, cut at the bend of the whole similarity curve (`papyrus_knowledge_query/cuts.py`, `search_cut_count`). The list is already bounded by the 100 S3 Vectors returns, so there is no cap of our own. The result is held in the Lambda for five minutes per query so paging does not embed again. A meaning result for a Reference the word index does not hold (no `feedStateKey`) is dropped, and Show is checked again against the Reference's own feed state, not the vector's.

**Why a cut for a search list is not the cut for link suggestions.** `knee_cut_count` keeps everything before the largest single drop among the first half of the scores. That suits link suggestions, which want a few sure links. On a neighbour list for a question, where one hit stands clear of a smoothly falling tail, the largest drop is between the first and second score, so the cut kept one Reference, and it was usually the one the word search had found already: the meaning lane contributed no card of its own (the live "why do neural networks forget earlier training" search showed one "title and meaning" card and no "meaning" card). `search_cut_count` scales ranks and scores to 0..1 and cuts at the point farthest from the straight line between the first and last score: a steep start that flattens keeps the steep part, a plateau that falls keeps the plateau, a flat list is kept whole. It adapts to each list and needs no constant. Its trade-off is recall over precision, which is right behind exact word matches because meaning matches rank below them. Whether the live vectors have thin coverage (the summaries of References not yet embedded) cannot be told from the code; the cut is what the code shows.

**Rejected References have no vectors today**, so only the word search can find a rejected Reference. That is expected for this phase.

## Merging, paging, failure

One entry per lineage, in tiers, best first:

1. an exact title phrase;
2. every term in the title or the authors;
3. every term across the four fields;
4. a meaning match (alone, or with some of the words);
5. a partial word match found by words alone.

Inside a tier, Reciprocal Rank Fusion, `1 / (60 + rank)` summed over the lanes a Reference is in, so a Reference found both ways ranks above the same rank in one lane; then the lineage id, a fixed order. A partial word match never outranks a meaning match, and "Hinton" (one term, in the authors) behaves as before: every author match first. The cursor is opaque: an offset and a hash of the query, Show choice, sort and minimum stars, and a cursor from another search or another ordering is refused. If one search fails the other's results are returned with the failed search's status; the meaning search is given 20 seconds.

## From the command line

`papyrus references search "agent memory" [--site HOST] [--show unrated|rated|all] [--limit N] [--cursor C] [--json]` asks the same query with the `papyrus login` session. It is read-only: one query, no mutation, no AWS credentials. Without `--json` it lists each Reference with how it matched and the next cursor.

## Deploying

The schema (one new query) and the `knowledgeQuery` Lambda change, so the data API and function deploy together through the site's Amplify pipeline; nothing else changes and no backfill is needed (the feed keys are the ones in [reference feed indexes](reference-feed-indexes.md)). The meaning search needs the site's `OPENAI_API_KEY` secret and the vector index, as `knowledgeQuery` does; without them the page still searches by words and says so. The Lambda is a Lambda-backed query, not a JavaScript resolver, so it has no resolver entry file or APPSYNC_JS lint to get wrong.

## Tests

`procedures/newsroom/tests/test_reference_search.py` (index, ranking, fusion, cursor, failure), `test_references_search_cli.py` (the command, no mutation), `features_backend/reference-search.feature` (behave), `scripts/test-reference-feed-search.ts` and the `search` scenario of `scripts/test-reference-feed.ts` at 375 and 1440 pixels, and `features/newsroom-reference-search.feature` (Cucumber). The sort and minimum are tested in the same files (`test_reference_search.py`, `reference-search.feature`, `test-reference-feed-search.ts`) and in the `quality` scenario of `scripts/test-reference-feed.ts` (`features/newsroom-reference-quality.feature`).
