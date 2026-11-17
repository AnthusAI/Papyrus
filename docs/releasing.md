# Releasing

Papyrus publishes two packages in lockstep from GitHub Actions with Semantic Release:
`@anthusai/papyrus` (npm) and `papyrus-newsroom` (PyPI). Both always carry the same
release number. Publishing uses npm and PyPI trusted publishing (OIDC); there is no
`NPM_TOKEN` or `PYPI_TOKEN` anywhere.

## How releases are cut

- Commit with conventional commits (`feat:`, `fix:`, `feat!:` or `BREAKING CHANGE` for real breaks).
- A squash merge takes the pull request's title as its commit message, so the title must start with `feat:` or `fix:` (a title like "Hooks: ..." releases nothing).
- A push that changes only files under `project/**` (the Kanbus board) never starts the Release workflow, so a release pull request must carry at least one change outside it. An empty commit or a board-only difference between `develop` and `main` publishes nothing (2026-11-09, #1317 and #1318).
- A push to `develop` publishes a prerelease `X.Y.Z-next.N` (npm dist-tag `next`; PyPI `X.Y.Z.devN`).
- A push to `main` publishes the stable version. `main` only changes by a release: a `develop` to `main` pull request with a merge commit, once or twice a day. Agents release only when told to, and an extra release needs Ryan's say-so (`AGENTS.md`, Git workflow, policy of 2026-11-04). Site bumps go to each site's `develop` and ship in that site's release.
- Versions are stamped into the staged copies only; nothing is committed back.
- Do not hand-tag. Semantic Release picks the first version (`1.0.0-next.1`).

## One new index per table per release

DynamoDB creates or deletes one global secondary index per table in one update, and a table holds at most 20. The GSI ledger check (`scripts/check-gsi-ledger.ts`, run by the `ts-misc` job and by `npm run test:gsi-ledger`) compares the indexes in every schema source (`amplify/data/schema.ts` and each plugin's and function's `schema.ts`) with the last stable release tag (the `ts-misc` job checks out the full history so tags exist; with no tag the check fails and says so) and fails when:

- a table gains more than one index since that tag (it names the table and every new index);
- an index keeps its name but changes its keys (add a new index and remove the old one in a later release);
- a table has more than 20 indexes, the DynamoDB limit per table.

It reports how many index slots each changed table has left, and prints the release order the pending indexes need: release 1 takes the first new index of each table, release 2 the second, and so on. A renamed index counts as a removal plus an addition. Rules and examples: `features_backend/gsi-ledger.feature`.

### The release budget: how many index creations fit one build

Amplify stops a build job at its build timeout (`_BUILD_TIMEOUT`, set by the app shell from `cms.buildTimeoutMinutes`, at most 120 minutes; [docs/site-hosting.md](site-hosting.md#build-timeout)), and the backend deploy runs inside that job. A release that creates an index on many tables takes long: Machines on Machines job 107 (2026-11-14, Papyrus 5.111.0) created 23 indexes, the data stack update took 54 minutes 10 seconds (3,250 s, about 141 s per creation), and Amplify's default 30 minute timeout stopped the job while CloudFormation was still updating. CloudFormation updated the model stacks in 8 sequential waves of up to 6 concurrent stacks; each wave took about 565 s (the slowest, ItemTag, 706 s).

The ledger check therefore also fails when a release creates more indexes on existing tables than fit the build timeout. The limit is `floor((build timeout minutes less reserved minutes) x 60 x (1 - safety margin) / slowest measured seconds per creation)`. With the 120 minute default, 10 reserved minutes and a 25 percent margin that is 35 creations (6 at Amplify's old 30 minutes). The measured figures, the reserve and the margin are data in `scripts/data/gsi-deploy-measurements.json`, not constants in code. A failure names the tables, states the limit and its inputs, and prints the release order split to fit (release 1, 2, 3 ...), each release still holding at most one new index per table. `--build-timeout MINUTES` checks against a shorter timeout (a site that sets a lower `cms.buildTimeoutMinutes`). Indexes created together with a new table do not count (SiteDocument and SiteDocumentVersion took 47 to 61 s).

Re-measure after any release that created indexes, once its CloudFormation update has finished (read-only access to the site's AWS account): `AWS_PROFILE=... AWS_REGION=... npx tsx scripts/measure-gsi-deploy.ts --root-stack <root backend stack> --index-creations N --label "<site, release>" --append`. N is the creation count the ledger check printed for that release. The slowest recorded seconds per creation sets the budget, so a faster later release never loosens it.

## Shared AWS stacks: pipeline roles

A release to `main` also deploys the shared AWS stacks (`.github/workflows/stack-deploy.yml`). That needs the pipeline's IAM roles. They are changed by the `role-stack-deploy` workflow when a change to `infra/pipeline/papyrus-stack-pipeline.yaml` is merged to `develop` or `main`: it plans in the job summary and the reviewer approves in GitHub, so the roles can be updated before the release that needs them. On a new AWS account a person runs the one-time setup (`infra/pipeline/bootstrap.sh --approver-only`, `infra/pipeline/create-environment.sh`). A release whose summary says "The pipeline roles are out of date" has an approval waiting. Details: [infra/pipeline/README.md](../infra/pipeline/README.md#changing-the-pipeline-roles-merge-then-approve-in-github).

## Enforcing the agent policy on a site

From the release that carries PPY-c8175e, the shared procedure runner reads each site's agent policy before it starts a run
([procedure runner](procedure-runner.md)). An automation that is not adopted onto a responsibility, or whose responsibility is not
raised above `off` in the site's policy, starts nothing: the run is recorded as "Nothing to do" with the reason `not_adopted` or
`rung_off`. So for every site that runs automations, **before the release that carries the runner reaches it**:

1. In the router config, name the site's `tenantId` and `siteBucket` on its publication (the site's media bucket; the policy body is at
   `tenants/<tenant>/site/agents/<version>.json` in it).
2. Adopt each automation (an admin who is a person, signed in with `papyrus login`). Dry run first:
   `papyrus automations adopt --id AUTOMATION_ID --responsibility KEY --dry-run`, then the same without `--dry-run`. Adopting sets no rung.
3. Write the policy line for that responsibility at the rung that matches today's behaviour, with a reason. **Ryan approves the rung;
   an engineer never picks it.** (There is no operator command for this yet: it is `papyrus agents set-rung` of slice H3, PPY-e6f31e, which also needs a
   production write adapter for the site store. Until it exists, enforcement cannot be turned on for a site that has automations.)
4. Check: `papyrus automations runs --id AUTOMATION_ID` after the next wake shows the run with the policy version and rung, not
   "Nothing to do (not_adopted)".

Distinctive's TTAB analysis is the automation `distinctive.ttab`. The responsibility catalog has no entry for a ruling analysis, so which one it
is adopted as, and at which rung, is Ryan's decision; the commands are on PPY-e713eb.

## Starting procedures through the wake queue

From the release that carries PPY-567bf9, nothing invokes the shared procedure runner directly. The monitoring router, Run now, the story-stage
triggers and translate-on-publish put a wake on the site's queue, `papyrus-<site>-agent-wakes.fifo`, and the runner consumes it
([the wake queue](procedure-runner.md#the-wake-queue)). Two things must be true for a site before its procedures can start:

1. **The site has its queue.** The queue is in the site's `agents` stack, which the site's second deploy adds (a first deploy leaves it out).
   The mapping from the queue to the runner can only be created after the runner's role may read the queues, so the runner stack's release
   (the statement `ReadWakeQueues`) comes before the first site deploy that creates a queue.
2. **The senders and the runner switch together.** The router and the runner are shared stacks and switch in one release; a site's own functions
   (Run now, translate-on-publish) switch with that site's backend. A wake for a site that has no queue yet fails to start and the trigger row says
   `startFailed` with the queue's name; nothing falls back to another way of starting, so a site that runs procedures (Distinctive Mark's ruling analysis,
   the story bots) is bumped and deployed in the same quiet window as the release, and what arrived in between is started again afterwards.

The role changes are in `infra/procedures/papyrus-procedure-runner.yaml` and `infra/monitoring/papyrus-monitoring.yaml`, and they reach AWS only through
the release. They need Ryan's approval first. Before the queue is relied on at a site, the live once-only create is proved on a site on a release with wake keys
(PPY-817340).

## Procedures are registered by the site's deploy

A site's Amplify build registers every core procedure and the site's own procedures right after the backend deploys (`papyrus procedures
seed-required`, in the generated production build spec; [details](procedure-runner.md#registering-procedures-the-deploy-does-it)). It needs
no step from a person and no change to a role: the build runs as the app's service role, which can sign GraphQL requests and use the
site's storage. A registration that fails fails the build. The first site build that carries it writes all 15 core procedures (ten
digests are new because the kind header was added to those files, seven kinds had never been seeded, and `rate_items`, the rating agent's, is new); later builds write nothing
until a procedure file or its metadata changes. A site's pin of Papyrus must carry the command: the build installs the pinned version, and
an older pin stops at the missing command instead of skipping the step.

## Agent definitions are applied by the site's deploy

Right after it registers the procedures, a site's Amplify build runs `papyrus agents apply` (the generated production build spec; [details](automations.md#applying-the-definitions-the-deploy-does-it)). It needs no step from a person and no new IAM permission: the build role already signs GraphQL requests to the site's API, which is all the step does (list, read, create and update `Automation` records). A site's own definitions are in `papyrus-site-agents` at its checkout root.

- It stops the build, before writing anything, when a definition is invalid or names a procedure that is not registered. **A core definition whose procedure is not registered therefore fails every site's build.** `core/rate.yaml` names `rate_items`, which the registry lists since PPY-d85860 (the procedure and the definition ship in the same release, and a test keeps them so).
- It creates each new agent's automation disabled, writes the registered copy (the same digest writes nothing) and retires a definition gone from Git. It never writes the agent policy document and never adopts an automation, so a deploy does not move a rung or a pause and a new agent arrives at `off`.
- The release that first carries it adds the optional `definitionRetiredAt` field to `Automation` (a field on an existing model, no index); the build deploys the backend before this step.

## The schedule group is reconciled by the site's deploy

Right after `papyrus agents apply`, the production build runs `papyrus agents schedules --site <brand id>` ([details](automations.md#the-schedule-trigger)): one EventBridge Scheduler entry for each switched-on agent that names a schedule, targeting the site's wake queue. **Unlike the apply step, it needs permissions the build role does not have yet** (the scheduler actions on the site's group, `iam:PassRole` on the scheduler role, the wake queue's address and the monitoring table read; the exact list is in automations.md). **Do not release a version that carries this step until a person has granted them**, or every site's build stops at it. The schedule group and the scheduler role are in the site's `agents` stack, which the first deploy of a new site leaves out.

## The first agent: rating on Machines on Machines (PPY-d85860)

The rating agent (`core/rate.yaml`, procedure `rate_items`; [the agent](design/always-on-agents-architecture.md), specs `features_backend/rating-agent.feature`) is the first
always-on agent. Once a day it reads the published Stories nobody has rated and, at the rung `observe`, only records what it would rate and why: no rating is written,
no review request is filed, and a five is only ever listed as a candidate. Nothing below has been run against a live site. Each step says who does it. **Ryan approves the rung;
an engineer never picks it.**

Before the first run (each is a separate decision or piece of work):

1. **The release.** The procedure, the definition and the `ratings` operation reach Machines on Machines through a release and the site's bump, in the quiet window the
   always-on agents track report describes (the runner and the backends switch together, one site at a time; this site's guideline conversion first). The site's build then registers
   `rate_items` and applies the definition on its own: the automation `rate` appears **disabled**, with its registered copy. (Engineer, with Ryan's go for the window.)
2. **The router publication names the site's policy.** In `infra/monitoring/router-config/hn.json`, the `machines-on-machines` publication has `tenantId` and `siteBucket`
   (PPY-d85860): the site's media bucket, where the policy body lives at `tenants/machines-on-machines/site/agents/<version>.json`. It is the same bucket the publication names as
   `monitorStories.storageBucketName`, and the one `papyrus agents set-rung` writes to (the site's published `media_bucket`, the `storage.bucket_name` of its `amplify_outputs.json`).
   The release applies the router config. Until it has, the runner refuses every wake ("the request names no site policy"). (Engineer.)
3. **The model key.** The site's key (`/amplify/shared/d260vp72hqglnc/OPENAI_API_KEY`, the router publication's `openaiKeyParameter`) expired on 14 November; the run fails closed
   without a working one (`The run has no model key`). PPY-6af46b. (Ryan rotates it.)
4. **Permissions for the schedule step** (the build role's scheduler, queue and monitoring reads), listed under "The schedule group is reconciled by the site's deploy" above. (Ryan grants.)
5. **The head stage index is filled.** The agent reads the published Stories from the head stage index and never scans. On the site, as an admin who is a person:
   `papyrus --site machines-on-machines stories head-index` (a dry run: it writes nothing) must report no keys to set or remove. If it does, run it with `--apply` first. (Engineer.)

The first run, in this order, signed in with `papyrus login` as an admin, `--site machines-on-machines`:

```
papyrus --site machines-on-machines automations adopt --id rate --responsibility rate --dry-run
papyrus --site machines-on-machines automations adopt --id rate --responsibility rate
papyrus --site machines-on-machines agents set-rung ...          # sets rate to observe; NOT BUILT: see below
papyrus --site machines-on-machines automations update --id rate --monitor hn --publication machines-on-machines --enabled true
papyrus --site machines-on-machines agents schedules --site machines-on-machines --dry-run
papyrus --site machines-on-machines agents schedules --site machines-on-machines
papyrus --site machines-on-machines automations run --id rate --input '{}'       # the first run now; otherwise the schedule runs it at 03:30 New York time
papyrus --site machines-on-machines automations runs --id rate
```

* `adopt` names the responsibility and sets no rung. Until a rung is set the policy says `off` for `rate`, and a wake is recorded as "Nothing to do (rung_off)", never run.
* **Setting the rung `observe` has no command yet.** `papyrus agents set-rung` is slice H3 (PPY-e6f31e) and needs the production write adapter for the site's policy store; until it is
  built, no one can put `rate` at `observe` on a site, and the agent cannot start. This is the one step that blocks the first run. The rung is Ryan's decision and is written with his reason.
* `update --monitor hn --publication machines-on-machines` links the schedule automation to the router publication that gives each tick the site's endpoint, model key and policy location
  (`hn` is the router config's monitor id). `--enabled true` switches it on; the schedule entry is created by `agents schedules` (the next deploy does it too).
* What the first run shows: `automations runs --id rate` lists the run as "✓ Did it (proposed)" or "– Nothing to do (nothing_unrated)", with the policy version and rung `observe`. The
  run's output lists each Story with the stars it would get and why, the five-star candidates for a person, any Story it could not judge, the gate's answers (the write
  operation `ratings_set` answers `human_required`, needing `draft`), and the cost. `papyrus stories list` shows no new rating. A person's judgement of the proposals is the evidence
  for raising the rung; raising it to `draft` is a change of the policy document and no code: the same run then writes threes and fours, never a five and never over a person's rating.
* To stop it: switch the automation off (`automations update --id rate --enabled false`, then `agents schedules`), or pause it in the policy (the pause stops the next wake and says why).
* Read it as it stands: the run reads every unrated published Story each day, newest first, until the index ends or the run's own deadline is near (the run says which). At `observe` nothing is
  rated, so the same Stories are judged again the next day and the model is paid for each time; the weekly budget (slice G1) is not built, so the cost is on the run record and nothing else limits it.
  Accepted References are not read: no index lists the accepted References that have no stars.

## The publish switch

The `release` and `pypi` jobs run only when the repository variable `PUBLISH_ENABLED`
equals `true` (Settings -> Secrets and variables -> Actions -> Variables). It is unset by
default, so pushes run only the package smoke checks and publish nothing. Set it only
after the registry setup below is done. Local check: `npm run release:dry-run` with
`GITHUB_TOKEN` set publishes nothing.

- After a stable release the `back-merge` job merges `main` back into `develop` (Git Flow). The stable tag sits on main's merge
  commit, so without it semantic-release on develop cannot see the tag and keeps numbering prereleases from an old version.

## Trying a prerelease in a publication

Every merge to `develop` that carries a `feat:` or `fix:` publishes `X.Y.Z-next.N` (npm dist-tag `next`, PyPI `X.Y.Z.devN`),
built from develop exactly as a release is built from main. To develop a site feature without releasing to `main` each time,
pin the site to that exact prerelease, the same way it pins a release (the site's `package.json`, `infra/package.json` and
`infra/site.json` `papyrusVersion`), and put the site change in the same pull request to the site's `develop`, so it ships in one release. Go back to a stable
version once the feature is released.

```
npm view @anthusai/papyrus dist-tags.next      # the newest develop prerelease
npm i @anthusai/papyrus@next
pip install --pre papyrus-newsroom
```

## One-time registry setup (Ryan, by hand)

npm (https://www.npmjs.com):
1. Sign in as an Owner of the `anthusai` organization (avatar menu -> Organizations -> `anthusai` -> confirm your role is Owner).
2. Create the package once so a trusted publisher can be attached. In a terminal: `npm login` (browser + OTP), then
   ```
   mkdir /tmp/papyrus-bootstrap && cd /tmp/papyrus-bootstrap
   printf '{"name":"@anthusai/papyrus","version":"0.0.0","description":"Placeholder; releases are published by GitHub Actions.","license":"MIT","repository":{"type":"git","url":"git+https://github.com/AnthusAI/Papyrus.git"}}' > package.json
   npm publish --access public      # enter the OTP when asked
   ```
3. Open https://www.npmjs.com/package/@anthusai/papyrus -> **Settings** tab -> **Trusted Publisher** section -> choose **GitHub Actions** -> Organization or user `AnthusAI`, Repository `Papyrus`, Workflow filename `release.yml`, Environment name leave EMPTY -> **Set up connection**.
4. Same Settings page -> **Publishing access** -> select **Require two-factor authentication and disallow tokens** -> **Update Package Settings**.

PyPI (https://pypi.org):
1. Sign in (enable 2FA if not already: Account settings -> Two factor authentication).
2. Go to https://pypi.org/manage/account/publishing/ (Account settings -> **Publishing**). Under **Add a new pending publisher**, GitHub tab: PyPI Project Name `papyrus-newsroom`, Owner `AnthusAI`, Repository name `Papyrus`, Workflow name `release.yml`, Environment name leave EMPTY -> **Add**. No placeholder publish is needed; the first release creates the project and the publisher becomes active.
3. After the first release, open the project -> **Manage** -> **Publishing** and confirm the GitHub publisher is listed.

GitHub: Settings -> Rules/Branches: confirm `develop`/`main` rules allow GitHub Actions to create `v*` tags and releases (semantic-release pushes tags only, no commits).

Finally, create the repository variable `PUBLISH_ENABLED` = `true` to turn publishing on. Also confirm you want a public `@anthusai/papyrus` (decided 2026-10-05: public, MIT).
