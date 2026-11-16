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
  "timeoutSeconds": 840,
  "trigger": {"kind": "monitor", "monitorId": "ttab", "sourceId": "97752244-EXA_26", "pk": "MONITOR#ttab", "sk": "TRIGGER#...",
              "automationId": "distinctive.ttab"}
}
```

`timeoutSeconds` and `trigger.automationId` are present only when an Automation record governs the start
(`docs/automations.md`); a run started by hand has `trigger.kind` `manual` and a `MANUAL#...` sort key.

For each request, the runner does these steps:

1. It loads the procedure's current version from the newsroom (`getNewsroomProcedureDefinition`). The
   version must be published.
2. It downloads the version's `code` attachment (sort key `code`) and its skill files (further `code`
   attachments with sort key `skill:<path>`).
3. It records a ProcedureRun in the newsroom through the external-execution path of
   `startNewsroomProcedureRun`. The run is created as `running`, and the newsroom's parameter schema
   checks the input.
4. It writes the skills at their registered paths in a fresh working directory, so a procedure's
   `skills = {".claude/skills/..."}` resolves exactly as it does in the site repository.
5. It runs the procedure in a child process (`python -m papyrus_content.procedure_runner_child`) with
   every tool real. The child process has a deadline 60 seconds inside the Lambda's own, or the request's
   `timeoutSeconds` if that is shorter. The child reports the model usage of each call.
6. It updates the ProcedureRun to `completed` with the procedure's output, or to `failed` with the error,
   and stores the usage and an estimated cost (`docs/automations.md`). A run that overruns the deadline is recorded
   as `failed` ("timed out"), never left `running`.
7. When the request came from a trigger, it names the run on the trigger's row in the monitoring table as soon
   as the run exists (status `running`, `runId`) and records the outcome (status, error) there when it ends.

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
     "input": {"proceeding": "{sourceIdPrefix}", "opinion_url": "{documentUrl}"}}
  ]
}
```

Input values are templates over the delivered item. These placeholders are available:

| Placeholder | Value |
|---|---|
| `sourceId` | The item's source id |
| `sourceIdPrefix` | The part of the source id before the first `-`. For a TTAB decision, this is the proceeding number. |
| `canonicalUrl` | The item's canonical URL (the identity used for matching, which may not download) |
| `documentUrl` | The address that downloads the document: the item's first alias, or its canonical URL when it has none. For a TTAB decision, this is the Reading Room PDF address in the form the site itself links. |
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

An automation record (`docs/automations.md`) mirrors a trigger like this one, shows its run history and governs it:
the router reads the record before each start (a disabled automation starts nothing, one at its limit refuses, its
timeout goes with the request), and falls back to starting as described here when there is no record or it cannot be read.

To run a procedure again for an item, delete its `TRIGGER#` row and invoke the runner with the request
stored on that row.

## Deploying

The release deploys the runner, like every shared stack: a merge to `main` builds the image and updates the stack (`.github/workflows/stack-deploy.yml`, `infra/pipeline/stacks.json`). Nothing is built, pushed or applied by hand.

- **The image.** `infra/procedures/build_image.py` builds the arm64 image from `infra/procedures/Dockerfile` and pushes it to the `papyrus-procedure-runner` repository. Its tag is `src-` plus a hash of
  everything the Dockerfile copies (`pyproject.toml`, `README.md`, `LICENSE`, `src/`, `corpora/`) and the Dockerfile, so a change to the code is a new image and an unchanged tree reuses the old one: the image cannot go stale. The stack receives the image by digest as `ImageUri`.
- **The repository** is the stack `papyrus-procedure-runner-repository`. The repository existed before the pipeline; the first release imports it, and the stack retains it.
- **The grants.** The runner's role may call each site's API: the stack takes `DistinctiveApiId`, `AnthUsApiId`, `MachinesOnMachinesApiId`, `ThreatIntelApiId`, `DataParadeApiId`, `PilobolusApiId` and `ShippedApiId`, which the release reads from the `ApiId...` outputs of the `papyrus-monitoring` stack, so no API id is written in Git.
- **The router.** `papyrus-monitoring` is given `ProcedureRunnerFunctionName=papyrus-procedure-runner`, which lets the router start the runner. Register the site's procedure (above), and add `openaiKeyParameter` and `procedureTriggers` to its
  router publication in `infra/monitoring/router-config/hn.json` (a pull request; the release applies it: [router config in Git](monitoring-cloud.md#router-config-in-git)).

To run a procedure by hand, invoke the runner with a request like the one above:
`aws lambda invoke --function-name papyrus-procedure-runner --invocation-type Event --payload file://request.json out.json`.

## Granting a newsroom to the runner

The runner may call a newsroom's API only if the role's `PublicationNewsrooms` statement names it. To grant a new site: add its `<Site>ApiId` parameter and its two resources (every Query field, every Mutation field) to
`infra/procedures/papyrus-procedure-runner.yaml`, add its `ApiId<Site>` output to `infra/monitoring/papyrus-monitoring.yaml`, and its `<Site>ApiId` parameter line to the runner entry in `infra/pipeline/stacks.json`. Merge; the release's change set modifies only the runner role.
No image rebuild is needed for a grant. The first run of a procedure on a newly granted newsroom shows in `papyrus automations runs`; an AppSync "not authorized" error on a run means the grant is not live.

## Limits

- **Time.** A run gets about 14 minutes. A procedure that needs longer needs a different runtime (ECS),
  which is not built.
- **Access.** The runner's role may call every Query and Mutation of the newsroom APIs it is granted, because a
  procedure's tools may call any of them. The stack grants every site's API (see Deploying); the template also
  names Anth.us (`AnthUsApiId`), which takes effect when the change set below is executed. Grant a new publication
  by adding its API id to the template.
- **Records.** Logs go to CloudWatch (`/aws/lambda/papyrus-procedure-runner`). The ProcedureRun keeps the
  output, the error and its log tail, and the run's model usage and estimated cost (`usage`, `costUsd`).
- **Interactive runs.** A procedure that waits for a human is not supported. It fails.

### Publication tenant context

Run now and the automatic localization dispatcher take `tenantId` from the configured router publication, never from procedure input. The runner validates this optional request field and applies it to both its own GraphQL client and the child process. A dedicated-site request without a tenant clears any previous worker tenant. Localization still rejects a tenant-prefixed source when the matching tenant context is absent, as well as actual translations and another tenant's group; it does not strip arbitrary prefixes.
