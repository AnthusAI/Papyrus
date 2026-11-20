# Distinctive Mark: staged bump from Papyrus 5.73.0 to 5.130.2

Plan for review. Written 2026-11-17 from `origin/develop` of Papyrus, the Distinctive-web repository at `origin/main` and `origin/develop`, and read-only commands against the live
account (DynamoDB `describe-table`, Amplify `get-app` and `list-jobs`, CloudFormation `describe-stacks`, SSM `describe-parameters`, EventBridge Scheduler, one sign-in-free `curl`).
**Nothing was bumped, merged, deployed or written.** Every number below says whether it was read or derived.

Related: [releasing](releasing.md) (the one-index rule, the release budget), [release 5.130 plan](release-5-130-plan.md), [procedure runner](procedure-runner.md),
[site hosting](site-hosting.md) (build timeout, two-deploy bootstrap), [multi-tenancy](multi-tenancy.md), [monitoring in the cloud](monitoring-cloud.md).
The plan is filed on Distinctive's Kanbus board (project key `dist`) as an epic with ordered child tasks; the board text is the working copy.

## Why now

The shared procedure runner is already on 5.130. It refuses a start that carries no wake key. The monitoring router still invokes it directly, so the next new TTAB decision
(the collection pass runs once a day at 02:58 UTC, the router at minute 41 of every hour) starts `distinctive.ttab.ruling-analysis` with no key and is refused. The
`papyrus-monitoring` stack is held (`infra/pipeline/stacks.json`, PPY-e713eb: "Taking this line out is the go"). Lifting it moves the router onto per-site wake queues for
every site, and a site has a queue only once its backend is on 5.130 (the site's `agents` stack). Distinctive is therefore the first thing the hold waits for.

## 1. What was read: where Distinctive stands

| Fact | Value | How known |
|---|---|---|
| Pins | `@anthusai/papyrus` 5.73.0 in `package.json` and `infra/package.json`; `papyrusVersion` 5.73.0 in `infra/site.json`; `papyrus-newsroom[markus]==5.73.0` in `requirements-publication.txt` | repo |
| Branches | `develop` (review) and `main` (a push to `main` runs CI, then `amplify-deploy.yml@main` starts the Amplify job); `develop` builds nothing | repo, `.github/workflows/deploy.yml` |
| Tables | 50 tables, 172 global secondary indexes, all `ACTIVE` | live `describe-table` |
| Plugins | `newsletter` only; no reader-steering, no signup | `papyrus.config.ts` |
| Amplify app build spec | the plain `npx ampx pipeline-deploy` spec; the repository's `amplify.yml` is the same plus a `cp amplify_outputs.json` line and overrides it | live `get-app`, repo |
| **Build timeout** | **the app has no `_BUILD_TIMEOUT`, so Amplify's default of 30 minutes applies** | live `get-app` (`environmentVariables` is empty) |
| App-shell stack | last updated 2026-10-22; holds an Amplify app, branch and roles only | live `describe-stacks`, `get-template` |
| `infra/site.json` | **does not validate against current Papyrus**: `email` has been required for cloud sites since 5.34.0 (`infra/amplify-app-shell/lib/cloud-email-config.ts`). `papyrus-infra synth` fails on it at 5.130.2 and the same code is in 5.73.0 | derived: parsed with the 5.130.2 `parseSiteConfig` |
| Branch variables | no `PAPYRUS_TENANT_ID`, no `PAPYRUS_SITE_ID` (Machines on Machines has both) | live `get-branch` |
| Router publication | `MONITOR#ttab` / `CONFIG#router` in the monitoring table: `decisions direct`, `mode live`, `maxItemsPerRun 25`, `feedback false`, one publication `distinctive` with `procedureTriggers` for `distinctive.ttab.ruling-analysis` and an `openaiKeyParameter`. **It has no `tenantId` and no `siteBucket`, and no file in Git** (`infra/monitoring/router-config/` holds only `hn.json`; "Today only `hn` has a file") | live `get-item` |
| Other router entries | of the 14 router configs in the table only `ttab` has `procedureTriggers`. `web-distinctive` has a `distinctive` publication with no key, no trigger, no bucket and no tenant | live scan |
| Automations (3) | `distinctive.ttab` (monitor `ttab`), `distinctive.ruling.fact-check` (`story.stage_entered`, reporting to copywriting), `distinctive.ruling.copy-edit` (copywriting to typesetting); all enabled; none adopted | live scan of the `Automation` table |
| Procedures (3) | `distinctive.ttab.ruling-analysis`, `distinctive.ruling.fact-check`, `distinctive.ruling.copy-edit`, registered once by hand (`procedure-distinctive-...`) | live scan; repo `procedures/*.tac` have no kind header line, and the repo has no `papyrus-site-procedures.json` |
| Triggers | 14 `TRIGGER#` rows for the ruling analysis, all `completed`, none `deferred` | live query |
| Public site | `sitemap.xml` lists 42 URLs on 2026-11-17; `/newsroom` answers 200 | `curl` |
| Model key | SSM `SecureString` for the app exists, last modified 2026-11-01. **Not read, not tested.** | `describe-parameters` |
| Schedules | `papyrus-monitoring-ttab-collect` `rate(6 hours)` (the monitor itself is due once a day: last finish 02:58:15 UTC); `papyrus-monitoring-ttab-route` `cron(41 * * * ? *)`; `web-distinctive-route` `cron(57 * * * ? *)`; `web-distinctive-monitor-stories` `cron(30 7 * * ? *)` | live `get-schedule`, monitoring table |
| `reprojectOnDeploy` | `true`: every deploy re-renders the whole public site with the new engine | `papyrus.config.ts` |
| Dependencies | the dependency block of Distinctive's `package.json` equals Machines on Machines' at 5.130.0 apart from the pin, so no dependency change is expected | repo comparison |

The live index counts equal the 5.73.0 ledger on 47 tables. Three tables have more live: `EditionItem` and `ItemTag` two more each, `MediaAsset` one more. Those are the indexes Amplify creates itself for
`belongsTo` and `hasMany` fields (the models have 2, 2 and 1 such fields); the ledger reads only `index()` calls and cannot see them. Counting those fields in every schema source at 5.73.0 and 5.130.2 finds **no change in any model**, so the range adds no
relationship index the ledger misses. Every table has room (largest: `Message` with 12 of 20).

## 2. The stages (item 1)

### How they were derived

`scripts/check-gsi-ledger.ts` compares the last stable tag with the working tree. It cannot compare two arbitrary tags, so the ledger was built the way the script builds it:
`git ls-tree -r --name-only <tag> -- amplify`, keep the paths matching `SCHEMA_SOURCE` from `scripts/lib/gsi-ledger.ts`, `parseLedgers` over `git show <tag>:<path>`, and
`compareLedgers(base, current, releaseBudget(measurements, buildTimeout))` with the real `scripts/data/gsi-deploy-measurements.json`. A stage passes only when the ledger reports no
failure **and** no table gains and loses indexes in the same stage (DynamoDB changes one index per table in one update, creation or deletion; the shipped script only warns about a
drop, so the extra check was added). From each stable tag the walk took the furthest stable tag that still passes; the last stage was then split in two on purpose (below).

Findings that hold for the whole range:

- A direct jump 5.73.0 to 5.130.2 fails: `Reference` gains 3 indexes and `Item` gains 4. The script's own release order for the jump needs 4 releases; real stable tags need 6 index stages.
- No index changes keys in place and none is dropped between the two versions.
- The earlier draft on Distinctive's board (the 2026-11-07 epic, `dist-0c135b9b`) stopped at 5.92.0 and is superseded: it predates the head stage index (5.103.0), the schedule index (5.108.0), multilingual (5.110.0) and the tenant indexes (5.111.0).
- Anth.us took the same first two stage points (5.70.0 to 5.85.2, then 5.86.0, on 2026-11-04) and Machines on Machines took 5.107.2, 5.108.0, 5.109.0 and 5.111.0, so those points are known to deploy.

### The stages

Index creations are counted on tables Distinctive has (or gets in an earlier stage); the script's own count includes the reader-steering and signup tables a site without those plugins
does not have. Minutes are the script's upper estimate, 141 s per creation (measured on Machines on Machines job 107), not a promise.

| Stage | Pin | Indexes created (Papyrus version that adds it) | New tables | Creations | Minutes of index work | Budget attention |
|---|---|---|---|---|---|---|
| S1 | 5.85.2 | `Reference.listReferencesByStarFeedAndArrival` (5.79.0) | none | 1 | about 3 | none |
| S2 | 5.86.0 | `Reference.listReferencesByMediumFeedAndArrival` (5.86.0) | none | 1 | about 3 | none |
| S3 | 5.102.0 | `Reference.listReferencesByContentNeededAndArrival` (5.87.0), `Item.listItemsByParentAndOrder` (5.92.0) | `CurationDelegationRecord` (5.89.0) | 2 (two tables) | about 5 | none; 5.101.0 adds `backend-deploy` and cost tags to the generated spec, which this stage does not use |
| S4 | 5.107.2 | `Item.listItemsByHeadStageAndUpdatedAt` (5.103.0) | `Tenant`, `TenantMembership`, `TenantDomain` (5.105.0) | 1 | about 3 | head stage index fill after (section 4) |
| S5 | 5.109.0 | `Item.listItemsByScheduleStateAndScheduledPublishAt` (5.108.0) | `AnnouncementSettings`, `Announcement`, `AnnouncementSpend`, `XConnection` (5.109.0) | 1 | about 3 | none |
| **S6** | **5.112.1** | `Item.listItemsByLanguageGroupAndLanguage` (5.110.0) and 21 `...ByTenant` indexes (5.111.0), 22 on Distinctive's live tables plus `CurationDelegationRecord.listCurationDelegationRecordsByTenant` | `LocalizationRequest` (5.110.0), `SiteDocument`, `SiteDocumentVersion` (5.111.0), `TenantSelection` (5.112.0) | **23** | **about 54** | **does not fit Amplify's 30 minute timeout** |
| S7 | 5.130.2 | `LocalizationRequest.listLocalizationRequestsByStateAndRequestedAt` (5.115.0) | `EntityLabel` (5.120.0), `AnnouncementDecision`, `Delivery` (5.130.0) | 1 | about 3 | agents stack, wake queue, first build with the generated spec |

Why S6 and S7 are two stages. The script passes 5.109.0 to 5.130.2 as one stage at a 120 minute timeout (30 creations by its count, 23 for Distinctive) and fails it at 30 minutes:
`This release creates 30 indexes on existing tables ... but only 6 fit one release`. Machines on Machines job 107 created 23 indexes in 54 minutes and Amplify stopped the job at 30. Splitting
at 5.112.1 keeps the long index build alone in its own deploy, and keeps the 5.130 contract change (wake queue, runner policy gate, generated build spec) out of it, so a failure says which one broke.
5.112.1 is the newest stable version whose own `papyrus-infra` sets `_BUILD_TIMEOUT` (5.112.0 added it).

**Fallback split of S7.** If S7 fails on CloudFormation's limit of 2,500 resources in one operation (`Limit on the number of resources in a single stack operation exceeded`; see
[the two-deploy first backend](site-hosting.md#start-a-new-papyrus-site-the-two-deploy-first-backend)), take 5.126.0 first: 5.112.1 to 5.126.0 adds `EntityLabel` and one index on `LocalizationRequest`; 5.126.0 to 5.130.2 adds `AnnouncementDecision` and `Delivery`
and no index. Both pass the ledger. This was not measured; no synth or change set was run for any stage (see risks).

### Which stages need the bootstrap and first-stage budget attention

- **`PAPYRUS_BOOTSTRAP_STAGE` is not used.** It is for the first create of a brand-new site (about 2,700 resources in one operation); Distinctive is an existing stack and an update counts only what it creates or changes.
- **S6 needs a raised build timeout.** `_BUILD_TIMEOUT` is set by the app-shell stack from `cms.buildTimeoutMinutes` (default 120). Distinctive's app-shell stack has not been updated since 2026-10-22, so the app has no value. Without
  the update, S6 ends as job 107 did: the job is stopped at 30 minutes with no error while CloudFormation keeps going, and the next build must wait for it. That step is a person-run, reviewed change set (section 3, task T0).
- **S7** is the first build that runs `papyrus-infra backend-deploy` for Distinctive: after the release pass it adds the cost tags in waves of at most 1,800 resources until `PapyrusCostTagWave` says `complete`. Waves start only if they fit in the rest of the timeout; leftovers
  finish in the next build. Expect several passes in the first build (Machines on Machines' job 139 did one pass).
- **Cost tags are deliberately not adopted before S7.** The generated spec switches to `backend-deploy` at 5.101.0; S3 to S6 keep Distinctive's current `amplify.yml`, so no stage mixes index work with tagging.

## 3. What Distinctive changes at each stage (item 2)

### Every stage: the pin checklist

1. Edit the exact version in `package.json`, `infra/package.json`, `infra/site.json` (`papyrusVersion`) and `requirements-publication.txt`. `AGENTS.md` says "currently 5.67.0"; fix the number at S1.
2. `npm install --package-lock-only --ignore-scripts` in the repository root, then again in `infra/`.
3. `npm ci && echo '{}' > amplify_outputs.json && npx papyrus-app sync && npx tsc --noEmit`, then `.venv/bin/pip install -r requirements-publication.txt` and `.venv/bin/python -m unittest discover -s tests`, then `bin/build_local_site.py` (the local fixture render).
4. Pull request into `develop`; the stage ships in a release (`develop` to `main`, merge commit) that carries nothing else. One stage per release, so each release is its own deploy. **This is more than two releases in a day if run back to back; the extra releases need Ryan's say-so.**

### T0, before S6 (not a pin change): make the app-shell stack current

- `infra/site.json` needs an `email` block or `papyrus-infra synth` fails. The live account has an SES identity for the sending domain and a configuration set `papyrus-distinctive`, so the likely block is `{"mode": "existing", "sendingDomain": "<the newsletter sending domain>", "configurationSet": "papyrus-distinctive", "eventTopicName": "<the newsletter event topic>"}`. **Which values are right was not checked**; take them from the newsletter plugin's resources and confirm with the change set.
- `cms.buildTimeoutMinutes` is left at its default (120); it becomes `_BUILD_TIMEOUT` on the app.
- Synthesize with the 5.112.1 `papyrus-infra` (the `infra/package.json` pin may move to 5.112.1 alone for this), create a CloudFormation change set against the live stack, and have a person read it. The stack was last updated on 2026-10-22: expect Modify actions on the app, branch and roles, and look for any Replacement. No replacement of the app or branch is acceptable (the branch holds the backend).
- Apply it from Git by the repository's own pipeline or by the reviewed `papyrus-infra deploy` the infra README describes. Machines on Machines' equivalent (PR #265, `ci: deploy the app-shell stack on a push to main`) is open and unmerged, so there is no merged pipeline to copy yet. **Question for Ryan.**
- Check: `aws amplify get-app` shows `_BUILD_TIMEOUT` 120; the app id, branch and domain are unchanged.

### S1 to S5 (pins only)

Pins and lockfiles, nothing else. `amplify.yml` stays as it is (the plain spec). No config change is needed by any of these versions; the release notes between them were read as commit subjects only
(1,733 commits), not as a line-by-line diff, so each stage's pull request also reads that stage's commit list for `site.json`, `papyrus.config.ts` and `projection.json` changes before merging.

Data steps tied to a stage, run after its deploy, dry run first (each is a command in the Papyrus docs; the tables are small, about 49 TTAB References):

| After | Command | Why |
|---|---|---|
| S1 | rating writers set `starFeedKey` going forward; check [reference feed indexes](reference-feed-indexes.md) for whether existing rated References need a backfill | the index is empty for rows written before it |
| S2, S3 | `papyrus --site distinctive-mark.com references backfill-medium` (preview), then `--write` | sets `medium`, `mediumFeedKey`, `contentNeededKey` |
| S3 | `papyrus relations migrate-concept-tags` (dry run: "legacy related_to tags found N") | 5.101.0 renamed `related_to` to `tagged_with`; apply only if N is not 0 ([runbook](concept-tag-migration-runbook.md)) |
| S4 | `papyrus --site distinctive-mark.com stories head-index` (dry run; `--apply` when it lists keys to set) | the head stage index is dual-written from 5.103.0; Machines on Machines had 26 keys to set |

### S6 (5.112.1)

Pins and lockfiles, after T0. The deploy is the long one (23 index creations). No other change. After it, the new CLI can read the backend: before S6 it cannot (the 5.130 CLI's `guidelines convert` fails against the 5.73.0 backend with
`Field 'tenantId' in type 'EditorialCheckSettings' is undefined`, tried 2026-11-17, nothing written).

### S7 (5.130.2): the 5.130 contract

All of this is one pull request into `develop`, released alone:

1. **Pins and lockfiles** as above.
2. **`amplify.yml` becomes the generated spec**, as Machines on Machines did in its PR #319: `npx papyrus-infra print-buildspec --site infra/site.json --app cms-production > amplify.yml`. With this site's `infra/site.json` at 5.130.2 it is
   `npm ci`, `npx papyrus-infra backend-deploy`, the uv and Python 3.12 install of `papyrus-newsroom[markus]==5.130.2`, then `papyrus procedures seed-required`, `papyrus agents apply`, `papyrus agents schedules --site distinctive`,
   `npx papyrus-app alexa-sync || ...`, and a frontend phase with no `cp amplify_outputs.json` line (the generated markus-static spec has none). It must be regenerated at every later bump.
   Add a check that `amplify.yml` equals the generated spec (Machines on Machines has `features/build-spec.feature`; Distinctive has no `behave` harness, so either add it or write a unittest. The repository's standing rule asks for Gherkin: open question).
3. **Procedures** (item 2, "kind header lines and `papyrus-site-procedures.json`"). Each `.tac` file's **first line** becomes `-- papyrus-procedure-kind: <kind>`, with the existing description comment below it:
   `procedures/ttab_ruling_analysis.tac` is `distinctive.ttab.ruling-analysis`, `procedures/ruling_fact_check.tac` is `distinctive.ruling.fact-check`, `procedures/ruling_copy_edit.tac` is `distinctive.ruling.copy-edit`.
   New file `papyrus-site-procedures.json` at the repository root: `{"version": 1, "procedures": {"distinctive.ttab.ruling-analysis": "procedures/ttab_ruling_analysis.tac", "distinctive.ruling.fact-check": "procedures/ruling_fact_check.tac", "distinctive.ruling.copy-edit": "procedures/ruling_copy_edit.tac"}}`.
   The three skills under `.claude/skills/` are stored with them (each has a `SKILL.md`). Check before merging: `papyrus procedures seed-required --dry-run --json --root .` (needs the 5.130.2 CLI and a backend that has the tables, so after S6; the stage's own build is the first real run).
   The first build also writes the 15 core procedures and re-registers the three site ones as digest versions (the hand-registered `...-1` versions are archived).
4. **Tenant settings in `infra/site.json`**, decided in section 5 (question 3): `PAPYRUS_SITE_ID` and `PAPYRUS_TENANT_ID` in `cms.environment`, reaching the branch through a second app-shell deploy **before** this stage's release. They must not reach the branch before the data is adopted.
5. **`AGENTS.md`**: the bump section says the spec is generated; the "Where it runs" and "Map" sections gain the wake queue and the agent policy.

What the S7 deploy adds to the backend (read from Papyrus, not run): the `agents` stack (wake queue, dead-letter queue, alarm, queue-to-runner mapping, schedule group and role), the `admin-agent-policy-grant` stack, the file-reading guideline functions
and upload role, `ProcedureRun.wakeKey` and outcome fields, and the tables `EntityLabel`, `AnnouncementDecision`, `Delivery`. The runner's `ReadWakeQueues` statement is already live (the runner hold was lifted in #1661, released as 5.130.1), which is what made Machines on Machines' first 5.130.0 attempt fail (job 137).

### Wake queue and runner implications

- `papyrus-distinctive-agent-wakes.fifo` (brand id `distinctive`) exists only after S7. Until then a wake for Distinctive fails to start with `startFailed` naming the queue; nothing falls back to another start.
- The runner already holds the grant to call Distinctive's API (`DistinctiveApiId` in the runner stack) and, since the runner release, may read every `papyrus-*-agent-wakes.fifo`. The router gains the right to send to them only when the held monitoring stack is released.
- Story-stage bots (fact-check, copy-edit) are started by the site's own console function, the CLI or the runner after a stage run, so they too need the queue; they work only from S7.

### Amplify build timeout against index build time

| Stage | Index work (script's estimate) | Timeout needed | Verdict at 30 minutes |
|---|---|---|---|
| S1 to S5 | 3 to 5 minutes, plus the normal 10 to 20 minute build (job history: 10 to 14 minutes) | 30 is enough | fits |
| S6 | about 54 minutes (analogue: job 107) | at least 65 with the 10 reserved; 120 after T0 | **fails, T0 first** |
| S7 | about 3 minutes plus the new stacks, plus cost tag waves | 120 | unknown at 30; do not try |

## 4. Verification, stop rule and timing (item 3)

### After every stage (all read-only)

1. GitHub: the `ci` job and the `deploy` job are green for the exact commit; Amplify job `SUCCEED` through BUILD, DEPLOY and VERIFY (`aws amplify get-job`, or `npx papyrus-infra amplify job-log --app-id ... --job N`).
2. CloudFormation root stack `UPDATE_COMPLETE` (never start the next stage while it is `UPDATE_IN_PROGRESS`; after S7 also read the `PapyrusCostTagWave` output: `complete` or `W/N`).
3. Each index of the stage is `ACTIVE`: `aws dynamodb describe-table --table-name <Table>-<api id>-NONE --query 'Table.GlobalSecondaryIndexes[].[IndexName,IndexStatus]'`; an index still `CREATING` or backfilling blocks the next stage.
4. Public site: `https://distinctive-mark.com/sitemap.xml` lists the same 42 URLs (or the new count with a reason); five sample pages (home, a ruling, the docket archive, a section page, the newsletter signup) return 200 and their visible text matches the previous stage (strip markup; `reprojectOnDeploy` re-renders every page, so markup may differ, text may not). Record before S1: the sitemap, and a text hash of the sample pages.
5. CMS: `https://distinctive-mark.com/newsroom` answers 200; sign in with Google; the References, Stories and Automations pages load (an AppSync schema error shows as a red banner).
6. Monitor delivery: `papyrus-monitoring-ttab-route` and `web-distinctive-route` run at their next `:41` and `:57` with no new error in the router log; the collector's `STATE` for `MONITOR#ttab` still says `lastStatus: complete`. Before S7 a new TTAB item is refused by the new runner whatever the stage, so a refused trigger before S7 is expected, not a failure of the stage.
7. Newsletter: the `newsletter` plugin stack is unchanged (`UPDATE_COMPLETE`, no SES identity change); nothing is sent by a deploy.

### Stop and rollback rule

- **Stop** (do not start the next stage, do not retry in a loop, tell Ryan) when: a job is not `SUCCEED`; the root stack is `UPDATE_ROLLBACK_*` or `UPDATE_IN_PROGRESS` more than twice the stage's estimate; an index is not `ACTIVE` after twice its estimate; the sitemap loses a URL; the newsroom does not load; or a read shows a new error class in AppSync or a Lambda.
- **Rollback.** Indexes are additive, so reverting the pin pull request does not need another index change, and a reverted backend still reads the extra indexes and tables. Revert by a pull request that restores the four pins, both lockfiles (and, at S7, `amplify.yml`, the kind headers and the JSON file), released like any stage. A revert does not delete tables; leave them. A revert of S7 returns Distinctive to a backend the new runner refuses, which is the state before the plan.
- **A stack in `UPDATE_ROLLBACK_FAILED`** or a job stopped by the timeout with CloudFormation still running: nobody starts another build; Ryan decides.
- A rollback is never a manual change in the console or an AWS CLI write.

### Timing

| Window | Reason |
|---|---|
| Not between 02:50 and 03:50 UTC | the TTAB collection pass (02:58 UTC) and the first router pass after it (03:41 UTC) |
| S1 to S6 any other time | they change nothing the router starts until S7; the new runner refuses starts anyway |
| **S7 and the hold lift in one UTC day, finished before 02:58 UTC** | the only new decisions arrive in the 02:58 pass; if both are done before it, none is refused. If not, re-run what was refused (section 5, step 8) |
| Each stage waits for the previous one's checks | a deploy about every 1 to 2 hours if Ryan allows several releases in a day; S6 about 90 minutes with checks |
| `web-distinctive-monitor-stories` 07:30 UTC | avoid the half hour around it for S6 and S7 |

Who does what: **Claude (Distinctive session)** prepares each pin pull request, runs the local checks and the read-only post-deploy checks and records them on the Kanbus task; **Ryan** gives the go for each release (and for more than two in a day),
approves T0's change set, decides the tenant question and the rungs, and rotates the model key if needed; **a Papyrus engineer** opens the router config pull request and the hold-lift pull request.
Agents merge into `develop` and open the release pull request only when told to.

## 5. After the bump (item 4)

Order, each a separate task on the board:

1. **Head index and backfills**: `papyrus --site distinctive-mark.com stories head-index` (dry run, then `--apply`), `references backfill-medium`, as in section 3.
2. **Guideline conversion** (after S7; the dry run cannot run before S6, see above). As signed-in admin with the 5.130.2 CLI: `papyrus --site distinctive-mark.com guidelines convert` (dry run: it lists each lineage as ready or refused and reports `"applied": false`);
   then `--apply`; then `guidelines resolve` for the publication, one section and one language; `guidelines export`; `convert` again must show `already_files` for every lineage. Between S7 and `convert --apply` guidelines read `legacy_version`; no one saves guidelines in that gap.
   Machines on Machines' dry run read 64 requests (budget 200) and its apply converted three lineages. Distinctive's lineage count is not known.
3. **Site definitions.** `papyrus agents set-rung` accepts only an agent that has a definition file (core or the site's), so before any rung the site adds `papyrus-site-agents/` with `distinctive.ttab.yaml`, `distinctive.ruling.fact-check.yaml` and `distinctive.ruling.copy-edit.yaml`
   (the 11-line template of [automated processes](automated-processes.md), a `responsibility` from the catalog, `procedure`, `wakes`, `operations` with the lowest rung each needs). Check offline: `papyrus agents validate --dir papyrus-site-agents`.
   `agents apply` then writes only the registered copy on the existing automation (not `enabled`, not a rung). **Which operations the three procedures use, and whether the operation table has any that fit a ruling draft, was not checked**: if none, a definition cannot be filed honestly and the engine needs an operation first.
   This goes in its own release after S7, not in S7, so a definition error cannot fail the 5.130 build.
4. **Adopt** each automation onto a responsibility: `papyrus --site distinctive-mark.com automations adopt --id <id> --responsibility <key> --dry-run`, then without `--dry-run`. Adopting sets no rung.
5. **Rung.** `papyrus agents set-rung --id <id> --rung <rung> --reason "<Ryan's reason>"` (dry run), then `--apply` (admin who is a person; needs the `admin-agent-policy-grant` S7 deploys; the policy store fix is in 5.130.2). **Ryan decides the responsibility and the rung; an engineer never picks them.**
6. **Router config in Git.** New file `infra/monitoring/router-config/ttab.json` in Papyrus: the stored item without its key plus `tenantId` and `siteBucket`. It replaces the stored item whole, so every stored field is carried:

   ```json
   {
     "decisions": "direct",
     "enabled": true,
     "feedback": false,
     "maxItemsPerRun": 25,
     "mode": "live",
     "publications": [
       {
         "appsyncEndpoint": "${AppSyncEndpoint:Distinctive}",
         "openaiKeyParameter": "/amplify/shared/<the Distinctive Amplify app id>/OPENAI_API_KEY",
         "procedureTriggers": [
           {"procedureKey": "distinctive.ttab.ruling-analysis",
            "input": {"opinion_url": "{documentUrl}", "proceeding": "{sourceIdPrefix}"}}
         ],
         "publicationId": "distinctive",
         "site": "distinctive-mark.com",
         "siteBucket": "<the site's media bucket>",
         "tenantId": "<the tenant, question 3>"
       }
     ]
   }
   ```

   `siteBucket` is the `storage.bucket_name` of the site's `amplify_outputs.json`: the bucket whose name contains `papyrusmediabucket` (not the `sitebucket`, which is the public projection). `monitorStories` is absent from the stored item and stays absent. The story-stage automations name monitor `ttab`
   and publication `distinctive`, so this one entry gives all three automations their endpoint, key and policy location. `web-distinctive` stays as it is (outside Git, no triggers).
   Until `tenantId` and `siteBucket` are applied the runner refuses every Distinctive wake ("the request names no site policy").
7. **Lift the `papyrus-monitoring` hold** (remove the `hold` line in `infra/pipeline/stacks.json`, one reviewed pull request, released). The router config file applies in the same release because the stack applies changed files on release. Preconditions, all read before the go:
   S7 deployed and verified (the queue and its dead-letter queue exist, the alarm is quiet); steps 4 to 6 done; the model key works; the other sites: only `ttab` has `procedureTriggers`, but other sites' story-stage and Run now automations also start through the queue (see release-5-130-plan section 2), so ask which sites bump in the window or accept `startFailed` on the rest (question 6).
8. **After the lift**: `papyrus --site distinctive-mark.com automations runs --id distinctive.ttab` shows a run with a policy version and rung, not "Nothing to do (not_adopted)"; re-run each ruling the new runner refused between its switch and now (`papyrus automations run --id distinctive.ttab --input ...` per `TRIGGER#` row that is not `completed`);
   the once-only check `papyrus procedures check-wake-guard` is still unrecorded on a real site ("Not done" in the 5.130 board notes) and can be proved here if Machines on Machines has not done it.

### Responsibility and rung: the options

The catalog (`src/papyrus_content/responsibilities.py`) has no entry for a ruling analysis. The policy entry is keyed by responsibility, so two automations on the same responsibility share one rung unless a narrower override is written.

| Automation | Option | Fit | Note |
|---|---|---|---|
| `distinctive.ttab` (draft ruling page at the reporting stage) | `improve` ("Write and copy-edit") | closest: it writes draft versions of a Story | **recommended** |
| | `research` | it reads an opinion | its output is a draft, not research notes |
| | `intake` | it starts from a delivered item | it does not capture anything |
| | a new catalog entry, for example `analyze_ruling` | exact | an engine release and a catalog change; not worth it for one site now |
| `distinctive.ruling.fact-check` | `fact_check` | exact | **recommended** |
| `distinctive.ruling.copy-edit` | `improve` | exact | **recommended**; shares the rung with `distinctive.ttab` unless an override narrows it |

Rungs: `off` stops all three (not wanted). **`observe` is the recommended start** and the default Ryan named. Read it as it stands: the run gate starts a run at every rung above `off` and records the rung; it enforces nothing on a procedure that never asks the gate. All three Distinctive procedures
write through their own tools, so at `observe` they run and write exactly as they do today, and the policy only records. `draft` would be the honest label for "saves draft versions"
(releasing says to write the line "at the rung that matches today's behaviour"), but a rung cannot exceed what its definition needs, so it can be chosen only once the definitions list the operations. Raising the rung later is a policy change with a reason, never code.

## 6. Open risks and what could not be verified (item 5)

1. **No synth, change set or dry-run deploy was run for any stage.** Nothing here proves a stage stays under 2,500 resources in one CloudFormation operation. The evidence is indirect: Machines on Machines passed 5.111.0 (23 creations) and 5.130.0 on a backend of the same shape. The fallback split is 5.126.0.
2. **The app-shell stack was last updated on 2026-10-22 and its `site.json` does not validate.** The size of its change set is unknown. A replacement of the app or branch would be destructive. T0 stops there.
3. **The build timeout.** Even with `_BUILD_TIMEOUT` set, `docs/site-hosting.md` records two old Amplify reports of builds timing out with 120 or more. The first long release after T0 is the check.
4. **The tenant for Distinctive** (question 3). Distinctive's rows carry no `tenantId`. Setting `PAPYRUS_TENANT_ID` makes the site's Lambdas use the tenant client, under which untenanted rows are invisible until `papyrus content adopt-tenant-data --tenant <id>` has stamped them, and that command also
   re-keys every bare `NewsroomSection` row to `<tenant>#<key>` (it creates the new row and deletes the bare one). Whether the public projection and `projection.json` sections survive that re-key was not checked. The adoption dry run (read-only, possible after S6) lists the counts and conflicts before anyone decides.
   Policy, guidelines and the router all need a tenant (`AgentPolicyStore` is keyed by it). Whether they work on a dedicated stack with the tenant named only by `--tenant` and the router file, and no `PAPYRUS_TENANT_ID` on the site, was not verified.
5. **`reprojectOnDeploy`.** Every stage re-renders every page with the new engine, so the public HTML changes at S1 already. The checks compare text and URLs, not markup; `web/hooks.py` (the one `page_body` hook) could break on a projector change, which `bin/build_local_site.py` and the unit tests catch only for the fixtures.
6. **Model key.** Last modified 2026-11-01. Machines on Machines' key expired on 2026-11-14 and Distinctive's was not tested. The key must work before the hold lift, or the runs fail closed with "The run has no model key". Rotation is Ryan's.
7. **Operations for the definitions.** Not checked (task 3 above). It may need engine work.
8. **The 5.130 CLI against an older backend fails** (shown), and the installed CLI is 5.126.0, which has no `agents` group. Post-bump commands use `uvx --from papyrus-newsroom==5.130.2 papyrus ...`.
9. **Releases per day.** Seven stages and T0 are many releases; the policy allows once or twice a day.
10. **The TTAB analysis is refused from the next new decision (02:58 UTC collection) until S7 and the hold lift are done.** If the plan runs over several days, each day's new decisions are refused, not lost; they are started again by hand afterwards. No fallback start is added.
11. **Release-note reading.** Commits between tags were scanned by subject for data steps, not read in full. `docs/release-5-130-plan.md` step 1 expected Distinctive on 5.129.0 before the window; with the runner already on 5.130 an intermediate 5.129.0 has no use and is dropped.
12. **Not reviewed:** what else the held `papyrus-monitoring` stack would change when released besides the router and `ttab.json` (every change merged since the hold is in the same release). The stack's pull request dry run lists them and must be read before the lift.

## 7. Questions for Ryan

1. May the seven stages run on one day with more than two releases (S1 to S5 take about 15 to 20 minutes each, S6 about an hour)? Otherwise the plan takes four to five days and the ruling analysis stays refused throughout.
2. How should the app-shell stack (T0) be applied: a person-run reviewed change set, or the unmerged `ci: deploy the app-shell stack` workflow first? And what are the right `email` values for `infra/site.json` (the newsletter sending domain and its event topic; `existing`, not `managed`)?
3. The tenant: (A) set `PAPYRUS_TENANT_ID=distinctive` and `PAPYRUS_SITE_ID=distinctive` as Machines on Machines did, after `adopt-tenant-data` (dry run reviewed first, because it re-keys sections); or (B) keep the site untenanted and name the tenant only in the router file and `--tenant`, if the S7 build proves the guideline and policy paths work without it.
   Recommendation: take the adoption dry run after S6, then choose; do not set the variable before the adoption.
4. Responsibilities (section 5): `improve`, `fact_check`, `improve`, and the default rung `observe`. Recommended as listed. Or a new catalog entry for the analysis?
5. Is the Distinctive session allowed to merge its own stage pull requests into `develop` and open each release, or does each wait for your go?
6. Which other sites bump in the hold-lift window, or is `startFailed` on the rest for a while acceptable (release-5-130-plan question 4)?
7. Is Distinctive's model key valid, or does it need the rotation Machines on Machines needs?
8. Gherkin for the generated-spec check: add `behave` to Distinctive (as Machines on Machines has), or accept a unittest for this one check?
