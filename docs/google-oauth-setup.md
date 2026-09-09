# Google OAuth setup for a Papyrus publication

A Papyrus CMS can let editors sign in with Google. This guide walks through
**creating the Google OAuth client in Google Cloud Console** and wiring it to a
deployed publication. Pilobolus (`newsroom.pilobol.us`) is the worked example.

Related: [`site-hosting.md`](site-hosting.md),
[`publications/pilobol_us/docs/bootstrap.md`](../publications/pilobol_us/docs/bootstrap.md).

## Two different URL lists (read this first)

Google sign-in goes through **Amazon Cognito hosted UI**, not directly to your
CMS domain. That means two separate places need URLs — and they are **not** the
same list.

| Where | Field | What to put there | Pilobolus example |
| --- | --- | --- | --- |
| **Google Cloud Console** | Authorized JavaScript origins | Cognito hosted-UI origin only | `https://papyrus-pilobol-us.auth.us-east-1.amazoncognito.com` |
| **Google Cloud Console** | Authorized redirect URIs | Cognito IdP callback only | `https://papyrus-pilobol-us.auth.us-east-1.amazoncognito.com/oauth2/idpresponse` |
| **Papyrus (CDK branch env)** | `PAPYRUS_OAUTH_REDIRECT_URLS` | Where users land **after** Cognito finishes | `https://newsroom.pilobol.us/`, `http://localhost:3001/`, … |

Do **not** put `https://newsroom.pilobol.us/` in Google's redirect URIs. Google
never redirects there. Cognito sends the user back to your app after Google
authenticates them.

The Cognito domain is predictable when you set `PAPYRUS_COGNITO_DOMAIN_PREFIX`
on the branch (see below). Format:

```text
https://<prefix>.auth.<aws-region>.amazoncognito.com
https://<prefix>.auth.<aws-region>.amazoncognito.com/oauth2/idpresponse
```

## Overview

1. Choose a Cognito domain prefix and set it on the Amplify branch (IaC).
2. Create a Google Cloud project, OAuth consent screen, and Web OAuth client.
3. Store `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Amplify SSM secrets.
4. Remove `PAPYRUS_DISABLE_GOOGLE_OAUTH` and redeploy so Cognito enables Google.
5. Sign in at the CMS and confirm **Continue with Google** appears.

---

## Part A — Google Cloud Console

You need a Google account with permission to create projects and OAuth clients
(typically a Google Workspace admin or a personal `@gmail.com` account).

### A1. Create or select a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project picker at the top (next to "Google Cloud").
3. Click **New Project**.
4. **Project name:** e.g. `Papyrus Pilobolus` (any label you like).
5. Click **Create** and wait for the project to finish creating.
6. Make sure the new project is selected in the project picker.

### A2. Configure the OAuth consent screen

Google requires a consent screen before you can create OAuth credentials.

1. In the left menu go to **APIs & Services → OAuth consent screen**
   (or open [direct link](https://console.cloud.google.com/apis/credentials/consent)).
2. **User Type:**
   - **Internal** — only users in your Google Workspace org can sign in. Use
     this if every editor has an account on your company domain.
   - **External** — anyone with a Google account can attempt sign-in (you can
     restrict later with a test-user list while the app is in "Testing").
3. Click **Create** (External) or continue (Internal).
4. **App information** (required):
   - **App name:** e.g. `Pilobolus Newsroom`
   - **User support email:** your email
   - **Developer contact email:** your email
5. Click **Save and Continue**.
6. **Scopes:** click **Add or Remove Scopes**, add:
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `openid`
   Then **Update** → **Save and Continue**.
7. **Test users** (External apps in Testing only): add the Gmail addresses of
   editors who should sign in during testing. Click **Save and Continue**.
8. Review the summary and click **Back to Dashboard**.

While the app is in **Testing**, only listed test users can complete Google
login. When you are ready for production, return to the consent screen and click
**Publish App**.

### A3. Create the OAuth client (Web application)

1. Go to **APIs & Services → Credentials**
   ([direct link](https://console.cloud.google.com/apis/credentials)).
2. Click **+ Create Credentials** → **OAuth client ID**.
3. **Application type:** **Web application**.
4. **Name:** e.g. `Papyrus Pilobolus CMS`.

5. **Authorized JavaScript origins** — click **+ Add URI** and enter the Cognito
   origin **without** a path:

   ```text
   https://<PAPYRUS_COGNITO_DOMAIN_PREFIX>.auth.us-east-1.amazoncognito.com
   ```

   Pilobolus — use the **live** Cognito domain from your deployed stack (it is
   auto-generated unless `PAPYRUS_COGNITO_DOMAIN_PREFIX` is wired in the
   backend). As of the first Google-enabled deploy:

   ```text
   https://4f95152b62f48bfd084b.auth.us-east-1.amazoncognito.com
   ```

   Look up the current value any time with:

   ```bash
   aws cloudformation describe-stacks \
     --stack-name amplify-d11eu9hbs2mipk-main-branch-3c5f57c311 \
     --region us-east-1 \
     --query 'Stacks[0].Outputs[?OutputKey==`oauthCognitoDomain`].OutputValue' \
     --output text
   ```

6. **Authorized redirect URIs** — click **+ Add URI** and enter the Cognito
   IdP callback path:

   ```text
   https://<PAPYRUS_COGNITO_DOMAIN_PREFIX>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
   ```

   Pilobolus (must match the domain from the command above):

   ```text
   https://4f95152b62f48bfd084b.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
   ```

   > If Google shows *"Invalid Redirect: domain must be added to the authorized
   > domains list"*, go to the OAuth consent screen → **Authorized domains** and
   > add `amazoncognito.com`. Save, then retry adding the redirect URI.

7. Click **Create**.
8. Copy the **Client ID** and **Client secret** from the dialog (or open the
   client later from the Credentials list → edit icon). Store them somewhere
   safe temporarily — you will put them in AWS SSM, not in git.

**Do not add** `https://newsroom.pilobol.us/` or `http://localhost:3001/` to
Google's redirect URIs. Those belong in Papyrus only (next section).

---

## Part B — Papyrus / AWS configuration

### B1. Set branch environment variables (CDK app shell)

Each publication's CMS branch env lives in
`infra/amplify-app-shell/sites/<site>.ts`. Pilobolus:

```typescript
environment: {
  PAPYRUS_COGNITO_DOMAIN_PREFIX: "papyrus-pilobol-us",
  PAPYRUS_OAUTH_REDIRECT_URLS:
    "http://localhost:3001/,https://newsroom.pilobol.us/,https://main.d11eu9hbs2mipk.amplifyapp.com/",
  PAPYRUS_DISABLE_GOOGLE_OAUTH: "1",  // remove this line when ready (step B4)
  // ...
},
```

| Variable | Purpose |
| --- | --- |
| `PAPYRUS_COGNITO_DOMAIN_PREFIX` | Stable Cognito domain for Google redirect URIs (lowercase, unique per region) |
| `PAPYRUS_OAUTH_REDIRECT_URLS` | Comma-separated app URLs Cognito may redirect to after sign-in/sign-out |
| `PAPYRUS_DISABLE_GOOGLE_OAUTH` | Set to `1` to skip Google until secrets exist; remove to enable |

Redeploy the app shell so Amplify picks up env changes:

```bash
cd infra/amplify-app-shell
npm run deploy:pilobol-us
```

`amplify/auth/resource.ts` reads these at backend synth time on the next Amplify
CI build.

### B2. Store Google credentials as Amplify secrets (SSM)

Amplify Gen 2 secrets live in SSM Parameter Store:

```text
/amplify/<appId>/main-branch-<hash>/GOOGLE_CLIENT_ID
/amplify/<appId>/main-branch-<hash>/GOOGLE_CLIENT_SECRET
```

Find `<hash>` from the backend stack name
`amplify-<appId>-main-branch-<hash>` or from the JWT authorizer Lambda's
`AMPLIFY_SSM_ENV_CONFIG` environment variable.

Pilobolus (`appId=d11eu9hbs2mipk`, `hash=3c5f57c311`):

```bash
APP_ID=d11eu9hbs2mipk
HASH=3c5f57c311
PREFIX=/amplify/$APP_ID/main-branch-$HASH

aws ssm put-parameter \
  --name "$PREFIX/GOOGLE_CLIENT_ID" \
  --value "<paste-client-id-from-google>" \
  --type SecureString \
  --region us-east-1 \
  --overwrite

aws ssm put-parameter \
  --name "$PREFIX/GOOGLE_CLIENT_SECRET" \
  --value "<paste-client-secret-from-google>" \
  --type SecureString \
  --region us-east-1 \
  --overwrite
```

Never commit these values to git.

### B3. Confirm the Cognito domain after deploy

After Google OAuth is enabled and a backend deploy completes, verify the domain
matches what you entered in Google:

```bash
aws cloudformation describe-stacks \
  --stack-name amplify-d11eu9hbs2mipk-main-branch-3c5f57c311 \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`oauthCognitoDomain`].OutputValue' \
  --output text
```

Expected for Pilobolus: `papyrus-pilobol-us.auth.us-east-1.amazoncognito.com`

If this is empty, Google OAuth is still disabled or the backend deploy has not
finished. The domain is only created when `externalProviders` is active.

### B4. Enable Google OAuth

1. Remove `PAPYRUS_DISABLE_GOOGLE_OAUTH` (or set it to `0`) in the CDK site
   config.
2. Redeploy the app shell (`npm run deploy:pilobol-us`).
3. Trigger an Amplify backend deploy:

   ```bash
   aws amplify start-job \
     --app-id d11eu9hbs2mipk \
     --branch-name main \
     --job-type RELEASE \
     --region us-east-1
   ```

Wait for the job to succeed before testing.

---

## Part C — Verify

1. Visit `https://newsroom.pilobol.us/` (redirects to `/newsroom`).
2. Click sign in. The Cognito hosted UI should show **Continue with Google**.
3. Complete Google consent. You should land back on the newsroom, signed in.
4. New users still need the `editor` or `admin` Cognito group to use newsroom
   tools (assign via the manage-user-role flow or Cognito console).

### Local development

Include `http://localhost:3001/` in `PAPYRUS_OAUTH_REDIRECT_URLS` (already set
for Pilobolus). Run `npm run dev` with the deployed backend's
`amplify_outputs.json` in the project root. Google redirect URIs stay on the
Cognito domain only — no change needed for localhost in Google Console.

---

## Disabling Google OAuth

Set `PAPYRUS_DISABLE_GOOGLE_OAUTH=1` in the CDK site config, redeploy the app
shell, and run an Amplify RELEASE job. Email/password auth continues to work.
SSM secrets can remain (unused) or be deleted.

---

## Per-publication checklist (Pilobolus)

| Step | Where | Value |
| --- | --- | --- |
| Google Cloud project | console.cloud.google.com | e.g. `Papyrus Pilobolus` |
| OAuth consent screen | Google Console | scopes: email, profile, openid |
| Google JS origin | OAuth client → Authorized JavaScript origins | `https://papyrus-pilobol-us.auth.us-east-1.amazoncognito.com` |
| Google redirect URI | OAuth client → Authorized redirect URIs | `https://papyrus-pilobol-us.auth.us-east-1.amazoncognito.com/oauth2/idpresponse` |
| `PAPYRUS_COGNITO_DOMAIN_PREFIX` | `infra/amplify-app-shell/sites/pilobol-us.ts` | `papyrus-pilobol-us` |
| `PAPYRUS_OAUTH_REDIRECT_URLS` | same | `http://localhost:3001/,https://newsroom.pilobol.us/,https://main.d11eu9hbs2mipk.amplifyapp.com/` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | SSM `/amplify/d11eu9hbs2mipk/main-branch-3c5f57c311/...` | from Google client |
| `PAPYRUS_DISABLE_GOOGLE_OAUTH` | same | remove when secrets are set |
| Deploy | Amplify CI RELEASE on `main` | after removing disable flag |

## Reference — p.apyr.us (shared production)

The shared p.apyr.us stack uses an auto-generated Cognito prefix. Look up the
live domain from stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name amplify-dbsyytcm9drqa-main-branch-cb38ada667 \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`oauthCognitoDomain`].OutputValue' \
  --output text
# → 48215fcaaf4ddb708e9f.auth.us-east-1.amazoncognito.com
```

Use that domain (not the CMS URL) in Google's JavaScript origins and redirect
URI fields for the p.apyr.us Google client.

## Notes

- One Google OAuth client per publication CMS (per domain / user pool).
- `PAPYRUS_OAUTH_REDIRECT_URLS` keeps publication-specific app URLs out of
  `amplify/auth/resource.ts`; p.apyr.us keeps the built-in default list.
- Cognito domain prefixes are **globally unique within an AWS region**. Pick a
  prefix that is unlikely to collide (e.g. `papyrus-<site-id>`).
- Official Amplify reference:
  [External identity providers](https://docs.amplify.aws/react/build-a-backend/auth/concepts/external-identity-providers/).
