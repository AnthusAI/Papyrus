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

### A console on its own host

When the newsroom console is served from its own host (`cms.consoleOrigin` in the app-shell
`site.json`, for example `https://newsroom.shipped.anth.us`), the app shell sets
`PAPYRUS_CONSOLE_ORIGIN`, and remote login follows it: the approval page and the callback
(`/cli/approve`, `/cli/callback`) and the Cognito return URL are on the console origin, and
`broker_endpoint` and `remote_callback_uri` in `/.well-known/papyrus-cli.json` name it.
`PAPYRUS_SITE_ORIGIN` stays the public site's origin. The login file names the console origin
as `publication`, because the CLI requires `publication` to equal the origin it was given.
The new address is therefore `papyrus login --site https://newsroom.shipped.anth.us` (or
`papyrus login --remote newsroom.shipped.anth.us`). The public host serves the same file, so
the CLI refuses it there with the publication mismatch until the old address is retired.

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

## Authorization

Signing in says who you are. Which Account you may act in, and with what role, is Prospectus's answer, asked at the moment of
each operation. Pool groups alone are not authorization.

This is off until a site turns it on (`features.prospectusAuthorize`, or `PAPYRUS_ENABLE_PROSPECTUS_AUTHORIZE=true`), after
enrollment works for that site. With it off the backend is exactly what it was: no extra data source, pipeline function,
Lambda environment or permission, and the same synthesized templates. With it on:

- Every account-scoped operation sends the chosen Account in `X-Prospectus-Account` and the person's own access token in
  `X-Prospectus-Human-Token`. The CLI starts sending both when Account selection lands (PPY-2d3dd9); until then
  turning this on would refuse every CLI call, so a site turns it on only after that.
- The backend calls `POST /v1/accounts/{id}/authorize` as the site's role with `console:read`, `console:write` or
  `members:read`, immediately before the effect. It proceeds only when `allowed` is true and the answer's `accountId` is the
  requested one. A missing header, a missing token, an unreachable Prospectus, a server error or any other answer refuses. The
  GraphQL error types are `AccountRequired`, `AuthorizationDenied` and `ReenrollmentRequired`.
- When Prospectus answers `401` or `403` with `reenrollment_required`, that passes through as `ReenrollmentRequired` and the CLI
  prints "Your login is no longer enrolled with Prospectus. Run `papyrus login` again." and exits non-zero. A request with no
  Account prints "Choose an account: papyrus account use <name>".
- The site's own IAM functions (the router, monitors, projection) carry no human token and are not asked. They are machines
  inside the site.

The Lambda resolvers use `src/papyrus_content/prospectus_authorize.py` and `lib/prospectus-authorize.ts` (twins, one table that
maps a field name to the operation). The JavaScript resolvers use the pipeline function
`amplify/data/resolvers/prospectus-authorize.js` behind an IAM-signed HTTP data source named `ProspectusAccounts`, placed first
in each account-scoped mutation's pipeline. The Prospectus accounts API must allow the signing principal: see the open
question on the epic about the registered role and an execution delegation.

For the private chat host, which does not use this, see [private chat authorization](newsroom-private-chat-authorization.md).

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

## Enrollment

Enrollment makes a CLI login a Prospectus Person. It is off for every site until the site switches it on, and it
covers both `papyrus login --remote` and the local `papyrus login` (cli-login 0.4.0 `prepare` and `enroll` hooks).

**Switching it on.** Set `PAPYRUS_ENABLE_CLI_ENROLLMENT=true` in the backend build, next to remote CLI
login. The pages function then gets `SITE_CHALLENGE_ORIGIN` (the site's own origin), the stack gets a small throttle
table, and the site's Amplify outputs carry `cliLogin.enrollment: true` and the table name, which turn on `/cli/challenge`
and `/cli/enroll`. The pages function holds no Prospectus access. With the flag off none of this exists and the stack synthesizes unchanged.

**The flow.**

1. Central Prospectus admits challenge and resolve only from the site's registered compute role, so the pages
   function does not call it. On Approve (`amplify/functions/cli-login-pages/login_challenges.py`) it asks the site's
   `GET /cli/challenge?loginStateDigest=<sha256hex(T)>`, where T is the broker transaction; that route runs as the
   compute role and calls Prospectus. The route and the pages function both accept the answer only if the status is
   200, `challengeId` is a UUID4, the nonce matches `^[A-Za-z0-9_-]{32,256}$`, `expiresAt` is within the next 300
   seconds and the token is a signed `v1.` challenge. Otherwise nothing is bound and the page says the service is
   unavailable.
2. The challenge nonce is the OpenID nonce of the Google sign-in; the signed challenge token is the opaque
   enrollment the broker hands only to the CLI that holds the poll secret.
3. After the code exchange the CLI posts `{challengeToken, idToken, loginState: T}` with its access token as the
   bearer to `/cli/enroll`. The route verifies both tokens against the site's registered federation client (issuer,
   audience or client id, expiry, same subject and same `auth_time`) and asks Prospectus to resolve them as the site.
   A local `papyrus login` asks the site first (`GET /cli/challenge?state=<its own state>`, bound to `sha256hex(state)`,
   never unbound), uses the nonce in the authorize URL, and posts to `/cli/enroll` with that state. It does this only
   for a site whose challenge route answers; for a site that has not switched enrollment on, local login is unchanged.
4. The CLI keeps its session only if this succeeds, and records the Person's id beside the site in
   `~/.config/papyrus/user-session.json` (never a token).

**Sign-in protections the review relies on.** The CLI uses the authorization code flow with PKCE (S256, a fresh
verifier for each login), the Cognito `state` is the broker transaction and its secret part (the CLI never learns the
secret part, and the dot is never sent to Prospectus), and the OpenID nonce is the Prospectus challenge nonce, which
Prospectus compares with the ID token before it resolves.

**Throttle.** `/cli/challenge` is public and central Prospectus has no per-site limit, so the site keeps a token
bucket shared by all callers in a DynamoDB item, updated with a conditional write: 1 request per second with a burst
of 2 by default (the same as Prospectus's own CRM for the same route), configurable with
`PAPYRUS_CLI_CHALLENGE_RATE_PER_SECOND` and `PAPYRUS_CLI_CHALLENGE_BURST`. The reasoning: a challenge is issued once
per login that a person then approves in a browser, so real demand is orders of magnitude below one per second, and the
limit only bounds abuse. An empty bucket answers 429 and a storage failure answers 503; neither reaches Prospectus.

**Failures.** `challenge_invalid`, `login_state`, `challenge_replay` and `reenrollment_required` pass through with
their status; `login_not_enrollable` (403) means the login was made on a client other than the site's registered
federation client; anything else is `unavailable`. The CLI discards the session and says why, and for
`reenrollment_required` it says "Run `papyrus login` again."

**Registration.** The challenge and enroll routes run as the Amplify compute role, which must be the site's
registered `roleArn` in Prospectus; an `executionDelegation` principal is refused on challenge and resolve.
