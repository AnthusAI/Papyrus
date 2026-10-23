# Automations

An automation is a named record in a site's own backend that says "when this happens, run that procedure with
this input". It is the background-automation epic (PPY-9ff95b). The smallest useful version wraps what already
runs: Distinctive Mark's TTAB monitor starts its ruling-analysis procedure for each new decision. The record
describes that, links to it, controls it, costs it and shows what it did.

## What is live and what is not

| Part | Today |
|---|---|
| `monitor` triggers | Live, because the monitoring router already runs them. The router's `procedureTriggers` entry still says what starts and with what input; the record mirrors it and now governs it (below). |
| `schedule`, `event`, `manual` triggers | Stored, and shown as "not yet supported". Nothing starts them. |
| `enabled` | **Real for monitor automations.** The router reads the record before each start. A disabled automation starts nothing, and the trigger row says `skipped` with the reason "automation disabled". |
| `limits.timeoutSeconds` | **Enforced.** It goes to the runner with the request and becomes the procedure's deadline, capped at 840 s (the runner Lambda's 15 minutes less its recording margin). |
| `limits.maxConcurrent` | **Enforced at the start, by refusing.** At the limit a new start is not made; the trigger row says `refused` and gives the reason. Nothing is queued. |
| `limits.budgetUsdPerRun` | **Advisory.** A run is never stopped for it. The history compares each run's recorded cost with it and flags a run over it. |
| Cost per run | **Recorded** (below). |
| Run now | **Live** for monitor automations, from the command line and the console. |

The monitoring router, the procedure runner and the registered procedure still own the starting. The router's
`CONFIG#router` entry stays the source of truth for what starts; the record is read for whether it may and with
what limits.

### When the router cannot find or read the record

The router starts exactly as it did before slice 2. This is a deliberate rule, so that a missing, unreadable or
mismatched record can never stop Distinctive's TTAB analysis:

* There is no record for the trigger (no monitor automation with this monitor, publication and procedure), or the
  record's trigger or fields cannot be read: the router starts. The request carries no timeout and no automation id,
  and the trigger row is the same as before.
* The call to read the records fails (the router's role may not read them yet, a timeout, a network error): the
  router starts, as above.
* Counting the runs in flight fails: the router starts.

Two records for the same trigger: the one with the lowest id governs.

### How a run counts as "running" for `maxConcurrent`

A run counts while its row says `starting`, `started` or `running` and it began less than its timeout plus two
minutes ago. The rows are the `TRIGGER#` rows of the procedure and the `MANUAL#` rows (Run now) of the automation, so
a run started by hand counts against the limit too. The runner moves a row to `running` and writes its `runId` as soon as the run exists, and to
`completed`, `failed` or `notRunnable` when it ends. A run whose outcome was never recorded (a crash)
stops counting after its timeout plus the grace, so it cannot block the automation for ever.

Things to know before choosing `maxConcurrent`:

* The default is 1. The TTAB monitor can deliver several new decisions in one sweep, and a start the router
  refuses is not retried by the router: the trigger row is written once per item, and the item's Reference already
  exists on any later sweep. Set `maxConcurrent` to the number you are willing to run at once (for example
  `papyrus automations update --id distinctive.ttab --max-concurrent 4`) before the router starts reading records.
* A `skipped` or `refused` row keeps the resolved request (like any trigger row), so an operator can start that item
  later by hand: `papyrus automations run --id ... --input ...` with the same input.
* Run now never writes a row when it is refused; it tells the person at once.

## Cost

`procedure_runner_child` reports the model usage of each call (agent, model, prompt, completion and cached tokens)
with the procedure's result, even when the procedure fails part way. `run_procedure_request` prices those calls from
`src/papyrus_content/data/model_prices.json` and stores on the `ProcedureRun`:

* `usage`: `{calls, promptTokens, completionTokens, models, complete, unpricedModels, perCall}`; and
* `costUsd`: the estimate in dollars.

The price table is data. Add or correct a model by editing the file (input, output, cached input per million
tokens, and an optional above-a-threshold tier that bills the whole request at the higher rate). GPT-6 Luna is in it
($0.10 input, $0.50 output, $0.01 cached per million tokens; above 272,000 input tokens $0.20 and $0.75; source:
the LiteLLM price table, read 2026-10-11). It is an estimate, not a bill. A model missing from the table is named in
`unpricedModels` and left out of the total, so the estimate says it is partial; it is never counted as free. A run
that made no model call stores no usage and no cost. A run killed at its deadline stores no usage (the child could not
report it).

A site backend that predates the two new fields refuses them. The runner then records the run without them
(its outcome is never lost), and the history shows the cost as not recorded. Deploy the site backend before the
runner image to get costs.

`papyrus automations runs` prints each run's cost and flags `OVER BUDGET`; the console shows it beside each run.

## Run now

* Command line: `papyrus automations run --id distinctive.ttab --input '{"proceeding":"97752244","opinion_url":"https://..."}'`
  (`--dry-run` checks everything and starts nothing; `--json`). It needs the same things `runs` needs (AWS
  credentials that can read the monitoring table through the SSM parameter) plus `dynamodb:PutItem` on it and
  `lambda:InvokeFunction` on `papyrus-procedure-runner` (override with `PAPYRUS_PROCEDURE_RUNNER_FUNCTION`).
* Console: a **Run now** button on the automation, for editors and admins. It does not start on the first click: a
  confirm step says what will run, that it calls a model and counts against the limit, and asks for the input of this
  run. The mutation is `runAutomation(automationId, input)`; it is served by the `papyrus-automation-view` function.

The input is the one you give. If you give none, the record's `inputTemplate` is used only when it names no item
placeholder; the TTAB template does (`{sourceIdPrefix}`, `{documentUrl}`), so for TTAB you give the input.

Run now is refused, with the reason and without a row, when the automation is not a monitor automation, is
disabled, has no router publication for this site, or is at its `maxConcurrent`. Otherwise it:

1. writes `MANUAL#<automationId>#<timestamp>` in the monitor's partition (`MONITOR#<monitorId>`) of the monitoring table,
   with who started it and the runner request, status `starting`;
2. invokes `papyrus-procedure-runner` asynchronously with the automation's `procedureKey`, the input, the router
   publication's endpoint and key parameter, and `timeoutSeconds`; if that fails the row says `startFailed`;
3. the runner sets the row `running` with the `runId` as soon as the run exists, and its outcome at the end.

That row is the link. The history reads `TRIGGER#` rows and `MANUAL#<automationId>#` rows the same way and joins each to its
`ProcedureRun`, so a manual run appears with its status, duration, story and cost, marked "Run now by <who>".

## Started outside this automation

The history also lists the procedure's newest 25 `ProcedureRun` records that no row of this automation links to
(for example a run made with `papyrus procedures run`), under "Started outside this automation", with who started
each one. It is a different list from the automation's own runs and is not counted in its limits. If it cannot be
read, the rest of the history still shows.

## The record

`Automation` (a model in every site's data API; editors read, create and update, admins also delete):

| Field | Meaning |
|---|---|
| `id` | Lowercase letters, digits, dots, dashes, underscores. Fixed once created. |
| `title`, `description` | What a person reads. |
| `enabled` | See above. |
| `trigger` | `{kind, config}`. For `monitor`: `{monitorId, publicationId}`, the monitor and the router publication it delivers to. |
| `procedureKey` | The registered procedure to run (`papyrus procedures register`). |
| `inputTemplate` | Procedure input as templates over the delivered item, with the placeholders in `docs/procedure-runner.md`. |
| `limits` | See above. Defaults: 840 s, 1 at a time. |
| `createdBy`, `createdAt`, `updatedBy`, `updatedAt` | Who and when. |

## The router link

`show` and the Automation page compare the record with the router's own entry for the same publication and
procedure, and say one of: linked, differs (the input template is not the same), not linked (no trigger for
this procedure, the router does not deliver to the publication, or the monitor has no router configuration).
It reads and compares only. Fixing a difference means editing whichever side is wrong.

## Run history

Each run joins two records:

* a row in the monitoring table (`MONITOR#<monitorId>`): a `TRIGGER#<publication>#<procedureKey>#<sourceId>` row (which
  item, when it started, how the start ended) or a `MANUAL#<automationId>#<timestamp>` row (a Run now: who, when). Their
  statuses are `starting`, `started`, `running`, `completed`, `failed`, `startFailed`, `notRunnable`, and for a start that
  never happened `skipped` (the automation is disabled) and `refused` (at its limit), each with its `reason`; and
* the `ProcedureRun` in the site backend, linked by the row's `runId`: its status, start and finish (so the
  duration), error, output, usage and cost. The story the procedure created is the output's `story` (a story lineage
  id), with `version_id` and `title`.

Details worth knowing:

* The runner writes `runId` onto the row as soon as the run exists (status `running`) and its outcome when it ends.
  A run that has only just been started shows as "Started" with no run record yet.
* Items that already had a Reference are never started (`notTriggered`). They are counted, not listed. A `skipped` or
  `refused` start is listed, with its reason.
* A row whose run record cannot be found, or read, says so on that row; the rest of the history still reads.
* A site's console reads only its own publication's rows: the router must list the automation's publication
  with this site's endpoint. The runner's stored request (endpoints, key parameter) is never returned.

## Command line

```bash
papyrus automations list
papyrus automations show --id distinctive.ttab
papyrus automations runs --id distinctive.ttab [--limit 20] [--json]
papyrus automations run --id distinctive.ttab --input '{"proceeding":"97752244","opinion_url":"https://..."}' [--dry-run] [--json]
papyrus automations create --id distinctive.ttab --title "Analyze new TTAB rulings" \
  --monitor ttab --publication distinctive --procedure distinctive.ttab.ruling-analysis \
  --input '{"proceeding":"{sourceIdPrefix}","opinion_url":"{documentUrl}"}' [--dry-run]
papyrus automations update --id distinctive.ttab [--enabled false] [--title T] [--input JSON] \
  [--timeout-seconds N] [--max-concurrent N] [--budget-usd N] [--dry-run]
```

`create`, `update` and `run` use the normal sign-in lane (`papyrus login`, editor or admin); operators can use
`PAPYRUS_GRAPHQL_AUTH=iam`. `runs`, `run` (and the run column of `show`) also need AWS credentials that can read the
monitoring table, found through the SSM parameter `/papyrus/monitoring/table-name`. Without them the records
still list.

## Console

Administration, Automation, beside Procedures. It lists each automation (title, trigger, procedure, enabled,
last run status). Choosing one shows its settings, the router link, a Run now button, its recent runs (started,
duration, status, error or reason, who or which item, run id, the story with a link, cost, flagged if over the advisory
budget) and the procedure's other runs under "Started outside this automation". Status is always words with a mark,
never colour alone. An operator changes the settings with the command line; editors and admins can run now. The page reads
through `automationOverview` and acts through `runAutomation`, both served by the `papyrus-automation-view` function.

### Who may read and who may write

* **Read** (`automationOverview`): editors and admins in the browser, and an operator's IAM role in the site's own
  account, so an agent can read without a browser sign-in. AppSync lets an IAM caller through only when the caller's
  IAM policy allows `appsync:GraphQL` on `Query/fields/automationOverview` of the site's API; the function then admits it
  only if it is an IAM principal of the function's own account. A Cognito identity-pool user, a role in another
  account and an unauthenticated caller are refused.
* **Write** (`runAutomation`): editors and admins only. An IAM caller is refused, whatever its policy.
* The function's role may read `listAutomations`, `getAutomation`, `getProcedureRun`, `getNewsroomProcedureDefinition` and
  `listProcedureRunsByProcedureAndRequestedAt` of the site's own API, `GetItem` and `Query` on the monitoring table,
  `PutItem` there for the Run now row (partition keys `MONITOR#*` only), and `lambda:InvokeFunction` on
  `papyrus-procedure-runner`. The router's role may read `listAutomations` of Distinctive's API
  (`RouterAutomationReadPolicy`) and needs `dynamodb:UpdateItem` on the table (below).

## Setting up the TTAB automation for Distinctive

Distinctive's record (`distinctive.ttab`) exists already. Releasing this change involves, in this order:

1. **Release Papyrus and deploy the site backend** (the pipeline does this on a merge to main). The backend gains the
   `usage` and `costUsd` fields on `ProcedureRun`, the `runAutomation` mutation and the wider function role.
2. **Set the limits you want** on the record before the router starts reading it. In particular
   `--max-concurrent` (see above): the default of 1 refuses all but the first of several decisions delivered together.
3. **Build and deploy the runner image** (`infra/procedures/build_image.sh`, then the `papyrus-procedure-runner`
   stack). It must come after step 1, or runs are recorded without their cost. It needs nothing else changed in the stack.
4. **Deploy the router** (`papyrus-monitoring`): a new router zip, and the changed template with
   `RouterAutomationReadPolicy` (one read field) and `dynamodb:UpdateItem` on the table for the router role. This step waits
   for the Distinctive session's OK. Until the router can read the record (the policy, or step 1), it behaves as before.
   Without `UpdateItem` the router could never move a row from `starting` to `started` (a latent gap, harmless: the
   runner moves the row on); with the grant it does, and counts of rows work the same either way.
5. Check with `papyrus automations show --id distinctive.ttab` and `papyrus automations runs --id distinctive.ttab`.
