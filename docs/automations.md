# Automations

An automation is a named record in a site's own backend that says "when this happens, run that procedure with
this input". It is step one of the background-automation epic (PPY-9ff95b). The smallest useful version wraps
what already runs: Distinctive Mark's TTAB monitor starts its ruling-analysis procedure for each new decision.
The record describes that, links to it and shows what it did. **It starts nothing.**

## What is live and what is not

| Part | Today |
|---|---|
| `monitor` triggers | Live, because the monitoring router already runs them. The record mirrors the router's `procedureTriggers` entry. |
| `schedule`, `event`, `manual` triggers | Stored, and shown as "not yet supported". Nothing starts them. |
| `enabled` | **Display only until the router honours it.** Changing it changes the record and nothing else. To stop a trigger today, remove it from the router config (`seed_router_config.py`). |
| `limits` (`timeoutSeconds`, `maxConcurrent`, `budgetUsdPerRun`) | Recorded only. The runner does not enforce them, and `budgetUsdPerRun` is advisory. |
| Cost per run | Unknown. A `ProcedureRun` holds no token use or cost today. It would come from the procedure runner: `procedure_runner_child` would report model usage with its result, and `run_procedure_request` would store it on the `ProcedureRun`. |

The router (`monitoring_router.py`), the monitoring stack, the procedure runner and the registered procedure are
unchanged. The router's `CONFIG#router` entry stays the source of truth; the record is a mirror.

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

* the `TRIGGER#<publication>#<procedureKey>#<sourceId>` row in the monitoring table (`MONITOR#<monitorId>`): which
  item, when it started, and how the start ended (`started`, `startFailed`, `completed`, `failed`, `notRunnable`); and
* the `ProcedureRun` in the site backend, linked by the row's `runId`: its status, start and finish (so the
  duration), error, and output. The story the procedure created is the output's `story` (a story lineage id),
  with `version_id` and `title`.

Details worth knowing:

* The runner writes `runId` onto the trigger row only when a run finishes. A run in progress shows as
  "started" with no run record yet.
* Items that already had a Reference are never started (`notTriggered`). They are counted, not listed.
* A row whose run record cannot be found, or read, says so on that row; the rest of the history still reads.
* A site's console reads only its own publication's rows: the router must list the automation's publication
  with this site's endpoint. The runner's stored request (endpoints, key parameter) is never returned.

## Command line

```bash
papyrus automations list
papyrus automations show --id distinctive.ttab
papyrus automations runs --id distinctive.ttab [--limit 20] [--json]
papyrus automations create --id distinctive.ttab --title "Analyze new TTAB rulings" \
  --monitor ttab --publication distinctive --procedure distinctive.ttab.ruling-analysis \
  --input '{"proceeding":"{sourceIdPrefix}","opinion_url":"{documentUrl}"}' [--dry-run]
papyrus automations update --id distinctive.ttab [--enabled false] [--title T] [--input JSON] \
  [--timeout-seconds N] [--max-concurrent N] [--budget-usd N] [--dry-run]
```

`create` and `update` use the normal sign-in lane (`papyrus login`, editor or admin); operators can read with
`PAPYRUS_GRAPHQL_AUTH=iam`. `runs` (and the run column of `show`) also needs AWS credentials that can read the
monitoring table, found through the SSM parameter `/papyrus/monitoring/table-name`. Without them the records
still list.

## Console

Administration, Automation, beside Procedures. It lists each automation (title, trigger, procedure, enabled,
last run status). Choosing one shows its settings, the router link and its recent runs (started, duration, status,
error, run id, the story with a link, cost). Status is always words with a mark, never colour alone. It is read
only: an operator changes automations with the command line. The page reads through one query,
`automationOverview`, served by the `papyrus-automation-view` function, whose role may read two fields of the
site's own API and `GetItem` and `Query` on the monitoring table.

## Setting up the TTAB automation for Distinctive

1. Deploy a Papyrus release that includes this change to the site's backend (the `Automation` model and
   the `papyrus-automation-view` function are new). Nothing else about the monitor, router or runner changes.
2. Create the record with the `create` command above. Its `input` must equal the router's `procedureTriggers`
   input for `distinctive.ttab.ruling-analysis`; `show` reports whether it does.
3. Open Administration, Automation, or run `papyrus automations runs --id distinctive.ttab`.
