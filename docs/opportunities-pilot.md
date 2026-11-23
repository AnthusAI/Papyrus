# Papyrus Opportunities: on-demand pilot

Given a publication's approved References, look for public X conversations where an editor could add a specific, sourced point. This pilot suggests places to review. It cannot post, reply, like, message, schedule anything, or modify a Reference.

## Prepare a Reference shortlist

Make a JSON array with one record per useful Reference. Each record needs its `title`, original public source `url`, an X Recent Search `query`, distinctive `keywords` to match, and the `contribution` the editor can actually support. Optionally include an exact `evidence` passage and a verified public Papyrus `public_note_url`. An internal newsroom link is not a public note. Start with a few narrow queries, not a broad topic dump. Use only source material suitable for public discussion. See [example input](../features_backend/fixtures/opportunities/references.json).

## Run without X access

From the Papyrus checkout:

```sh
PYTHONPATH=src python3 -m papyrus_content.opportunities \
  --references features_backend/fixtures/opportunities/references.json \
  --posts features_backend/fixtures/opportunities/recorded-search.json \
  --max-reads 10
```

The sample returns two synthetic opportunities, not live places to reply. For an existing capture, `--posts` expects the same JSON shape: exact query strings as keys, each containing the search response object (`data` and optional `meta`). Offline read counts count rows in the capture, not network reads or charges.

## Run against the X API

Use a securely injected `PAPYRUS_X_BEARER_TOKEN` from an X app entitled to [Recent Search](https://docs.x.com/x-api/posts/search/introduction). Do not put the token on the command line, in a fixture, or in Git. The live command is the same without `--posts`; replace the example References with the intended publication's shortlist.

The utility makes only GET requests to X Recent Search. The effective number of distinct queries multiplies the API's ten-post minimum; use `--max-reads 30` for three distinct queries. It makes one bounded request per query; it does not page, retry, or run scheduled searches. The output includes posts returned and the sum of the requested limits. An optional `--price-per-read` reports an estimate, not a receipt for X charges; check [the app's current price](https://docs.x.com/x-api/getting-started/pricing) before using it.

Open the target and thread links in X and check that the thread is still active, the proposed point adds something new, and the source supports it. Candidates are deterministic phrase matches, not a semantic or full-thread assessment. Threads dedupe within a run, an already cited source in the candidate post is skipped when recognized, and at most five candidates are shown by default. No matches is a valid result. A person decides whether to post, and posts manually outside this tool. See [X's automation policy](https://help.x.com/en/rules-and-policies/x-automation).
