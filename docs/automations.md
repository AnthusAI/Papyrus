# Automations

An automation is a named record in a site's own backend that says "when this happens, run that procedure with
this input". It is the background-automation epic (PPY-9ff95b). The smallest useful version wraps what already
runs: Distinctive Mark's TTAB monitor starts its ruling-analysis procedure for each new decision. The record
describes that, links to it, controls it, costs it and shows what it did.

## What is live and what is not

| Part | Today |
|---|---|
| `monitor` triggers | Live, because the monitoring router already runs them. The router's `procedureTriggers` entry still says what starts and with what input; the record mirrors it and now governs it (below). |
| `event` trigger "story enters a stage" | **Live from the command line and the runner** (below, "Story-state triggers"). |
| `schedule`, `manual` triggers, other `event` kinds | Stored, and shown as "not yet supported". Nothing starts them. |
| `enabled` | **Real for monitor automations.** The router reads the record before each start. A disabled automation starts nothing, and the trigger row says `skipped` with the reason "automation disabled". |
| `limits.timeoutSeconds` | **Enforced.** It goes to the runner with the request and becomes the procedure's deadline, capped at 840 s (the runner Lambda's 15 minutes less its recording margin). |
| `limits.maxConcurrent` | **Optional; unset means no limit, as before.** When set, a new start at the limit is **deferred**, not dropped: the trigger row says `deferred` with the reason ("deferred: concurrency limit: 1 running, at most 1 at a time") and the router starts it on a later run when there is room. |
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

How a deferred item is retried:

* The row keeps the request the item was deferred with (the resolved input). At the start of every live router run,
  before it looks at new items, the router looks for `deferred` rows of each procedure trigger, oldest first. For each it
  asks the same question as a new start (is the automation still enabled, and is there room?). If there is room it starts
  the item and the row moves to `starting`, then `started` (with `retriedAt`), and the runner takes it from there. If the
  automation is full, the rest keep waiting. If the automation was disabled meanwhile the row becomes `skipped`. If the
  record has gone, the item starts as before. A retry that fails to start is recorded `startFailed`.
* Retries happen as often as the router runs (every 15 minutes), one per free slot per run at most.
* Setting the limit: `papyrus automations update --id distinctive.ttab --max-concurrent 4`. Clear it with
  `--max-concurrent none`. A record created before this change was given `maxConcurrent: 1` by the old default; if you
  did not mean a limit, clear it.
* Run now never writes a row when it is refused at the limit; it tells the person at once.

## Story-state triggers

A bot acts when a story moves between stages (PPY-f0914799). Human input is never a stage: wherever a person is wanted, the
engine raises a [review request](review-requests.md). The code is `src/papyrus_content/story_triggers.py`; the behaviour is
specified in `features_backend/story-state-triggers.feature`.

The example chain is `reporting` then `distinctive.ruling.fact-check`, then `copywriting`, then `distinctive.ruling.copy-edit`,
then `typesetting`, where no bot waits:

```bash
papyrus automations create --id distinctive.ruling.fact-check --title "Fact-check a ruling story" \
  --on-stage reporting --next-stage copywriting --monitor ttab --publication distinctive \
  --procedure distinctive.ruling.fact-check --input '{"tone":"plain"}' --max-hops 5
papyrus automations create --id distinctive.ruling.copy-edit --title "Copy-edit a ruling story" \
  --on-stage copywriting --next-stage typesetting --monitor ttab --publication distinctive \
  --procedure distinctive.ruling.copy-edit
```

The stored record is an `event` automation, `trigger.config` = `{"event": "story.stage_entered", "onStage", "nextStage",
"monitorId", "publicationId"}`; `limits.maxHops` is the hop limit. `monitorId` names the monitoring-table partition that holds
the run rows, and `publicationId` the router publication that supplies the site's endpoint and model key (the same two things a
monitor automation names). No schema change: the three fields are read back as `onStage`, `nextStage` and `maxHops`.

**Contract with the procedure.**

* Input: the record's static `inputTemplate` (no placeholders) merged under `{story, version, versionNumber, stage, runKey,
  automationId, hop}`, which win. `version` is the id of the version that entered the stage; `hop` counts the bot runs on this
  story so far, including this one.
* Output: `{"version": <new version id>}`, optionally `{"hold": true, "reason": "..."}`.
* The engine, not the procedure, moves the stage. After a run that completed with a new version and no hold, the runner moves the
  story to `nextStage` as `automation:<id>` (the trail note and the move), labels the new version `metadata.botAction`, and delivers
  the next stage's triggers, which is how the chain continues. With no `nextStage` the story stays. If the story was moved by
  someone else while the bot ran, it is not moved again.
* A bot that finds nothing to change returns the version it received (`{"version": <entering version>, "hold": false}`). That is
  success: the story advances, the trail says "no changes", no version is labelled. Extra output keys (corrections, unverifiable,
  remaining_findings) are not interpreted and are stored with the run record, which keeps the whole output.
* A failed or timed-out run, a hold, or a run that returns no version leaves the story where it is and raises a **flag** review
  request carrying the error or the reason.

**When it fires.** A story enters a stage by `papyrus stories move`, `stories save-version --stage/--advance`, `stories create`
(the story has entered its stage), or the engine's own move. These deliver the stage's triggers after the change, best effort: a
missing monitoring table or AWS credentials prints `not delivered` and never undoes the change. A move made on the console board
writes the Item directly and fires nothing yet; run `papyrus stories fire-triggers --story <lineage>` (safe to repeat).

**One run per story, stage and version.** The claim is a conditional put of `STAGE#<automation>#<story>#<stage>#<version>` in the
monitor's partition (`attribute_not_exists`); a second delivery finds it and starts nothing. The same row is the one the runner
updates with the run id and outcome. `enabled` and `maxConcurrent` apply as for any automation; a start at the limit is
reported `deferred` and starts when the triggers are delivered again.

**Hop limit.** `Item.metadata.botChain.hops` counts the bot runs started on the story; the default limit is 5, overridden by the
record's `maxHops`. At the limit nothing starts, the story stays where it is, and a **hard-gate** review request "bot hop limit
reached" is raised once. Raise `maxHops` on the automation to let the bots continue.

**Deployment needs.** `infra/procedures/papyrus-procedure-runner.yaml` now grants the runner's role what story-state triggers use:
`dynamodb:PutItem`, `GetItem` and `Query` on the monitoring table (leading keys `MONITOR#*`; the conditional put of the `STAGE#` claim,
the `startFailed` rewrite, the router-config read and the `STAGE#` prefix query; `UpdateItem` on the run rows was already there), and
`lambda:InvokeFunction` on `papyrus-procedure-runner` itself, to start the next stage. The existing `appsync:GraphQL` grant on every
Query and Mutation field of the Distinctive API already covers `listAutomations`, `getAutomation`, the Item fields, Messages and
review-request mutations; no other API is needed. What remains is the operator's: rebuild the image (`infra/procedures/build_image.sh`)
and update the `papyrus-procedure-runner` stack with the new `ImageUri` (see docs/procedure-runner.md, "Deploying").

**Not built yet:** the per-story budget cap from recorded cost (`botChain.costUsd` is reserved), a group lock, firing from the
console board, and a sweeper that retries `deferred` starts without a new delivery.

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
| `limits` | See above. Defaults: 840 s and no limit on how many at a time. |
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
  never happened `skipped` (the automation is disabled) and `deferred` (at its limit, waiting for room), each with its `reason`; and
* the `ProcedureRun` in the site backend, linked by the row's `runId`: its status, start and finish (so the
  duration), error, output, usage and cost. The story the procedure created is the output's `story` (a story lineage
  id), with `version_id` and `title`.

Details worth knowing:

* The runner writes `runId` onto the row as soon as the run exists (status `running`) and its outcome when it ends.
  A run that has only just been started shows as "Started" with no run record yet.
* Items that already had a Reference are never started (`notTriggered`). They are counted, not listed. A `skipped` or
  `deferred` start is listed, with its reason.
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
2. **Check `distinctive.ttab`'s limits** before the router starts reading the record. The record was created with
   `maxConcurrent: 1` (the slice 1 default). With this change that would run TTAB decisions one at a time, deferring the
   rest to later router runs. If that is not wanted, run `papyrus automations update --id distinctive.ttab --max-concurrent none`
   (today's behaviour: no limit).
3. **Build and deploy the runner image** (`infra/procedures/build_image.sh`, then the `papyrus-procedure-runner`
   stack). It must come after step 1, or runs are recorded without their cost. It needs nothing else changed in the stack.
4. **Deploy the router** (`papyrus-monitoring`): a new router zip, and the changed template with
   `RouterAutomationReadPolicy` (one read field) and `dynamodb:UpdateItem` on the table for the router role. This step waits
   for the Distinctive session's OK. Until the router can read the record (the policy, or step 1), it behaves as before.
   Without `UpdateItem` the router could never move a row from `starting` to `started` (a latent gap, harmless: the
   runner moves the row on); with the grant it does, and counts of rows work the same either way.
5. Check with `papyrus automations show --id distinctive.ttab` and `papyrus automations runs --id distinctive.ttab`.
