# Release 5.130: plan for review

Review document for the 5.130.0 engine release (Kanbus PPY-e713eb). It changes nothing live. Written 2026-11-17 from the repository at `develop` and from read-only
commands against Machines on Machines (MoM). Nothing here has been released, applied or switched on. Ryan's decisions on record: the release window, the MoM guideline
conversion (PPY-e37b6d), the IAM grants and adopting `rate` at `observe`. Not done and not decided here: the model key rotation (PPY-6af46b), any rung above `observe`, any budget figure.

Related: [releasing](releasing.md) (the first agent), [guidelines files cutover](guidelines-files-cutover.md), [the procedure runner](procedure-runner.md), [automations](automations.md).

## 1. The IAM statements

Marks: **[repo]** the statement is already written in a template in the repo and is applied by the release itself (no person's click). **[to write]** (none remain) nothing in the repo
defined it; the text below is what was or would be written. **[verify]** something I could not settle from the repo.

### 1.1 Runner role: receive and delete wakes, read policy bodies [repo]

- **Who:** the shared procedure runner's execution role, `papyrus-procedure-runner` stack.
- **Where:** `infra/procedures/papyrus-procedure-runner.yaml`, inline policy `papyrus-procedure-runner`, statements `ReadWakeQueues`, `SiteAgentPolicyBody` and `PutWakes`.
- **Why:** the runner is the one consumer of every site's wake queue (PPY-567bf9) and reads the agent policy body before each run (PPY-c8175e). `PutWakes` is the
  next-stage wake after a story-stage run. The dead-letter queues (`papyrus-<site>-agent-wakes-dead-letters.fifo`) do not match the pattern, so the runner cannot read them.

```yaml
- Sid: SiteAgentPolicyBody
  Effect: Allow
  Action: s3:GetObject
  Resource: !Sub "arn:${AWS::Partition}:s3:::*/tenants/*/site/agents/*"
- Sid: ReadWakeQueues
  Effect: Allow
  Action: [sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes]
  Resource: !Sub "arn:${AWS::Partition}:sqs:${AWS::Region}:${AWS::AccountId}:papyrus-*-agent-wakes.fifo"
- Sid: PutWakes
  Effect: Allow
  Action: [sqs:GetQueueUrl, sqs:SendMessage]
  Resource: !Sub "arn:${AWS::Partition}:sqs:${AWS::Region}:${AWS::AccountId}:papyrus-*-agent-wakes.fifo"
```

Applied by the release of the `papyrus-procedure-runner` stack (capability `CAPABILITY_IAM`; the pipeline role may already create roles for it), so **it takes effect when the hold on the runner is lifted, not when 5.130.0 is published** (section 2).

### 1.2 Router role: send only [repo]

- **Who:** the monitoring router's role (`RouterRole`), `papyrus-monitoring` stack.
- **Where:** `infra/monitoring/papyrus-monitoring.yaml`, managed policy `RouterWakeQueuePolicy`.
- **Why:** the router starts a publication's `procedureTriggers` by putting a wake on the site's queue; it no longer holds `lambda:InvokeFunction` on the runner. It cannot read or delete a message and cannot reach a dead-letter queue.

```yaml
- Sid: PutWakes
  Effect: Allow
  Action: [sqs:GetQueueUrl, sqs:SendMessage]
  Resource: !Sub "arn:${AWS::Partition}:sqs:${AWS::Region}:${AWS::AccountId}:papyrus-*-agent-wakes.fifo"
```

Applied by the release of the `papyrus-monitoring` stack (`CAPABILITY_NAMED_IAM`, not held today). **Hazard:** this stack is not held, so publishing 5.130.0 moves the router to the queue path
while the runner (held) does not yet consume the queue. See section 2, step 3.

### 1.3 Scheduler role and the site's own functions [repo, no person's grant]

- **Who:** `papyrus-<site>-agent-scheduler`, assumed only by `scheduler.amazonaws.com` for this account; and the site's own functions (Run now, translate-on-publish) for their own queue.
- **Where:** `amplify/agents/schedule-group.ts` (role, inline policy `SendWakes`) and `amplify/agents/wake-queue.ts`; both in the site's `agents` stack, which deploys with the site's backend.
- **Why:** a timer does nothing but put a wake on this site's queue.

```ts
new PolicyStatement({ effect: Effect.ALLOW, actions: ["sqs:SendMessage"], resources: [wakeQueueArn(brandId, partition, region, account)] })
```

### 1.4 Build role: scheduler, queue and monitoring reads, PassRole to the scheduler only [repo: already covered by AdministratorAccess, nothing written]

- **Who:** the Amplify build role that runs `papyrus agents schedules --site <brand>` in the site's production build (`infra/amplify-app-shell/lib/build-specs.ts`, `scheduleSync`).
- **Why:** it reconciles one EventBridge Scheduler entry per switched-on agent that names a schedule, and reads the router publication through the monitoring table. It never creates a group or role.
- **Where, as built (2026-11-17):** no statement was written. The production build of every app-shell site with a `cms` section runs as that app's `AmplifyServiceRole`
  (`iamServiceRole: cmsServiceRole.roleArn` on the `App`, `infra/amplify-app-shell/lib/amplify-app-shell.ts`), and that role carries the managed `AdministratorAccess`
  policy (documented risk). `infra/amplify-app-shell/examples/machines-on-machines.site.json` is a `cms` site, its production spec runs `papyrus agents schedules`
  as that role (`build-specs.ts`, `scheduleSync`), and the only deny on the role is the shared tier's (`shared-stack-deny.ts`, `papyrus-shared-*` resources), which
  the site's own queue, schedule group and scheduler role (`papyrus-machines-on-machines-*`) are not. So `sqs:GetQueueUrl`, the scheduler actions, `iam:PassRole` to the scheduler
  role and the monitoring-table read are all allowed already. The statements below are the least the step needs, kept as the reference if the role is ever narrowed; a
  narrower role is the point at which they become a template change.
  **[verify on deploy]** I ran no AWS command: that MoM's live app uses this role (that it was created from this template, not by hand) is read from the template and the example
  config, not from the account. `papyrus agents schedules --dry-run` run by the build role is the check, and it needs no change to any role.

```json
[
  {"Sid": "WakeQueueAddress", "Effect": "Allow", "Action": "sqs:GetQueueUrl",
   "Resource": "arn:aws:sqs:<region>:<account>:papyrus-<site>-agent-wakes.fifo"},
  {"Sid": "ListSchedules", "Effect": "Allow", "Action": "scheduler:ListSchedules", "Resource": "*"},
  {"Sid": "SiteScheduleGroupEntries", "Effect": "Allow",
   "Action": ["scheduler:GetSchedule", "scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule"],
   "Resource": "arn:aws:scheduler:<region>:<account>:schedule/papyrus-<site>-agent-schedules/*"},
  {"Sid": "PassTheSchedulerRoleToTheSchedulerOnly", "Effect": "Allow", "Action": "iam:PassRole",
   "Resource": "arn:aws:iam::<account>:role/papyrus-<site>-agent-scheduler",
   "Condition": {"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}}},
  {"Sid": "MonitoringTableRead", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Query"],
   "Resource": "arn:aws:dynamodb:<region>:<account>:table/<monitoring table>",
   "Condition": {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["MONITOR#*"]}}},
  {"Sid": "RouterPublicationParameter", "Effect": "Allow", "Action": "ssm:GetParameter",
   "Resource": "arn:aws:ssm:<region>:<account>:parameter/<the router config parameter>"}
]
```

The last two names (the table's name, the parameter's name) are what `papyrus automations run` reads today; I did not look them up and the final text must copy them from that code path.
The group-level `scheduler:*` on the pipeline role (`infra/pipeline/papyrus-stack-pipeline.yaml`, `schedule/default/papyrus-*`) is for stack deploys and is not this.

### 1.5 Signed-in admin: write the policy body [repo: written, not a storage rule]

- **Who:** the signed-in admin's Cognito group role (identity pool), used by `papyrus agents set-rung --apply` (`src/papyrus_content/agent_policy/store.py` through `story_images.user_lane_s3_client`).
- **Why:** `--apply` puts `tenants/<tenant>/site/agents/<version>.json` in the site's media bucket (`site_store.py`). Until the grant exists the call stops with S3 `AccessDenied` and writes nothing.
- **Can `defineStorage` say it?** No. `amplify/storage/resource.ts` grants admins `media/*`, `newsroom/*`, `corpora/*` (read) and `preview/*` (read); a rule takes a prefix ending in `/*`, and
  `tenants/*/site/agents/*` has a wildcard in the middle. The repo's mechanism for a grant a storage rule cannot express is an IAM statement in `amplify/site-backend.ts`
  (the Lambda grants beside `grantMediaReadWriteDelete`). Those go on Lambda roles in the function's own stack; for a group role the same mechanism would put a bucket ARN
  on a role in the auth stack, and the storage stack already depends on that stack (its rules attach to the group roles), so the two would depend on each other.
- **As built:** `amplify/agents/admin-policy-grant.ts` adds one `AWS::IAM::Policy` to the `admin` group's role (`backend.auth.resources.groups.admin.role`), in its own stack
  `admin-agent-policy-grant` created in `site-backend.ts` for a dedicated site (not a shared stack: the prefix names every tenant). Get and put only, no delete, no list; the editor and curator groups and
  the authenticated role get nothing. `scripts/test-admin-agent-policy-grant.ts` locks the exact statement and that only the admin role carries it
  (`amplify/agents/admin-policy-grant.feature`):

```json
{"Sid": "AdminWriteAgentPolicyBody", "Effect": "Allow",
 "Action": ["s3:GetObject", "s3:PutObject"],
 "Resource": "arn:aws:s3:::<media bucket>/tenants/*/site/agents/*"}
```

`s3:GetObject` is there because `--dry-run` and `--apply` read the live version as the admin through the same store; the runner's read is 1.1. It deploys with the site's bump, so
it must be in the release that precedes the first `set-rung --apply`. **[verify on deploy]** that the identity pool hands a signed-in admin the group's role (Cognito
`cognito:preferred_role`) rather than the authenticated role: `set-rung --apply` by an admin on a bumped site is the check, and `AccessDenied` there means the role mapping, not this statement.

### 1.6 What needs a person's click

The pipeline-roles stack (`role-stack-deploy`, environment `pipeline-roles`) needs approval only if a statement above is outside what the pipeline roles may deploy. From my reading, 1.1 and 1.2 use IAM actions the roles already have
(role and inline-policy writes on `papyrus-*`); the track report found no role-stack run waiting on 2026-11-16. Check the `plan` job of the first run after the PR merges. 1.4 needs no grant (the build role is `AdministratorAccess`) and 1.5 deploys with the site's bump as a stack in the site's backend, so neither is a person's apply in the pipeline-roles stack; a person reviews the IAM view of the `admin-agent-policy-grant` stack in the bump's change set.

## 2. Release order and the wake-key hazards

The rule: **a site's backend and the shared runner switch together.** A 5.129 backend works only with today's runner; a 5.130 backend works only with the new one (the new runner sends a wake key and outcome fields that only
5.130 accepts; 5.130 refuses a run with no wake key). Everything fails closed: a refused start, never a double run. The runner serves Distinctive, Anth.us, MoM, Threat Intelligence, Data Parade, Pilobolus and Shipped.

Hazards and where they stand (board and code, read today):

| Hazard | State |
|---|---|
| Deferred monitor items have no wake key and would be lost | Fixed: PPY-7ab263, PR #1640, with a scenario. `retry_deferred` rebuilds the key from the row. |
| The once-only create matched error text only | Code merged: PPY-a5513c, PR #1639. **Not proven on a real backend yet**: checklist step 11 is the proof, on MoM after its bump. |
| Router moves to the queue before the runner consumes it | Open. `papyrus-monitoring` is not held, so publishing moves the router. See step 3. |
| Guidelines read `legacy_version` between a site's bump and its `convert --apply` | Known. Keep it short, no one saves guidelines. |
| Anything refused during the switch is marked, not queued | Re-run it after (step 10). |
| The runner role statements (1.1) only arrive when the runner stack does | By design; it is held. |

Ordering:

1. **Distinctive (5.73.0) to 5.129.0** by stepped bumps, one ruling analysis confirmed after. Not a MoM matter; it only has to be done before the hold is lifted.
2. **Hold the runner.** Add `"hold": "<reason>"` to `papyrus-procedure-runner` in `infra/pipeline/stacks.json` in a reviewed PR. I read `infra/pipeline/stack_deploy.py`: `selected()` leaves a held stack out of `scope`, `changed` and `deploy` for **any** stack, not only the shared tier, and the pull-request dry run prints HELD.
   This settles the track report's open question [code read, not run]. The `papyrus-procedure-runner-repository` stack is separate and not affected.
3. **Decide the router.** `papyrus-monitoring` (router, 1.2) is not held. Either hold it too, in the same PR, and lift both together, or confirm the router's queue path is inert until a publication names a `procedureTriggers` wake; I could not confirm that from the repo. Recommended: hold both. (Question for Ryan, section 5.)
4. **Publish 5.130.0** (`develop` to `main`, normal release). Runner unchanged. Check `git tag --contains` for each PR.
5. **Prepare, no effect.** For MoM: the bump PR ready on its `develop`; read the `deferred`, `starting` and `startFailed` trigger row counts and write them down; the conversion dry run (section 3) ready.
6. **The window** (quiet: no MoM publish, nobody saves guidelines). **MoM only.** Merge the MoM bump and the engine PR that lifts the hold (runner, and the router if held) together. Until both have finished, MoM runs are refused, never doubled. Other sites' runs
   are refused too while the runner is the new one and their backends are old, so **this is the cost of one shared runner**: every other site that runs procedures must already be on 5.129.0 and be bumped in the same window, or accept refused runs until its own bump. Sites with no procedures or automations are unaffected.
7. **MoM:** `papyrus guidelines convert --apply` as the signed-in admin; `resolve` for the publication, one section and one language; `export`; `convert` again shows `already_files`.
8. **MoM:** one real run ends with an outcome word (a translation); re-read the trigger row counts and re-run anything refused with `papyrus automations run`.
9. **Once-only check** on MoM: start the same wake key twice; one run record, the second answer `duplicate`. Record it on PPY-a5513c and PPY-567bf9.
10. **Then, with the 1.4 and 1.5 grants in place:** the first-agent steps in [releasing](releasing.md#the-first-agent-rating-on-machines-on-machines-ppy-d85860) (head index check, `adopt` dry run then real, `set-rung --rung observe --reason`, schedule link). The model key is **not** rotated, so the run will fail closed with "The run has no model key". That is a correct stop, not a failure of the release; it means no first run until the key is replaced.
11. **Other sites** (Shipped, Pilobolus, Threat Intelligence, Data Parade; Anth.us only on explicit instruction): bump and convert, one per window, before their next procedure run. They are on 5.106.0 or older, so each needs stepped bumps first.
12. Caducus: release the version with PR #21 and bump its Papyrus pin before any work sends on the new records (PPY-ab48d4).
13. Nothing in this release turns an agent on except the one `observe` entry Ryan approved. The `rate` automation arrives **disabled** after the bump's `agents apply`.

MoM bumps first and alone. Nothing here bumps The Hallucinator.

## 3. MoM guideline conversion: dry run

Run today, read-only, with the 5.130-candidate CLI from this worktree (`PYTHONPATH=src python -m papyrus.cli --site newsroom.machines-on-machines.anth.us guidelines convert`, signed in as Ryan, no `--apply`). The installed `papyrus` is 5.126.0 and has no `convert`,
so the repo's own CLI was needed. The command works against the live site (it is not fixtures only), reports `"applied": false` and writes nothing; MoM is still on 5.126-era data, so the old engine is the one serving it.

| Lineage | Current version | Files it becomes | `resolvedUnchanged` | State |
|---|---|---|---|---|
| Publication (writing) | 3 | 4 | true | ready |
| es-419 overlay | 2 | 2 | true | ready |
| zh-Hans overlay | 1 | 1 | true | ready |

Summary: 3 ready, 0 refused, 0 converted, 0 already files. No section lineage was listed, so MoM has no section-specific writing guidelines (the command lists every lineage; I did not separately run `guidelines history`).
Needed to apply: the bump to 5.130 (new upload role `doctrine_files`, file-reading functions) deployed first, then `convert --apply` as an admin who is a person. Nothing else is needed; no lineage is refused.
The dry run made 64 read requests (budget 200).

## 4. Imported-translation label strings: not done

The coordinator withdrew this step. Ryan's standard is the byline ("By various bots" / "By various bots and [author]"), produced by the byline hook and the front matter `drafting: {by: AI}` and `author`. The separate "Written by {author}" notice from PR #1655
duplicates it and is being reworked in a follow-up. No `translation.importedLabel` strings were added to MoM or The Hallucinator, and no other repo was touched.

## 5. Live-check list

Before the window:
- `papyrus --site machines-on-machines guidelines history --kind writing` recorded (current versions 3, 2, 1 as above).
- Trigger row counts (`deferred`, `starting`, `startFailed`) for the monitor `hn`, written on PPY-e713eb.
- `papyrus --site machines-on-machines stories head-index` reports no keys to set or remove (dry run).
- `develop` `tests` run green on the exact commit to release (finished, not cancelled). On 2026-11-17 the `tests` and `Release` runs on `cefd3ba67` (merge of PR #1655) are green; the head `b1c7c7932` after it is a board-only commit.
- The pull-request dry run of the hold PR prints HELD for the held stack(s).
- Live build role read (1.4) and Cognito admin group role read (1.5), so the missing grants are known.
- The router config names MoM's `tenantId` and `siteBucket` (`infra/monitoring/router-config/hn.json`); the release applies it.

During and after:
- MoM bump build finished, including `procedures seed-required`, `agents apply` (a core definition naming an unregistered procedure fails every build; `rate_items` is registered, see below) and `agents schedules`.
- Automation `rate` exists, **disabled**, with its registered copy; no policy document exists yet.
- `convert --apply`; `resolve`; `export`; `convert` shows `already_files` for all three lineages.
- A real translation ends with an outcome word; once-only check (duplicate) recorded.
- Wake queue `papyrus-machines-on-machines-agent-wakes.fifo` exists with its dead-letter queue empty; the dropped-tick alarm is quiet.
- Then the first-agent commands, in the order in [releasing](releasing.md): `adopt --dry-run`, `adopt`, `set-rung --reason` dry run, `--apply`, `update --monitor hn --publication machines-on-machines --enabled true`, `agents schedules --dry-run`, `agents schedules`, `automations run`, `automations runs`.

## 6. Checks run for this plan

- `papyrus agents validate --dir src/papyrus_content/agent_definitions/core --core src/papyrus_content/agent_definitions/core` returns `ok: true` with one definition, `rate` (responsibility `rate`; operations `guidelines_resolve` at observe, `ratings_set` at draft). `rate_items` is in `src/papyrus_content/data/corpora/papyrus-required-procedures.json` and `data/procedures/rate_items.tac`, so a core definition naming it does not break builds.
- Develop CI: green on the last code commit (above).

## 7. Open questions for Ryan

1. Hold `papyrus-monitoring` too, so the router does not start sending to a queue nobody consumes? Recommended yes.
2. Answered from the templates: the app-shell `cms` build role is `AdministratorAccess`, so 1.4 writes nothing. Not read from the live account; the first `agents schedules --dry-run` on the build confirms it.
3. Built as described in 1.5 (get and put on the one prefix, admin group only, dedicated sites only). Not available to a shared stack: say if it should be.
4. One shared runner means every site that runs procedures must be on 5.129 before the window and is refused until its own bump. Which sites bump in the same window, or is a short refusal window acceptable on the others?
5. The model key is not rotated. The first run will fail closed. Do you want the release and `observe` set anyway so the wiring is proven, accepting a failed first run?
