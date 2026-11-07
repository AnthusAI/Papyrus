# Request meter, request budgets and batched reads

AppSync bills per request, and the bad days came from loops that sent one request per row. The Python GraphQL client therefore counts every request it sends, says who sent it, warns when a process spends more than its input justifies, and sends reads for many rows as one request. Code: `src/papyrus_content/request_meter.py`, `src/papyrus_content/batched_reads.py`, `PapyrusGraphQLAuthoringClient` in `src/papyrus_content/graphql_authoring.py`. Specs: `features_backend/request-meter.feature`, `features_backend/batched-reads.feature`. Design and roadmap (steps 1 and 2): the no-order-N design.

## What is counted

One count per HTTP attempt to AppSync made through `PapyrusGraphQLAuthoringClient` (a retry is a second request, as AppSync bills it). Each count is tagged with the caller, the model and the GraphQL operation name. TypeScript Lambdas (content-actions, the site backends) are not covered here.

| Process | Caller name | Summary goes to |
|---|---|---|
| `papyrus <group> <command>` | `cli:<group> <command>` | one line on stderr |
| Router Lambda | `lambda:router:<task>` (`lambda:router` with no task) | JSON log line |
| Procedure runner Lambda | `lambda:procedure-runner:<procedureKey>` | JSON log line |
| A stage's own child process | `stage:<procedureKey>` (the runner sets `PAPYRUS_REQUEST_CALLER`) | JSON log line |
| Any other process that sends a request | `process:<script>` | at exit |

The CLI line reads: `papyrus requests: cli:references show total=3 budget=3/216 units=2 top: Reference.GetReference x3`. A Lambda writes `{"event": "papyrus_request_summary", "caller": ..., "requests": ..., "budget": ..., "units": ..., "aliasedReads": ..., "unboundedLists": {...}, "top": {...}}`. Find them in CloudWatch Logs Insights with `filter event = "papyrus_request_summary" | stats sum(requests) by caller`.

## Budgets

A run's budget is `base + per_unit x units`, from the table `BUDGETS` in `request_meter.py` (longest matching caller prefix). Units are what the run says it handled: the ids and arguments named on the command line, the deliveries in a router pass, the votes and waiting References in an auto-accept pass. The numbers are first guesses; recalibrate them from the first week of summaries.

Going over the budget **warns once and the process continues**:

`WARNING papyrus request meter: cli:references show has made 217 AppSync requests outside named sweeps, over its budget of 216 (200 + 8 x 2 units). It continues; see docs/request-meter.md. Top: Reference.GetReference x217`

- **Stopping is a switch, off by default.** `PAPYRUS_REQUEST_BUDGET_MODE=stop` makes the process raise `RequestBudgetExceeded` at the crossing. Decision (2026-11-06): turn it on after about a week of warnings, not before 2026-11-13 (`ENFORCE_NOT_BEFORE`), once the summaries show which callers need a larger base.
- **Override:** `papyrus ... --budget N` (stripped before the command sees it) or `PAPYRUS_REQUEST_BUDGET=N`. The override and the default it replaces are logged (`papyrus_request_budget_override`).
- **Named sweeps are exempt.** A CLI command whose name says it sweeps (`backfill`, `repair`, `migrate`, `import`, `export`, `rebuild`, `audit`, the `knowledge` group; see `SWEEP_COMMAND`) declares itself a sweep, and code can wrap a section in `with request_meter.sweep("name"):`. Their requests are counted under the sweep name and never checked against the budget.

## Unbounded lists

`list_records(model)` reads every row, one request per 100. Outside `sweep(...)` it logs `papyrus_unbounded_list` (once per model per run) and counts it in the summary's `unboundedLists`. Its requests also count toward the budget, so a large table trips the warning. A static test, `src/papyrus_content/whole_table_reads_test.py`, records how many `list_records`, `safe_list_records` and `list_published_item_summaries` calls each file makes in `src/papyrus_content/data/whole_table_reads.json` and fails when a file makes more than it is allowed, so a new whole-table read cannot merge unnoticed. It finds method calls by name, so a read through an alias or `getattr` is invisible to it; the runtime log catches those. Convert a call, then lower the file's count with `--write`.

## Batched reads

`client.get_many(model, ids)` and `client.index_many(index, keys, limit=100)` send 25 reads per request as GraphQL aliases (the size `runAliasedIndexReads` uses in `components/news-desk-taxonomy-client.ts`). They return what the per-id and per-key reads return, finish any partition that has a second page, and apply the tenant rule. `get_records_by_id` uses `get_many` for every model that has a get query; it no longer reads the whole table above 100 ids. `batched_reads.py` has the helpers for References (`current_relations_of_many`, `attachments_of_many`, `references_by_id`). Used by: auto-accept (voted and waiting References' Cyclotron verdicts, rule-monitor detection) and the router's prediction requests (the Reference and its relations, 100 requests ahead).

## Confirming that one aliased request is one request

After the release, check from CloudWatch that AppSync counts a batch once. Read-only, with `AWS_PROFILE=papyrus-production AWS_REGION=us-east-1`:

1. Pick a window after a router `auto-accept` pass, for example 15 minutes, and a site's API id (`GraphQLAPIId` dimension of the `AWS/AppSync` namespace).
2. Sum the pass's own count from its log summaries: Logs Insights on the router log group, `filter event = "papyrus_request_summary" and caller like /auto-accept/ | stats sum(requests) as requests, sum(aliasedReads) as aliasedReads`.
3. Read the API's request count for the same window: `aws cloudwatch get-metric-statistics --namespace AWS/AppSync --metric-name Latency --dimensions Name=GraphQLAPIId,Value=<api-id> --start-time <t0> --end-time <t1> --period 60 --statistics SampleCount`, and add the points.
4. If the batching is billed as designed, the SampleCount over a quiet window is close to `requests` (plus whatever else used that API in the window), and is far below `requests + aliasedReads`. A batch of 25 that showed as 25 samples would put the SampleCount near `requests + aliasedReads`.
5. For a cleaner test, run one `papyrus` command that reads 100 ids against a site no one else is using at that moment (its stderr line says `total=4`) and compare the SampleCount for that minute with 4 and with 100.
