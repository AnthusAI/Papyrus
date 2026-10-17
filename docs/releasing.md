# Releasing

Papyrus publishes two packages in lockstep from GitHub Actions with Semantic Release:
`@anthusai/papyrus` (npm) and `papyrus-newsroom` (PyPI). Both always carry the same
release number. Publishing uses npm and PyPI trusted publishing (OIDC); there is no
`NPM_TOKEN` or `PYPI_TOKEN` anywhere.

## How releases are cut

- Commit with conventional commits (`feat:`, `fix:`, `feat!:` or `BREAKING CHANGE` for real breaks).
- A push to `develop` publishes a prerelease `X.Y.Z-next.N` (npm dist-tag `next`; PyPI `X.Y.Z.devN`).
- A push to `main` publishes the stable version. Agents never merge to `main`.
- Versions are stamped into the staged copies only; nothing is committed back.
- Do not hand-tag. Semantic Release picks the first version (`1.0.0-next.1`).

## The publish switch

The `release` and `pypi` jobs run only when the repository variable `PUBLISH_ENABLED`
equals `true` (Settings -> Secrets and variables -> Actions -> Variables). It is unset by
default, so pushes run only the package smoke checks and publish nothing. Set it only
after the registry setup below is done. Local check: `npm run release:dry-run` with
`GITHUB_TOKEN` set publishes nothing.

## Trying a prerelease in a publication

```
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
