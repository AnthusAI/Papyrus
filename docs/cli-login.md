# Native newsroom CLI login

`papyrus login` opens normal Google sign-in through a **reviewed public
Cognito app client**, then stores the renewable session in the machine's secure
credential store (see [Supported platforms](#supported-platforms-and-secure-storage)).
Editorial requests use the same Cognito user-pool authorization as the newsroom;
AppSync remains responsible for validating the token and enforcing permissions.
This does not grant an operator role or require personal AWS SSO.

This implementation is reviewable code, not activated provider configuration.
The existing Prospectus server client has 60-minute access/ID/refresh validity
and discards refresh tokens. Do not silently reuse it for an unattended CLI
session or extend browser sessions as part of setup.

## Install the CLI so `papyrus` is on your PATH

Install the published package as a tool, not into a project virtualenv. A tool install
puts the `papyrus` command on your PATH in every shell:

```sh
pipx install papyrus-newsroom        # or: uv tool install papyrus-newsroom
pipx upgrade papyrus-newsroom        # or: uv tool upgrade papyrus-newsroom
```

The package declares the `papyrus` console script (`[project.scripts]` in
`pyproject.toml`). Inside a Poetry checkout `papyrus` exists only while that
virtualenv is active (or as `poetry run papyrus`), which is why a bare `papyrus login`
fails elsewhere. `papyrus doctor` reports which kind of install you are running:

```text
version   0.1.0   (newer release 0.2.0 available; upgrade with `pipx upgrade papyrus-newsroom` ...)
install   pipx tool install
on-path   ~/.local/bin/papyrus
site      shipped.anth.us   signed in, session valid
site      p.apyr.us         expired or revoked; run `papyrus login p.apyr.us`
```

It compares against the latest PyPI release (a lookup that is skipped with `--offline`
and simply reported as unknown when PyPI is unreachable), says whether you are in a
tool install, a virtualenv or system Python, and checks each signed-in site. It exits
non-zero when a site needs a new login. It prints no tokens and no account identity.

## Supported platforms and secure storage

Sign-in, renewal, locking and storage come from the shared
[`cli-login`](https://pypi.org/project/cli-login/) library (pinned to an exact
version). Papyrus keeps only what is its own: reading a site's
`/.well-known/papyrus-cli.json`, the registry of signed-in sites, picking the session
that owns a GraphQL endpoint, and the `login`, `logout`, `whoami` and `auth status`
commands.

| Platform | Where the session is kept |
| --- | --- |
| macOS | Keychain, service `papyrus-newsroom-oauth`, one item per site key (sessions saved by earlier CLIs keep working) |
| Linux | Secret Service (an unlocked desktop keyring), then the kernel keyring, then the memory agent |
| Windows | Credential Manager |

There is never a plaintext fallback. If no secure store is usable, `papyrus login`
fails with the steps to fix it and writes nothing. Set `CLI_LOGIN_STORE` to
`keychain`, `secret-service`, `kernel-keyring`, `agent` or `credential-manager` to
choose a store explicitly.

### Cloud machines and containers

A cloud machine usually has no desktop keyring. Start the memory agent once, then sign
in again:

```sh
python -m cli_login.stores.agent serve --namespace papyrus-newsroom-oauth --background
python -m cli_login.stores.agent status --namespace papyrus-newsroom-oauth
python -m cli_login.stores.agent stop   --namespace papyrus-newsroom-oauth
```

The agent keeps sessions in memory only, behind a private Unix socket, so they last
until it stops or the machine restarts; sign in again after that. The agent is not
available on Windows in this version.

`papyrus login --remote` signs in from a machine with no browser at all, and needs no
agent unless the machine has no keyring either: see
[Remote sign-in from another device](#remote-sign-in-from-another-device).

## Remote sign-in from another device

An agent on a cloud machine has no browser and should hold no long-lived keys. It runs

```sh
papyrus login --remote shipped.anth.us
```

and prints an approval URL and a short matching code, then waits (up to 10 minutes):

```text
To approve this sign-in, open https://shipped.anth.us/cli/approve?t=...
and check that the page shows the code BCDF-GHJK.
```

Open the URL on your phone, sign in with Google on the site, check that the page shows
the same code and approve. The waiting CLI receives the session and stores it exactly
like a normal login (the same secure store, key and registry), then prints
`Signed in as <you>.` The approval URL and code are an approval capability: whoever opens
the URL and signs in first owns the session. When the agent knows who should approve, add
`--expect-email you@example.com`; the CLI then refuses, and stores nothing, if anyone else
approved. Nothing secret is printed or relayed: the broker sees only hashes of the CLI's
secrets, and the code it holds for a moment is useless without the CLI's PKCE verifier.

On a machine with no keyring, start the memory agent first (see
[Cloud machines and containers](#cloud-machines-and-containers)); sessions then live in
memory only. A site that has not switched this on answers
`<site> does not publish a remote sign-in broker`, and nothing is started. A denied or
expired approval, or an approval link that was already used, stores nothing.

### Switching it on for one site

Remote sign-in is **off for every site** until the site turns it on. It is built on the
shared [`cli-login`](https://github.com/AnthusAI/cli-login) broker protocol
(`docs/protocol.md` there) with one broker per site:

| Piece | Where it lives |
| --- | --- |
| Broker (Lambda function URL for `/start` and `/poll`, DynamoDB transactions, alarms) | the site's Amplify backend, in the `CliRemoteLogin` stack (`amplify/cli-login/remote-login.ts`) |
| Approval pages function (the library's own `ApprovalPages`, Python) | the same stack (`amplify/functions/cli-login-pages`) |
| `/cli/approve` and `/cli/callback` | the site's Next.js app, which forwards them to the pages function with IAM (`lib/cli-login-pages.ts`) |
| `https://<site>/cli/callback` | registered as a sign-in return URL on the site's existing web app client (never a logout URL) |
| `broker_endpoint`, `remote_callback_uri` | added to `/.well-known/papyrus-cli.json`, only when the backend outputs name them |

The broker, the pages and the CLI run the same pinned `cli-login` release
(`amplify/cli-login/bundle.ts` and `pyproject.toml`; a test keeps them equal).

To turn it on, set `cliRemoteLogin: true` in the `cms` block of the site's app-shell
`site.json`, then deploy the app-shell stack and the site's backend:

```json
"cms": { "cliRemoteLogin": true }
```

The app-shell stack then sets two variables on the production branch:
`PAPYRUS_ENABLE_CLI_REMOTE_LOGIN=true` and `PAPYRUS_CLI_INVOKER_ROLE_ARN` (the app's
compute role, the only principal allowed to invoke the pages function). A site whose
backend is configured without the app-shell can set the same two variables itself, or set
`features: { cliRemoteLogin: true }` in `defineSiteBackend`. The site also needs
`PAPYRUS_SITE_ORIGIN`, which production branches already have. With the flag off, the
synthesized backend and the Cognito client are unchanged.

### Operating the broker

The broker has two CloudWatch alarms in the `CliRemoteLogin` stack, checked every five minutes:

| Alarm | Meaning |
| --- | --- |
| `StartCeilingAlarm` | The broker refused login starts at its ceiling across all callers: too many login starts, such as a flood from many addresses. |
| `ThrottledAlarm` | The broker Lambda reached its reserved concurrency of 10 and is being throttled. |

Both notify the site's alarm topic when they fire and when they recover. Set the topic with
`alarmTopicArn` in the `cms` block of the site's app-shell `site.json`; the app-shell stack
passes it to the backend as `PAPYRUS_ALARM_TOPIC_ARN` on the production branch:

```json
"cms": { "cliRemoteLogin": true, "alarmTopicArn": "arn:aws:sns:<region>:<account>:<topic>" }
```

The topic ARN belongs in the site's own config, never in this repository, and so does the
subscription that delivers the notifications. Without the setting the alarms exist but
notify nobody, and synth prints one warning that names the setting.

## Sign in by site name

```sh
papyrus login shipped.anth.us          # host name, or an https origin
papyrus login shipped.anth.us p.apyr.us pilobol.us
```

The CLI reads the site's public sign-in values from
`https://<site>/.well-known/papyrus-cli.json`. It reads that file only over HTTPS,
refuses every redirect, caps it at 16 KiB, rejects any field it does not know, requires
every field it does, and requires `publication` to equal the origin you asked for.
The same validation as for a hand-written config then applies (HTTPS endpoints, a
registered loopback callback, and so on). Nothing is saved if any check fails.

If a site's frontend does not serve the file, the CLI says:
`<site> does not publish CLI login (its sign-in client does not register the CLI callback)`.
Deploy a frontend that includes the route (see
[How a site publishes the file](#how-a-site-publishes-the-file)). `--config` keeps
working for a site you configure by hand.

Sign-in uses the fixed callback `http://localhost:3001/`. If something else already
listens on that port (a dev server, another login), the CLI stops before opening a
browser and says `Sign-in needs local port 3001 ... already in use`; stop that program
and run the login again. Signing in to several sites at once is sequential, so one
login never competes with another for the port.

## Many sites at once

Signed-in sites are kept in a registry of **public** metadata (the same
`user-session.json` in the state directory, mode 0600, atomic writes under a lock, and
the same symlink refusals). Renewable secrets stay in the OS credential store under the
same per-site keys as before, so existing sessions survive the upgrade. A single-site
`user-session.json` written by an earlier CLI is read as a one-site registry and is
rewritten in the new shape the next time a site is saved.

| Command | Effect |
| --- | --- |
| `papyrus login <site> [<site> ...]` | sign in to each, adding it to the registry |
| `papyrus login --all` | sign in again to every site in the registry (a failure is reported and the rest continue; exit status is non-zero) |
| `papyrus login` | sign in again to the only registered site (otherwise it asks you to name one) |
| `papyrus whoami [<site>]` | renew and show every signed-in site, or one |
| `papyrus auth status [<site>]` | local status for every site, without renewing |
| `papyrus logout <site>` / `--all` | remove the stored session (and revoke it where reachable) |

`papyrus logout` with no name is refused when several sites are signed in. A signed-out
site stays in the registry so a later command cannot silently fall back to IAM.

### How a request picks its session

Every GraphQL request carries its endpoint. The CLI uses the registered site whose
`graphql_endpoint` equals it exactly, and a token is only ever sent to that endpoint.
If no signed-in site owns the endpoint, the request fails and the message lists the
signed-in sites and tells you to run `papyrus login <site>` (or to choose
`PAPYRUS_GRAPHQL_AUTH=iam` deliberately); it never uses another site's session or your
AWS credentials. A site whose file names an endpoint already registered for a different
site is refused, so one site cannot capture another's requests. `--config` and
`PAPYRUS_CLI_AUTH_CONFIG` still select exactly one hand-written config.

## How a site publishes the file

No infrastructure or backend change is needed. The app shell serves
`/.well-known/papyrus-cli.json` from the site's own `amplify_outputs.json`, so deploying
a frontend that includes the route is the whole setup. The file reuses the site's
**existing public web app client** (`auth.user_pool_client_id`: no secret, authorization
code flow, Google, 30-day refresh), the user pool id and region (the issuer), the
hosted-UI domain, and the GraphQL URL (`data.url`). The callback is always
`http://localhost:3001/`, which every app-shell site already registers
(`infra/amplify-app-shell/lib/site-config.ts`). The route emits the file only if that
exact URI is in the outputs' `auth.oauth.redirect_sign_in_uri`; otherwise it answers
404. The `publication` value comes from `PAPYRUS_SITE_ORIGIN`, never the request's Host
header. Every field is public. The publication API still decides what a signed-in
person may do under the normal user/group permissions.

## Required configuration and approval

Before a **real** login, the identity/publication owner must review and configure:

- An approved public client on the existing publication user pool, using
  Google, authorization code and PKCE S256; no embedded client secret.
- Its exact loopback callback. URLs may use literal `127.0.0.1` or `localhost`;
  the listener always binds only `127.0.0.1`, never a hostname or wildcard
  interface. Use a registered fixed available port/path. Other callback hosts,
  credentials, query strings and fragments are refused.
- The client/audience accepted by the publication API, normal user/group
  permissions, token revocation and the chosen refresh/rotation policy. No new
  grants, identity pool credentials or custom authorizer are introduced here.
- The authoritative publication/tenant/account authorization boundary. This
  first slice binds a session to one declared publication endpoint and client;
  it does **not** implement the multi-account Prospectus selection/BFF work in
  PPY-58f1. A local publication URL is not an authorization grant. Do not activate
  a multi-tenant deployment until the server verifies its account/publication
  grants and the normal-user API boundary has been approved and tested.

These are action-time provider/security configuration decisions. No live app
client, credentials, callback, role, session lifetime or deployment was changed
while developing this PR. There is no production client id to copy from this
example.

An existing reviewed public web client can also support a basic native login
test if it already admits Google code/PKCE, has no secret, registers an allowed
loopback URL and has an appropriate existing refresh policy. A separate native
client is not intrinsically required for that test. Reuse the exact registered
URL; substituting `127.0.0.1` for `localhost` fails OAuth's redirect match. Do not
change live client settings or grant permissions merely to make a test pass.
This corrects the earlier assumption that every live test needs a new client.
The separate short-lived Prospectus server client remains unsuitable.

Without site discovery you can still save reviewed **public metadata** as
`.papyrus/cli-auth.json` in the selected publication, or point
`PAPYRUS_CLI_AUTH_CONFIG` at it (this is also exactly what a site's
`/.well-known/papyrus-cli.json` contains):

```json
{
  "publication": "https://newsroom.example.test",
  "issuer": "https://cognito-idp.us-east-1.amazonaws.com/REVIEWED_POOL_ID",
  "client_id": "REVIEWED_NATIVE_CLIENT_ID",
  "oauth_domain": "https://REVIEWED_DOMAIN.auth.us-east-1.amazoncognito.com",
  "graphql_endpoint": "https://REVIEWED_API.appsync-api.us-east-1.amazonaws.com/graphql",
  "callback_uri": "http://127.0.0.1:5182/oauth/callback",
  "refresh_lifetime_seconds": 172800
}
```

`refresh_lifetime_seconds` is an optional **configured value for status display**,
not a TTL the CLI can impose on Cognito or a remaining-lifetime guarantee. The
172800 value above is illustrative, not a policy applied to a live client.
Published metadata must agree with reviewed provider settings and the current
publication's `PAPYRUS_GRAPHQL_ENDPOINT`/Amplify outputs. The CLI rejects endpoint
mismatches before sending any token. It never guesses a client or tenant: it uses only a
site's own published file or the config you pass.

## Commands

From the configured publication checkout:

```sh
papyrus login newsroom.example.test
papyrus login --publication https://newsroom.example.test --config .papyrus/cli-auth.json
papyrus auth status
papyrus whoami
papyrus stories show --story EXISTING_LINEAGE
papyrus logout
```

Only `login` opens a system browser. The callback has a bounded timeout, checks
state/path and never logs its authorization code. `whoami` renews through the
provider without an AWS credential probe. `auth status` inspects local metadata
and does not prove current remote grants or that an opaque refresh token remains
valid. A protected API request must still succeed under server authorization.
The CLI never fabricates a human editorial label from a signed-in identity;
agent authorship/approval attribution remains the caller's explicit content
metadata and the existing server action's responsibility.

For a `localhost` redirect, the browser must reach the IPv4 loopback listener.
If another application occupies the registered port, login fails safely; do not
stop a user's server or bind a public interface. Check port availability before
an approved interactive test.

The registry of signed-in sites is stored in a private metadata directory
(`~/.config/papyrus` by default, override `PAPYRUS_CLI_STATE_DIR`). Renewable
secrets and subject/label records live in the secure store, scoped by the complete
issuer/client/publication/endpoint/callback binding. Short-lived ID tokens are
in process memory only. There are no token argv, environment variables, repo
files or plaintext fallback. Child CLI/Tactus processes use the same public
registry and read their own renewable secret from the OS store.

A locked or unavailable store fails with a useful error and does not trigger a
surprise unlock prompt. Python interface tests use synthetic store/provider fixtures,
never production credentials.

Rotation reads and replaces the latest secret under a process-shared file lock;
lock files contain no token data. Transient provider/network failures retain the
session. Confirmed `invalid_grant` removes the unusable secret and requests an
explicit login. No noninteractive command opens a browser or changes identity.
User-authenticated API requests are not replayed after uncertain delivery.

`logout` always attempts local deletion, attempts provider refresh-session
revocation and reports whether remote revocation was confirmed. It does not
claim global signout or immediate invalidation of every previously issued JWT.
If local secure-store deletion fails, logout returns an error. Public registry
metadata remains as a signed-out binding so a subsequent command cannot
silently fall back to a broader IAM identity. Each site needs its own
`papyrus login <site>`; no credential is reused across bindings.

For deliberate operator work, `PAPYRUS_GRAPHQL_AUTH=iam` keeps the existing AWS
credential chain. Managed Lambdas continue using IAM. A failed user session
never automatically chooses that lane. The guest reader-export lane remains
read-only and cannot author private content.

## Session duration and evidence

Cognito supports renewable sessions beyond 24 hours, but actual validity is a
provider/client policy. The current one-hour Prospectus client does not meet
that goal. This implementation renews short-lived tokens instead of issuing or
requesting a 24-hour access token. Revocation, removed grants, unavailable
services and policy expiry can require recovery sooner.

Tests prove code behavior with mocked expiry/rotation/revocation, an actual
fresh Python process after **25 simulated hours**, concurrent session refresh,
loopback state rejection and timeout, cross-publication refusal, server denial,
no IAM escalation, secret-safe errors and honest offline logout. They do not
prove a live session lasts a day. `elapsed_24h_live_verified: false` explicitly
keeps that distinction in status output. No real elapsed 24-hour acceptance,
Google login, Keychain credential read/write or live permission-parity test has
run. The store backends are tested in the `cli-login` library; complete
credential-free tests and CI remain the review gate.

Reference implementation: [Apricity cloud CLI](https://github.com/AnthusAI/Apricity/blob/ffe8a023b0418445aa67893a52ae9e173c366d42/crates/apricity-cli/src/cloud.rs#L206).
OAuth uses the native-app pattern in [RFC8252](https://www.rfc-editor.org/info/rfc8252/).
Provider details: [refresh tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-refresh-token.html)
and [revocation](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html).

CLI login is separate from research execution: this PR does not replace the
hosted empty seeded packet, run a console-agent exchange, or prove execution of
a registered Tactus procedure.
