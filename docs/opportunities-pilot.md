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

## Capture with the site's existing X connection

This option requires the site frontend and data stack that include the Opportunities search change. The current pilot supports only a dedicated Papyrus site with a fixed tenant ID, the shared-monitoring spend ledger wiring, a person-only console client configured and a connected X account whose grant includes `tweet.read` and `users.read`. If this is not in the site's build, the capture action is not ready. Do not regenerate a bearer token, replace the app secret or reconnect a working account for this feature.

1. A person signed in as an admin opens **Administration → Announcements → Opportunities search**. Leave it off by default. To opt in, enter a distinct search allowance, the existing X billing cycle day and the current [X post and user read prices](https://docs.x.com/x-api/getting-started/pricing). Save search settings. If the X account lacks [Recent Search](https://docs.x.com/x-api/posts/search-recent-posts), the provider can still refuse the first attempt.
2. A person signed in as an editor or admin enters an exact query from the shortlist and clicks **Search X**. The button shows the worst-case reservation. Each click requests one page of ten posts, without fetching a second page or retrying. Download the resulting JSON capture. Use that file with the matching Reference record or records (the query strings in the records must match; combine captures by exact query to match several in one run).

```sh
PYTHONPATH=src python3 -m papyrus_content.opportunities \
  --references my-approved-references.json --posts ~/Downloads/x-opportunities-capture.json --max-reads 10
```

The site's existing connection authorizes one server-side GET. The server never returns credentials; it drops posts whose author is protected, withheld or not confirmed public. It requests only author expansions needed to establish visibility and does not return the profiles or follow the provider cursor. The server reserves the page's maximum estimated cost in a separate tenant-and-account-scoped allowance before any provider call. This reservation is deliberately not refunded after a call, including a timeout or ambiguous result; the receipt separates reserved allowance, provider resource counts and estimated cost. X remains the source of actual charges; set the correct tariff and use X's own account/project controls for charges outside this feature. The existing announcement sender and its separate allowance are unchanged. An admin can turn search off without disconnecting X.

A standalone direct search with a separately provisioned application token is not necessary for the connected-site workflow. The independent command's `PAPYRUS_X_BEARER_TOKEN` input is for a separate read-only app if already authorized and securely provisioned, not a reason to export, replace, or generate a token for a working site connection.

Open the target and thread links in X and check that the thread is still active, the proposed point adds something new, and the source supports it. Candidates are deterministic phrase matches, not a semantic or full-thread assessment. Threads dedupe within a run, an already cited source in the candidate post is skipped when recognized, and at most five candidates are shown by default. No matches is a valid result. A person decides whether to post, and posts manually outside this tool. See [X's automation policy](https://help.x.com/en/rules-and-policies/x-automation).
