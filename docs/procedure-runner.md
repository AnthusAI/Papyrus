# Procedure runner

The procedure runner executes a newsroom's published Tactus procedure in the cloud. It is one container
Lambda (`papyrus-procedure-runner`, arm64, 15 minutes, 3 GB) with Tactus and the Papyrus procedure tools
installed. It runs any procedure a newsroom has published, not only the seeded kinds that the newsroom's
own Lambdas handle (PPY-a2b94e). It is the consumer of each site's wake queue (below): the monitoring router
(when a monitor delivers a new Reference, PPY-9a79b5), Run now, the story-stage triggers and translate-on-publish
start it by putting a wake on the site's queue, and nothing invokes it directly.

## What a run does

The runner receives one queue message (below), whose request is:

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

Every request carries a **`wakeKey`**, and a request without a well-formed one is refused before anything is recorded.
The key says what the wake is about: `<owner>|<subject id>|<subject version>|<what>` for a change (a Story at a version
entering a stage; a Reference has no versions and says `unversioned`), `<owner>|schedule|<scheduled time>` for a timer,
`<owner>|manual|<request id>` for a person's request (Run now, or a command-line run). The owner is the automation's id, or
`procedure:<procedure key>` when no automation governs the start. The builders are in `src/papyrus_content/wake_keys.py`.

For each request, the runner does these steps:

1. It records a ProcedureRun in the newsroom through the external-execution path of
   `startNewsroomProcedureRun`, **before anything is loaded**. The record's id is derived from the wake key and it is
   created with a condition, with the status `started` and the key in `wakeKey`; the newsroom's parameter schema checks
   the input. A wake whose key already has a record comes back as a duplicate: the runner returns
   `runStatus: "duplicate"` with the first run's id, runs nothing, and touches neither the trigger row nor the story
   triggers (the first delivery did). A run that dies after this step leaves a `started` record with no outcome.
2. It loads the procedure's current version from the newsroom (`getNewsroomProcedureDefinition`). The
   version must be published and must be the version the record names. A procedure that cannot be loaded marks the
   record `failed` with the reason `not_runnable`, so it never stays `started` for a run that never began.
3. It downloads the version's `code` attachment (sort key `code`) and its skill files (further `code`
   attachments with sort key `skill:<path>`).
4. It writes the skills at their registered paths in a fresh working directory, so a procedure's
   `skills = {".claude/skills/..."}` resolves exactly as it does in the site repository.
5. It runs the procedure in a child process (`python -m papyrus_content.procedure_runner_child`) with
   every tool real. The child process has a deadline 60 seconds inside the Lambda's own, or the request's
   `timeoutSeconds` if that is shorter. The child reports the model usage of each call.
6. It updates the ProcedureRun to `completed` with the procedure's output, or to `failed` with the error,
   and stores the usage and an estimated cost (`docs/automations.md`). A run that overruns the deadline is recorded
   as `failed` ("timed out"), never left `running`.
   Every finished run also records its **outcome**, one of `acted`, `nothing`, `asked`, `failed`, `unknown`, with a short
   reason code (`outcomeReason`), plus the automation and the subject (story and version, or Reference) it was started for.
   `runStatus` is the mechanics; the outcome is what came of it. A procedure that looked and found nothing returns
   `run_outcome: "nothing"` with a `run_outcome_reason` code such as `no_new_filing` (a procedure must declare both fields in its
   `output`, because Tactus drops undeclared output keys; `procedures/newsroom/reference_curation.tac` does, and ends `nothing` with
   `already_curated` or `in_progress`); a procedure that returns neither did its work (`acted`). **`asked` is never a procedure's own
   word.** A procedure that needs a person's leave names the operations it wants in `gate_operations` and does none of them; the runner
   asks the one gate about each (`agent_gate/run_end.py`, on the policy it read for the run). If a person must do or approve one, the
   review-request code files one hard-gate review request on the run (`gate-<run id>`) and the run ends `asked` with the reason
   `human_required`, whatever word the procedure declared. If the operation is one no agent may do, the run ends `failed` with
   `gate_blocked`. Every answer, in order, with the policy version and the id of the request filed, is stored under `gate` in the
   run's `output` (kept on a run the gate stopped). A person's own run has no policy, so no gate is asked. A `nothing` or `asked`
   without a reason, or any other value, is recorded as `failed` with the reason `invalid_outcome`. A procedure error is
   `failed` with `procedure_error` (`timed_out` for a deadline). `unknown` is never set here: only settling an interrupted
   run sets it. Runs recorded before outcomes have none and are shown as "Recorded before outcomes"; they are not rewritten.
   `papyrus automations runs` and the console show each outcome as a word with a mark (✓ Did it, – Nothing to do, ? Asked,
   ✗ Failed, ! Outcome unknown). **Release order:** the site backend (which carries the new `ProcedureRun` fields,
   including `wakeKey`) goes out before the runner image and the CLI that write them.
7. **Before anything is loaded, the runner reads the site's agent policy** (PPY-c8175e; `agent_policy/run_gate.py`). It reads the
   automation named by the request's trigger and its `responsibility`, then the site's policy document (the live version only: the
   `SiteDocument` row, the live `SiteDocumentVersion` row, and the version's body from S3, all by key), and asks `decide_start`.
   The request names where the policy is with `tenantId` and `siteBucket`, which the router and Run now copy from the router
   publication (`tenantId`, `siteBucket`); a request without them is refused and starts nothing. Run now refuses a publication without them up front, and a wake without them that reaches the runner anyway has its run record made, failed with the reason `no_site_policy` and the automation's id, so the automation's run list shows it (not only the monitoring row).
   * No automation named, or an automation with no `responsibility` (not yet adopted with `papyrus automations adopt`): the run
     record is finished as `nothing` with the reason `not_adopted`.
   * The responsibility is `off` (including a responsibility the policy does not name, and a site with no policy document) or
     paused (the site or the agent): `nothing` with the reason `rung_off` or `paused`, and the words in `resultSummary`.
   * Either way nothing is loaded or run, no story is advanced, and the record names the `responsibility`, `policyVersion` and
     `rung` it was decided under. A run that starts records the same three fields on its finished record.
   * A policy that cannot be read (S3 or the API fails, or the body does not match its hash) fails the run with the reason
     `policy_unreadable`. There is no fallback that starts a run anyway.
   * A run a person starts in their own session (`papyrus stories localize`) uses `PersonStart`: a person's action is never limited by
     an agent's rung, and its record carries no responsibility or rung.
   * **An agent's run knows its own policy.** When the decision starts a run, the runner puts one entry in the child's environment, `PAPYRUS_AGENT_RUN`
     (`agent_gate/run_context.py`): the run id, the responsibility, the policy as read for this run and the moment the child is stopped. A procedure that must
     write through the gate while it works (the rating agent writes a rating only at a rung that allows it) builds its `GateRun` from that, so the gate it asks
     is the one gate over the one policy the run was decided under, and no rung is written into a procedure. A person's own run has no such entry, and a
     procedure that needs one refuses to run without it.
   The runner's role gains `s3:GetObject` on `tenants/*/site/agents/*` (the policy bodies). **Before enforcement reaches a site**, adopt
   its automations and write their policy lines: see [releasing](releasing.md#enforcing-the-agent-policy-on-a-site).
8. When the request came from a trigger, it names the run on the trigger's row in the monitoring table as soon
   as the run exists (status `running`, `runId`) and records the outcome (status, outcome, reason, error) there when it ends.

The runner signs its AppSync calls with its own role. The procedure tools in the child process do the
same (`PAPYRUS_GRAPHQL_AUTH=iam`). The OpenAI key comes from the publication's Amplify secret in SSM. For a run a change feed starts (the Item change feed, `change-feeds`), the wake names the parameter: the site's `agents.openAiKeyParameter`, put on the feeds as `PAPYRUS_OPENAI_KEY_PARAMETER` ([releasing](releasing.md#the-agents-model-key-the-parameter-a-site-names-ppy-8a374e-ppy-6af46b)). The runner's role may read only the parameters its template names (`AgentModelKeyParameters`); with none named the run has no key and fails closed.
The runner keeps no state of its own. A failure never starts a second run: the wake key's run record is created once,
and a second delivery of the same wake only finds it (`duplicate`).

## The wake queue

Every site has one FIFO queue, `papyrus-<site>-agent-wakes.fifo`, with a dead-letter queue, `papyrus-<site>-agent-wakes-dead-letters.fifo`, and an
alarm on it (PPY-567bf9; slice B1 of [the always-on agents design](design/always-on-agents-architecture.md)). The `<site>` is the site's brand
id, which is also its router publication id. They are in the site's `agents` stack (`amplify/agents/wake-queue.ts`), which a new site's first deploy
leaves out and its second deploy adds. The procedure runner is the queue's consumer: one message at a time (batch size 1), held for the whole run.

**A wake is one message**, `{"wake": {"key", "agent", "subject", "why"}, "request": {...}}` (`src/papyrus_content/agent_wakes.py`):

* `key` is the wake key. `agent` is its owner (the automation, or `procedure:<procedure key>`). `subject` is what it is about: the record, `schedule`, or the
  request id of a person's request. `why` is the trigger's own one-line summary.
* The **message group** is the agent plus its serial scope, which the wake's trigger carries from the agent definition's `serialBy`: `subject` (also the scope of a
  wake no definition governs) makes the subject the scope; `agent` makes one scope for the whole agent; `key:<name>` makes the scope the value in the trigger's
  `serialKey` (a channel account). Wakes of one group run one after the other, in order; wakes of different groups run at the same time. A `key:` wake with no
  `serialKey`, or a `serialBy` that is none of the three, is not a wake and is not sent. The wake records its `scope`. (The total concurrency from the model
  provider's limit, and the removal of `maxConcurrent` and the deferred sweep, are the rest of slice B4, PPY-a200ec; nothing is capped here.)
* The **deduplication id** is the wake key. SQS limits an id to 128 characters from a fixed set and a key may be 1000, so both ids are the SHA-256 of their text.
  SQS drops a repeat of the same id for five minutes. After that the run record's own condition drops it: the runner answers `duplicate` and runs nothing.

**What the runner does with a message.** It returns (the queue then deletes the message) only when the wake's run record exists: finished, refused
(`not_runnable`, `policy_unreadable`, `no_site_policy`), skipped by the policy, or the record of an earlier delivery of the same wake. If the message is not a well-formed wake, or no
record could be made (the site refused the start, or the runner died first), it raises, so the message stays and the queue delivers it again.

**Settling an interrupted run (slice A3, `run_settle.py`).** On the message's second delivery (`ApproximateReceiveCount` 2) the runner finds its wake's run record already there. A
record still `started` with no outcome is a run whose first attempt died. If the wake's trigger carries `safeToRepeat: true` (copied from the agent definition by the change feed), the runner runs it once more under the same key,
on attempt 2, and the run ends with its own outcome. If the trigger says `false` or says nothing, the runner records `failed` with the outcome `unknown` and the reason `interrupted`, which puts the run on the attention list that
Today reads, runs nothing, and returns so the queue deletes the message. A record that already has an outcome, or a first delivery, is the `duplicate` answer as before. If settling itself raises, the message stays and its
third receive goes to the dead-letter queue. A wake that does not come from the change feed (a timer) does not carry `safeToRepeat` yet, so an interrupted timer run is settled `unknown`, never repeated.

**Times that come from the runner, not from a guess.** The queue hides a received message for 960 seconds: the Lambda's 900 seconds (which hold the 60
seconds the runner keeps at the end to record the outcome) plus that margin once more, so a live run is never delivered to a second runner. A wake is
delivered at most twice (once to run, once to settle a run that died, slice A3); the third receive moves it to the dead-letter queue. Messages are kept 14 days.
`scripts/test-agents-stack.ts` fails if the queue's numbers differ from the runner template's `Timeout` and `SECONDS_KEPT_FOR_RECORDING`.

**The dead-letter queue is empty in normal operation.** Its alarm (`ApproximateNumberOfMessagesVisible` of 1 or more) reaches the operator through the account's alarm
listener. A message there is a wake nothing could run; the run record, if any, says why.

**Callers.** `agent_wakes.wake_sender()` is the one way to start a procedure. It finds the queue by the request's `publicationId`, and puts the wake on it. It
raises when the queue does not exist, and the caller records the start as failed (`startFailed`); nothing invokes the runner another way. The callers are the
monitoring router, `papyrus automations run` and the console's Run now, the story-stage triggers (in the console function, the CLI and the runner after a
stage run) and translate-on-publish.

**Who may do what (IAM).** A site's functions (Run now, translate-on-publish) may look up and send to their own site's queue only. The monitoring router and the
runner may look up and send to every site's wake queue by the name pattern `papyrus-*-agent-wakes.fifo`; the runner may also receive, delete and read the
attributes of those queues (never the dead-letter queues, whose names do not match). No one but the runner may receive or delete a wake, and nothing
holds `lambda:InvokeFunction` on the runner any more.

**Enabling it on a site.** A site has a queue once it is on a release that carries this and has had its second deploy. Wakes for a site without a queue fail to start
(`startFailed`, with the queue's name). Release order: the runner and monitoring stacks (role statements, consumer, router) go in one quiet window with the sites'
bumps, as in [releasing](releasing.md); the queue's duplicate drop is shown once on a real site before the queue is used there (PPY-817340 proves the run record's once-only create).

## The Item change feed

A DynamoDB stream on the Item table (switched on with the `agents` stack that reads it, never in a new site's first deploy) invokes the feed function
(`amplify/agents/item-change-feed.ts`, `amplify/functions/item-change-feed/handler.py`, `src/papyrus_content/item_change_feed.py`; slice B2, PPY-8a374e). For each
record it normalizes the change (a version created, a stage entered, a checklist step's new state), finds the agents that listen in the site's listener index
(one document, read by its live version; see [automations](automations.md#the-listener-index-and-the-item-change-feed)), and puts one wake on the site's queue for
each through `agent_wakes.send_wake`. The key is `<agent>|<lineage>|<version>|<what>`, so a stream record delivered twice makes the same keys and starts nothing
twice (the queue drops the repeat for five minutes, the run record's condition after that). Whoever wrote the change (the console board, the command line, an agent,
a person) the record is the same. An agent's own change never wakes that agent, a change nobody listens for sends nothing, and nothing lists a table. A record whose
wakes cannot all be sent is reported failed and Lambda retries from it. The Item table had no stream and no reader before; it holds one reader now, the feed.

## Proving the once-only create on a real site

The newsroom function (`amplify/functions/procedure-action/handler.ts`) answers a wake key that already has its run as
`duplicate: true`. It recognises the data API's refusal of the second create by its error type, the conditional-check failure
(`DynamoDB:ConditionalCheckFailedException`), or by its text, also when either is nested inside another error. Any other error is thrown, so
an answer it does not recognise is a failed start and never a second run. The scenarios in `features/wake-key-duplicate.feature` call the
handler with each shape of that error. They use an in-memory data client, so they cannot show what the real data API sends. A site that
runs the wake queue must have the real answer shown once: `papyrus procedures check-wake-guard`.

The check asks the site to start one wake key twice as the signed-in person. The wake key is `procedure:<procedure key>|manual|wake-guard-check-<time>`:
no automation, router or schedule ever builds a key like it. The start is the external-execution path, so **no procedure is loaded or run**.
The first start makes one `ProcedureRun` record; the second must answer `duplicate: true` with the same run id. The command then
finishes the record as `completed`, outcome `nothing`, reason `wake_guard_check`, so it does not sit `started`. It stays on the site as the
evidence: nothing deletes it, and it holds no text beyond the one-line summary.

Run it on one site that is on a release with wake keys (5.130 or later), as a signed-in admin, in this order. `<procedure key>` is any
published procedure with no required parameter; a procedure with one is refused at the parameter check and nothing is written.

```
papyrus --site <site> procedures check-wake-guard --procedure-key <procedure key> --dry-run
papyrus --site <site> procedures check-wake-guard --procedure-key <procedure key> --json
```

The first line writes nothing and prints the wake key it would use:

```
procedures	check-wake-guard	dry-run	procedure:<procedure key>|manual|wake-guard-check-<time>
```

The second prints, and exits 0 only when the second answer was a duplicate of the first run:

```
{"ok": true, "command": "procedures check-wake-guard", "status": "proved", "wakeKey": "procedure:<procedure key>|manual|wake-guard-check-<time>",
 "runId": "procedure-run-wake-<32 hex digits>",
 "answers": {"first": {"duplicate": false, "runId": "procedure-run-wake-<32 hex>", ...}, "second": {"duplicate": true, "runId": "procedure-run-wake-<32 hex>", "runStatus": "started", ...}}}
```

If the site answers anything else, the command exits non-zero with `Expected created, then duplicate of <run id>; got ...` and still finishes the first
record. Record the JSON on PPY-a5513c and PPY-567bf9. A second look at the site (`papyrus automations runs`, or the console's recent runs
for the procedure) shows exactly one record for that wake key, with the outcome `nothing` and the reason `wake_guard_check`. Run it again with a
new time in the key for another proof; never reuse a request id.

## Registering procedures: the deploy does it

Procedures live in Git, and a site's deploy registers them. The Amplify build of a site runs `papyrus procedures seed-required` right
after `papyrus-infra backend-deploy` (the generated production build spec, `infra/amplify-app-shell/lib/build-specs.ts`), as the build role on
the operator lane (`PAPYRUS_GRAPHQL_AUTH=iam`) with `PAPYRUS_ROOT` at the site's checkout. Nothing is seeded by hand and there is no
`npm run seed:amplify` step for a deployed site (that script still seeds a personal sandbox). The console only views and runs them.

What it registers:

- **Every core procedure**: all 15 kinds in `papyrus-required-procedures.json` (the registry; `procedures` maps each kind to its file in the
  wheel, `procedureMetadata` holds each kind's title, category, description, parameter schema and defaults, so there is one source). The CLI
  aliases in `requiredCliProcedures` are only a subset of the kinds.
- **The site's own procedures**, listed in `papyrus-site-procedures.json` at the site's root (a site without the file has none):

```json
{
  "version": 1,
  "procedures": {"distinctive.ttab.ruling-analysis": "procedures/ttab_ruling_analysis.tac"}
}
```

Each site file declares its kind on its first line (`-- papyrus-procedure-kind: distinctive.ttab.ruling-analysis`), as the core files do.
A site procedure is registered the way `papyrus procedures register` always did it: Tactus validates it, its `input` block becomes the
parameter schema and defaults, every skill directory its agents name (each with a `SKILL.md`) is stored beside it, and the version is
published. The definition's category is `site`.

The rules, each of which stops the deploy step with a plain error and writes nothing:

- A site kind cannot take a core kind's name. To replace a core procedure on purpose, the site lists the kind under `"overrides"`; its
  version then goes on the core definition and the core source is not written for that site.
- A kind with no file, a file that declares another kind or none, a core kind with no metadata, or an unknown default token is refused.
- A registry that is not valid JSON or is not `"version": 1` is refused.

Unchanged procedures write nothing. A version's id carries a digest of the source, the skill files and (for a core procedure) its metadata,
so the same Git state is never written twice; a change publishes a new version (version numbers count up) and archives the previous one.

The first deploy that carries this registers the 15 core procedures on every site, and it is not quiet: each procedure registered earlier by
the old seed (`procedure-version-<kind>-1`) gets a new digest version, because the kind header was added to ten of the files, and the kinds
that were never seeded (`story.localize`, `references.curate`, `story.editor-review`, `newsroom.copywriter`, `newsroom.editor`,
`newsroom.researcher`, `ingestion.reference.register`) are created. After that a deploy reports every kind unchanged until a file or its metadata
changes.

Before a deploy, and in CI, read-only checks:

```bash
papyrus procedures seed-required --dry-run --json   # reads the backend; says new, changed or unchanged for each procedure; writes nothing
papyrus procedures seed-required --check            # the same read, and exits non-zero naming every procedure that differs from Git
```

`--check` is the drift check: a published version that differs from the file in Git, or a procedure that was never registered, fails it.
`--root DIR` names the site's checkout (default: the current folder) and `--site-registry FILE` names another registry file.

The worked example is Distinctive Mark's TTAB ruling analysis (`distinctive.ttab.ruling-analysis`, the procedure
`distinctive.ttab` starts): `procedures/ttab_ruling_analysis.tac` and `.claude/skills/ttab-ruling-analysis/` in its repository, listed in its
`papyrus-site-procedures.json` as above. Moving Distinctive onto this contract (the file, the kind line, the next deploy) is that site's own
story. Until then, registering one procedure by hand is still possible and uses the same code:

```bash
papyrus procedures register --file procedures/ttab_ruling_analysis.tac --key distinctive.ttab.ruling-analysis
```

Use `--dry-run --json` there to see the schema and skill files without writing anything.

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
- **The role.** Besides the grants below, the runner's role receives from, deletes from and sends to the site wake queues by the name pattern, and it holds no `lambda:InvokeFunction`.
- **The grants.** The runner's role may call each site's API: the stack takes `DistinctiveApiId`, `AnthUsApiId`, `MachinesOnMachinesApiId`, `ThreatIntelApiId`, `DataParadeApiId`, `PilobolusApiId` and `ShippedApiId`, which the release reads from the `ApiId...` outputs of the `papyrus-monitoring` stack, so no API id is written in Git.
- **The router.** The router role may put wakes on the site queues (`RouterWakeQueuePolicy`). Register the site's procedure (above), and add `openaiKeyParameter` and `procedureTriggers` to its
  router publication in `infra/monitoring/router-config/hn.json` (a pull request; the release applies it: [router config in Git](monitoring-cloud.md#router-config-in-git)).

To run a procedure by hand, use `papyrus automations run` (or Run now in the console), which puts the wake on the site's queue. Nothing invokes the runner directly.

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
