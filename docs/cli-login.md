# Native newsroom CLI login

`papyrus login` opens normal Google sign-in through a **reviewed public
Cognito app client**, then stores the renewable session in macOS Keychain.
Editorial requests use the same Cognito user-pool authorization as the newsroom;
AppSync remains responsible for validating the token and enforcing permissions.
This does not grant an operator role or require personal AWS SSO.

This implementation is reviewable code, not activated provider configuration.
The existing Prospectus server client has 60-minute access/ID/refresh validity
and discards refresh tokens. Do not silently reuse it for an unattended CLI
session or extend browser sessions as part of setup.

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

Save reviewed **public metadata** as `.papyrus/cli-auth.json` in the selected
publication, or point `PAPYRUS_CLI_AUTH_CONFIG` at it:

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
mismatches before sending any token. It does not infer a native client from a
web client or guess a tenant when data is absent.

## Commands

From the configured publication checkout:

```sh
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

The active public selection is stored in a private metadata directory
(`~/.config/papyrus` by default, override `PAPYRUS_CLI_STATE_DIR`). Renewable
secrets and subject/label records live in macOS Keychain, scoped by the complete
issuer/client/publication/endpoint/callback binding. Short-lived ID tokens are
in process memory only. There are no token argv, environment variables, repo
files or plaintext fallback. Child CLI/Tactus processes use the same public
selection and read their own renewable secret from the OS store.

macOS support uses Apple's Security/CoreFoundation framework through Python's
standard-library FFI, without new dependency installation. Locked/unavailable
Keychain fails with a useful error and does not trigger a surprise unlock
prompt. Other desktop secure-store backends are not implemented in this first
slice; unsupported hosts fail closed. Python interface tests use synthetic
store/provider fixtures, never production credentials.

Rotation reads and replaces the latest secret under a process-shared file lock;
lock files contain no token data. Transient provider/network failures retain the
session. Confirmed `invalid_grant` removes the unusable secret and requests an
explicit login. No noninteractive command opens a browser or changes identity.
User-authenticated API requests are not replayed after uncertain delivery.

`logout` always attempts local deletion, attempts provider refresh-session
revocation and reports whether remote revocation was confirmed. It does not
claim global signout or immediate invalidation of every previously issued JWT.
If local secure-store deletion fails, logout returns an error. Public selection
metadata remains as a signed-out binding so a subsequent command cannot
silently fall back to a broader IAM identity. A different publication requires
its own explicit `login --config ...`; no credential is reused across bindings.

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
run. Only Apple framework symbol resolution was checked on M1; complete
credential-free tests and CI remain the review gate for this PR.

Reference implementation: [Apricity cloud CLI](https://github.com/AnthusAI/Apricity/blob/ffe8a023b0418445aa67893a52ae9e173c366d42/crates/apricity-cli/src/cloud.rs#L206).
OAuth uses the native-app pattern in [RFC8252](https://www.rfc-editor.org/info/rfc8252/).
Provider details: [refresh tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-refresh-token.html)
and [revocation](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html).

CLI login is separate from research execution: this PR does not replace the
hosted empty seeded packet, run a console-agent exchange, or prove execution of
a registered Tactus procedure.
