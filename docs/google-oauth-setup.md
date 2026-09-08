# Google OAuth setup for a Papyrus publication

A Papyrus publication can let editors sign in with Google instead of (or in
addition to) email/password. This doc is the general, repeatable setup for
**any** publication's CMS app. Pilobolus (`newsroom.pilobol.us`) is the
worked example.

Kanbus: PPY-43704a. Related: [`site-hosting.md`](site-hosting.md),
[`site-workspace.md`](site-workspace.md),
[`../publications/pilobol_us/docs/bootstrap.md`](../publications/pilobol_us/docs/bootstrap.md).

## How Papyrus wires Google OAuth

Google OAuth is configured in [`amplify/auth/resource.ts`](../amplify/auth/resource.ts):

- `secret("GOOGLE_CLIENT_ID")` / `secret("GOOGLE_CLIENT_SECRET")` — the
  OAuth client credentials, stored as Amplify secrets in SSM (never in git).
- `authRedirectUrls` — the OAuth callback / logout URLs. Sourced from the
  `PAPYRUS_OAUTH_REDIRECT_URLS` branch env var (comma-separated), defaulting
  to the p.apyr.us URLs when unset.
- `PAPYRUS_DISABLE_GOOGLE_OAUTH=1` — omit Google OAuth entirely (used when a
  publication has no Google client yet). Default is **enabled**; a new
  publication starts with the flag set to `1` and removes it once configured.

So enabling Google login for a publication is three steps: create a Google
OAuth client, set the two secrets in SSM, and remove the disable flag (and
set the redirect URLs if not using the default).

## Prerequisites

- A deployed Papyrus CMS app (see [`site-workspace.md`](site-workspace.md) and
  the publication's `docs/bootstrap.md`).
- The app's `appId`, the backend stack name (for the SSM secret path), and
  the branch env configured via the CDK app-shell stack
  (`infra/amplify-app-shell`).
- Access to Google Cloud Console to create an OAuth client.

## Step 1 — Create the Google OAuth client

1. Open [Google Cloud Console](https://console.cloud.google.com/) →
   **APIs & Services → Credentials**.
2. Ensure an OAuth consent screen exists for the project (External or
   Internal; add the scopes `email`, `profile`, `openid`).
3. **Create Credentials → OAuth client ID → Web application**.
4. Under **Authorized redirect URIs**, add every URL the publication's CMS
   can be reached at. For each URL add both the bare path and the OAuth
   callback path that Amplify uses. Amplify's Cognito hosted UI redirects
   back to the app origin, so list the origins:

   ```
   https://<cms-domain>/
   https://<appId>.amplifyapp.com/
   http://localhost:3001/      (for local dev against this backend)
   ```

   For Pilobolus:
   ```
   https://newsroom.pilobol.us/
   https://main.d11eu9hbs2mipk.amplifyapp.com/
   http://localhost:3001/
   ```

5. Copy the **Client ID** and **Client Secret**.

## Step 2 — Set the redirect URLs on the branch (IaC)

The CDK app-shell site config owns the branch env. Set
`PAPYRUS_OAUTH_REDIRECT_URLS` to the same comma-separated list you authorized
in Google. Example for Pilobolus in
`infra/amplify-app-shell/sites/pilobol-us.ts`:

```typescript
PAPYRUS_OAUTH_REDIRECT_URLS:
  "http://localhost:3001/,https://newsroom.pilobol.us/,https://main.d11eu9hbs2mipk.amplifyapp.com/",
```

Redeploy the app shell so the branch picks up the env:

```bash
cd infra/amplify-app-shell
npm run deploy:pilobol-us
```

This env is read at backend synth time, so the next Amplify CI build uses the
new URLs. (It is harmless to set this while Google OAuth is still disabled —
the URLs are only consumed when Google OAuth is enabled.)

## Step 3 — Store the client credentials as Amplify secrets

Amplify Gen 2 secrets live in SSM at
`/amplify/<appId>/<branch>-branch-<hash>/<SECRET_NAME>`. Find the exact path
from the deployed JWT authorizer Lambda's `AMPLIFY_SSM_ENV_CONFIG` env, or
derive it from the backend stack name `amplify-<appId>-<branch>-branch-<hash>`.

For Pilobolus (`d11eu9hbs2mipk`, branch `main`, hash `3c5f57c311`):

```bash
APP_ID=d11eu9hbs2mipk
HASH=3c5f57c311
PATH=/amplify/$APP_ID/main-branch-$HASH

aws ssm put-parameter \
  --name "$PATH/GOOGLE_CLIENT_ID" \
  --value "<google-client-id>" \
  --type SecureString \
  --region us-east-1

aws ssm put-parameter \
  --name "$PATH/GOOGLE_CLIENT_SECRET" \
  --value "<google-client-secret>" \
  --type SecureString \
  --region us-east-1
```

These are the values Amplify reads at runtime; they are never committed to git.

## Step 4 — Enable Google OAuth on the branch

Remove `PAPYRUS_DISABLE_GOOGLE_OAUTH` from the CDK site config (or set it to
`0`) and redeploy the app shell:

```typescript
// infra/amplify-app-shell/sites/pilobol-us.ts
environment: {
  // PAPYRUS_DISABLE_GOOGLE_OAUTH: "1",   // remove this line
  ...
},
```

```bash
cd infra/amplify-app-shell
npm run deploy:pilobol-us
```

Then push anything to `main` (or start a release job) so Amplify CI runs a
backend deploy with Google OAuth included:

```bash
aws amplify start-job --app-id d11eu9hbs2mipk --branch-name main --job-type RELEASE
```

## Step 5 — Verify

1. Visit `https://<cms-domain>/` (redirects to `/newsroom` for a CMS-only
   deployment).
2. Sign in → the Cognito hosted UI should now offer **Continue with Google**.
3. After consent, you land back on the newsroom authenticated as an editor
   (add the user to the `editor`/`admin` group via the manage-user-role flow or
   Cognito to grant newsroom access).

## Local development

For local dev against a deployed backend, list `http://localhost:3001/` in
the Google authorized redirect URIs and in `PAPYRUS_OAUTH_REDIRECT_URLS`, then
run `npm run dev` with the backend's `amplify_outputs.json` present.

## Disabling Google OAuth

Set `PAPYRUS_DISABLE_GOOGLE_OAUTH=1` on the branch (via the CDK site config)
and redeploy. The auth resource omits the `externalProviders` block entirely;
the secrets can stay in SSM (unused) or be deleted.

## Per-publication checklist

| Step | Where | Pilobolus value |
| --- | --- | --- |
| Google OAuth client | Google Cloud Console | *create per publication* |
| Redirect URIs authorized | Google client config | `https://newsroom.pilobol.us/`, `https://main.d11eu9hbs2mipk.amplifyapp.com/`, `http://localhost:3001/` |
| `PAPYRUS_OAUTH_REDIRECT_URLS` | CDK site config (branch env) | same list, comma-separated |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | SSM `/amplify/<appId>/main-branch-<hash>/...` | *from Google client* |
| `PAPYRUS_DISABLE_GOOGLE_OAUTH` | CDK site config | remove (or set `0`) |
| Deploy | Amplify CI build of `main` | auto-build on push |

## Notes

- The OAuth client is per **publication** (per domain), not per Papyrus app.
  Each publication creates its own Google client with its own redirect URIs.
- The `PAPYRUS_OAUTH_REDIRECT_URLS` env keeps `amplify/auth/resource.ts`
  free of any publication-specific hard-coding; p.apyr.us keeps the default
  (no env set), every other publication sets its own list.
- If a publication never wants Google login, leave
  `PAPYRUS_DISABLE_GOOGLE_OAUTH=1`; email/password auth still works.
