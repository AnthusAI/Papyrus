# Procedure runner

The procedure runner executes a newsroom's published Tactus procedure in the cloud. It is one container
Lambda (`papyrus-procedure-runner`, arm64, 15 minutes, 3 GB) with Tactus and the Papyrus procedure tools
installed. It runs any procedure a newsroom has published, not only the seeded kinds that the newsroom's
own Lambdas handle (PPY-a2b94e). The monitoring router starts it when a monitor delivers a new Reference
(PPY-9a79b5).

## What a run does

The runner receives one request:

```json
{
  "publicationId": "distinctive",
  "appsyncEndpoint": "https://<api>.appsync-api.us-east-1.amazonaws.com/graphql",
  "openaiKeyParameter": "/amplify/shared/<appId>/OPENAI_API_KEY",
  "procedureKey": "distinctive.ttab.ruling-analysis",
  "input": {"proceeding": "97752244", "opinion_url": "https://.../EXA_26.pdf"},
  "actorLabel": "Papyrus monitor ttab",
  "trigger": {"kind": "monitor", "monitorId": "ttab", "sourceId": "97752244-EXA_26", "pk": "MONITOR#ttab", "sk": "TRIGGER#..."}
}
```

For each request, the runner does these steps:

1. It loads the procedure's current version from the newsroom (`getNewsroomProcedureDefinition`). The
   version must be published.
2. It downloads the version's `code` attachment and every `skill:<path>` attachment.
3. It records a ProcedureRun in the newsroom through the external-execution path of
   `startNewsroomProcedureRun`. The run is created as `running`, and the newsroom's parameter schema
   checks the input.
4. It writes the skills at their registered paths in a fresh working directory, so a procedure's
   `skills = {".claude/skills/..."}` resolves exactly as it does in the site repository.
5. It runs the procedure in a child process (`python -m papyrus_content.procedure_runner_child`) with
   every tool real. The child process has a deadline 60 seconds inside the Lambda's own.
6. It updates the ProcedureRun to `completed` with the procedure's output, or to `failed` with the error.
   A run that overruns the deadline is recorded as `failed` ("timed out"), never left `running`.
7. When the request came from a trigger, it records the outcome (run id, status, error) on the trigger's
   row in the monitoring table.

The runner signs its AppSync calls with its own role. The procedure tools in the child process do the
same (`PAPYRUS_GRAPHQL_AUTH=iam`). The OpenAI key comes from the publication's Amplify secret in SSM.
The runner keeps no state of its own. Asynchronous invocations are not retried
(`MaximumRetryAttempts: 0`), so a failure never starts a second run. Failed events go to the dead-letter
queue.

## Registering a site's procedure

A publication's own procedures live in its repository (for example `procedures/ttab_ruling_analysis.tac`
and `.claude/skills/ttab-ruling-analysis/`). From the site repository root, run:

```bash
papyrus procedures register --file procedures/ttab_ruling_analysis.tac --key distinctive.ttab.ruling-analysis
```

The command does four things:

- It validates the procedure with Tactus.
- It turns its `input` block into the version's parameter schema and defaults.
- It finds every skill directory the procedure's agents name. Each one must hold a `SKILL.md`.
- It stores the source and every skill file as attachments of a new published version, and archives the
  previous published version.

The version id is a digest of all those files, so registering unchanged files changes nothing. Use
`--dry-run --json` to see the schema and skill files without writing anything.

## Starting a procedure from a monitor

A router publication may list `procedureTriggers` (`CONFIG#router`; see `docs/monitoring-cloud.md`):

```json
{
  "publicationId": "distinctive",
  "appsyncEndpoint": "https://<api>.appsync-api.us-east-1.amazonaws.com/graphql",
  "openaiKeyParameter": "/amplify/shared/<appId>/OPENAI_API_KEY",
  "procedureTriggers": [
    {"procedureKey": "distinctive.ttab.ruling-analysis",
     "input": {"proceeding": "{sourceIdPrefix}", "opinion_url": "{canonicalUrl}"}}
  ]
}
```

Input values are templates over the delivered item. These placeholders are available:

| Placeholder | Value |
|---|---|
| `sourceId` | The item's source id |
| `sourceIdPrefix` | The part of the source id before the first `-`. For a TTAB decision, this is the proceeding number. |
| `canonicalUrl` | The item's canonical URL |
| `sourceItemUrl` | The item's source page URL |
| `title` | The item's title |
| `publishedAt` | When the source published the item |
| `referenceId` | The id of the delivered Reference |
| `publicationId` | The publication's id |
| `corpusId` | The publication's corpus id |

After a delivery succeeds, the router handles each trigger like this:

- **The Reference already existed** (it matched an earlier Reference by URL or alias): nothing starts,
  because the decision may already have coverage. The router writes a `TRIGGER#<publication>#<procedureKey>#<sourceId>`
  row with status `notTriggered`.
- **Otherwise**: the router writes that row with status `starting`, only if no row exists, and invokes the
  runner asynchronously. The row then moves to `started`, or to `startFailed` with the error. The runner
  later sets it to `completed`, `failed` or `notRunnable`.

The router never waits for a run, and a failed start never fails the delivery. Because the row is written
only once, a source item starts each procedure at most once, even when it is redelivered or redesignated.
The run receipt counts `proceduresStarted`, `procedureStartFailed` and `procedureNotTriggered`.

To run a procedure again for an item, delete its `TRIGGER#` row and invoke the runner with the request
stored on that row.

## Deploying

Both stacks are deployed by hand. Review a change set before you execute it.

1. Build and push the image: `infra/procedures/build_image.sh`. It prints the image URI by digest.
2. Create or update the `papyrus-procedure-runner` stack from `infra/procedures/papyrus-procedure-runner.yaml`.
   Pass `ImageUri` and `MonitoringTableName` (SSM `/papyrus/monitoring/table-name`).
3. Update `papyrus-monitoring` with `ProcedureRunnerFunctionName=papyrus-procedure-runner`. This gives the
   router `lambda:InvokeFunction` on the runner and sets `PROCEDURE_RUNNER_FUNCTION`.
4. Register the site's procedure (above), and add `openaiKeyParameter` and `procedureTriggers` to its
   router publication with `seed_router_config.py`.

To run a procedure by hand, invoke the runner with a request like the one above:
`aws lambda invoke --function-name papyrus-procedure-runner --invocation-type Event --payload file://request.json out.json`.

## Limits

- **Time.** A run gets about 14 minutes. A procedure that needs longer needs a different runtime (ECS),
  which is not built.
- **Access.** The runner's role may call every Query and Mutation of the newsroom APIs it is granted (only
  Distinctive's today), because a procedure's tools may call any of them. Grant a new publication by
  adding its API id to the template.
- **Records.** Logs go to CloudWatch (`/aws/lambda/papyrus-procedure-runner`). The ProcedureRun keeps the
  output, the error and its log tail. Token use and cost are not recorded yet.
- **Interactive runs.** A procedure that waits for a human is not supported. It fails.
