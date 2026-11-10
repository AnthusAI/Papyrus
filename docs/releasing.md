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

DynamoDB creates or deletes one global secondary index per table in one update, and a table holds at most 20. The GSI ledger check (`scripts/check-gsi-ledger.ts`, run by the `ts-misc` job and by `npm run test:gsi-ledger`) compares the indexes in `amplify/data/schema.ts` with the last stable release tag and fails when:

- a table gains more than one index since that tag (it names the table and every new index);
- an index keeps its name but changes its keys (add a new index and remove the old one in a later release);
- a table has more than 18 indexes.

It warns when a table has 16 or more, and prints the release order the pending indexes need: release 1 takes the first new index of each table, release 2 the second, and so on. A renamed index counts as a removal plus an addition. Rules and examples: `features_backend/gsi-ledger.feature`.

## Shared AWS stacks: pipeline roles

A release to `main` also deploys the shared AWS stacks (`.github/workflows/stack-deploy.yml`). That needs the pipeline's IAM roles. They are changed by the `role-stack-deploy` workflow when a change to `infra/pipeline/papyrus-stack-pipeline.yaml` is merged to `develop` or `main`: it plans in the job summary and the reviewer approves in GitHub, so the roles can be updated before the release that needs them. On a new AWS account a person runs the one-time setup (`infra/pipeline/bootstrap.sh --approver-only`, `infra/pipeline/create-environment.sh`). A release whose summary says "The pipeline roles are out of date" has an approval waiting. Details: [infra/pipeline/README.md](../infra/pipeline/README.md#changing-the-pipeline-roles-merge-then-approve-in-github).

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
