# Google OAuth setup for a Papyrus publication

Google is the standard sign-in for every Papyrus CMS. A site created from the
template always gets the Google provider and a stable Cognito hosted-UI domain;
there is no per-site switch to turn it off. This guide covers the **Google Cloud
Console** side and the two Amplify backend secrets. Pilobolus
(`newsroom.pilobol.us`) is the worked example.

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
| **Papyrus (`infra/site.json`)** | `cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS` | Where users land **after** Cognito finishes | `https://newsroom.pilobol.us/`, `http://localhost:3001/`, … |

List each origin once (`https://newsroom.pilobol.us/` or just the origin). The
backend (`defineSiteAuth`) registers both `<origin>/newsroom` and `<origin>/` as
Cognito callback and logout URLs, newsroom first, and the client signs in with
the first entry for the current origin, so a Google sign-in on a site that owns
`/` (Threat Intelligence, p.apyr.us) returns to the newsroom instead of the
public reader. A CMS-only host (brand `newsroomBasePath: ""`, e.g. Pilobol.us)
gets only `<origin>/`, because `/` already is the newsroom. Nothing changes in
Google: it needs only the Cognito domain URIs.

Do **not** put `https://newsroom.pilobol.us/` in Google's redirect URIs. Google
never redirects there. Cognito sends the user back to your app after Google
authenticates them.

The Cognito domain is predictable only when `cms.applyCognitoDomainPrefix` is
`true` in `infra/site.json` (see "Cognito domain: prefix or generated" below).
Amplify Gen2 otherwise generates a hex domain and ignores the prefix. Format:

```text
https://<prefix>.auth.<aws-region>.amazoncognito.com
https://<prefix>.auth.<aws-region>.amazoncognito.com/oauth2/idpresponse
```

## Overview

1. Set `cms.cognitoDomainPrefix` and `cms.applyCognitoDomainPrefix: true` in `infra/site.json` (IaC; the template puts them on the branches). For an existing site that already has a generated domain, read "Cognito domain: prefix or generated" first.
2. Use a Google OAuth client (an existing one is fine, see "Reusing a client"), and add the new Cognito origin and redirect URI to it.
3. Set the Amplify backend secrets `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on the app.
4. Deploy the stack, then run a backend build so Cognito gets the domain and the Google provider.
5. Sign in at the CMS and confirm **Continue with Google** appears.

### Reusing a client

One Google OAuth client can serve several CMS user pools. The client does not
change between sites: only its two lists in Google Cloud Console grow. For each
new site, **add** its Cognito origin (Authorized JavaScript origins) and its
`/oauth2/idpresponse` URI (Authorized redirect URIs) to the existing client, and
paste the same Client ID and secret into the new app's Amplify secrets. Create a
new client only when you want a separate consent screen.

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

### A3. Create the OAuth client (Web application), or edit the existing one

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

   The prefix is `cms.cognitoDomainPrefix` from `infra/site.json` when
   `cms.applyCognitoDomainPrefix` is `true`; otherwise use the generated domain.
   Pilobolus (new CMS, app `dv0pdx67fk80m`, still on the generated domain):

   ```text
   https://69a74c507e157f784c3c.auth.us-east-1.amazoncognito.com
   ```

   After a backend deploy, confirm the live value with the stack output
   `oauthCognitoDomain` (see B3).

6. **Authorized redirect URIs** — click **+ Add URI** and enter the Cognito
   IdP callback path:

   ```text
   https://<PAPYRUS_COGNITO_DOMAIN_PREFIX>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
   ```

   Pilobolus (new CMS):

   ```text
   https://69a74c507e157f784c3c.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
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

### B1. Cognito domain and redirect URLs (`infra/site.json`)

Everything about the hosted UI lives in the site's `infra/site.json`. Nothing is
edited in the Amplify console.

```json
"cms": {
  "cognitoDomainPrefix": "papyrus-pilobol-us-cms",
  "environment": {
    "PAPYRUS_OAUTH_REDIRECT_URLS": "http://localhost:3001/,https://newsroom.pilobol.us/,https://staging.pilobol.us/"
  }
}
```

| Field | Purpose |
| --- | --- |
| `cms.cognitoDomainPrefix` | Required. The Cognito domain you want (lowercase letters, digits, hyphens; unique per region; must not contain `aws`, `amazon` or `cognito`). The template sets `PAPYRUS_COGNITO_DOMAIN_PREFIX` on the CMS branches. It takes effect only with `applyCognitoDomainPrefix` |
| `cms.applyCognitoDomainPrefix` | Optional, default off. When `true` the backend uses `cognitoDomainPrefix` as the user pool domain (template sets `PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX=true`). Without it Amplify's generated domain is kept |
| `cms.environment.PAPYRUS_OAUTH_REDIRECT_URLS` | Comma-separated app URLs Cognito may redirect to after sign-in/sign-out. Without a custom domain the template appends the app's default `amplifyapp.com` URLs |

`PAPYRUS_DISABLE_GOOGLE_OAUTH`, `PAPYRUS_COGNITO_DOMAIN_PREFIX` and
`PAPYRUS_APPLY_COGNITO_DOMAIN_PREFIX` are rejected inside `cms.environment`:
Google is always on and the prefix has its own fields.

### Cognito domain: prefix or generated

Amplify Gen2's auth factory overwrites the `domainPrefix` passed to `defineAuth`
with a hash of the backend id (a 20-character hex name, for example Pilobol.us's
`69a74c507e157f784c3c`). Papyrus therefore sets the user pool domain itself, and
only when `cms.applyCognitoDomainPrefix` is `true`.

- **New site:** set both fields before the first backend deploy. The domain is
  the prefix, so the Google origin and redirect URI are known up front.
- **Existing site on the generated domain:** leave `applyCognitoDomainPrefix`
  unset. Nothing changes on the next deploy, and the real domain is read with
  `aws cognito-idp describe-user-pool --user-pool-id <id> --query UserPool.Domain`
  or the stack output `oauthCognitoDomain`.
- **Switching an existing site to the prefix:** Cognito cannot rename a pool
  domain in place. CloudFormation replaces `AWS::Cognito::UserPoolDomain`: it
  creates the prefix domain, then deletes the generated one. The pool, users and
  groups are kept, but the hosted-UI URL changes, so sign-in with Google fails
  until you (1) add the new origin and `/oauth2/idpresponse` redirect URI to the
  Google OAuth client before deploying (the old ones may stay until after), (2)
  set `applyCognitoDomainPrefix: true`, deploy the stack, and run a backend
  build, and (3) remove the old Google URIs. A prefix already taken in the
  region by another pool makes the deploy fail and roll back.

Deploy the stack so Amplify gets the branch variables:

```bash
cd infra/amplify-app-shell
SITE=<path to the site's infra/site.json> npm run deploy
```

`amplify/auth/resource.ts` reads the variables at backend synth time on the next
Amplify build.

### B2. Store Google credentials as Amplify secrets (SSM)

The two secrets are `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. They must be
Amplify backend secrets, because the backend reads them with `secret(...)` at
build time. Without them the backend build fails.

Console path (per app, one time): AWS Amplify, the app, **Hosting**, **Secrets**,
**Manage secrets**, add both names for branch `main` (or all branches), save,
then run a new build. The values come from the Google OAuth client; they never
go into git, `site.json` or branch environment variables.

Under the hood they are SSM SecureStrings:

```text
/amplify/<appId>/<branch>/GOOGLE_CLIENT_ID
/amplify/<appId>/<branch>/GOOGLE_CLIENT_SECRET
```

Shell alternative for an app whose backend stack already exists (Pilobolus' old
CMS, `appId=d11eu9hbs2mipk`, `hash=3c5f57c311`; the path uses the stack hash):

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

Actual for the new Pilobolus CMS (generated, prefix not applied): `69a74c507e157f784c3c.auth.us-east-1.amazoncognito.com`

If this is empty, the backend deploy has not finished, or the branch lost its
environment variables (see "Verify and repair after connecting" in
[`site-hosting.md`](site-hosting.md)); the domain is only created when the
provider is configured.

### B4. Build

After the stack deploy (B1) and the secrets (B2), start a backend build so the
Cognito domain and the Google provider are created:

```bash
aws amplify start-job \
  --app-id <cms app id> \
  --branch-name main \
  --job-type RELEASE \
  --region us-east-1
```

Wait for the job to succeed before testing.

---

## Part C — Verify

1. Visit the CMS origin, for example `https://newsroom.pilobol.us/` (redirects to `/newsroom`).
2. Click sign in. The Cognito hosted UI should show **Continue with Google**.
3. Complete Google consent. You should land back on the newsroom, signed in.
4. New users still need the `editor` or `admin` Cognito group to use newsroom
   tools (assign via the manage-user-role flow or Cognito console).

### Local development

Include `http://localhost:3001/` in `PAPYRUS_OAUTH_REDIRECT_URLS` (required by
`site.json` validation). Run `npm run dev` with the deployed backend's
`amplify_outputs.json` in the project root. Google redirect URIs stay on the
Cognito domain only — no change needed for localhost in Google Console.

---

## Sandboxes only: skipping Google

Google is not optional for a deployed publication. A personal Amplify sandbox
without Google credentials may export `PAPYRUS_DISABLE_GOOGLE_OAUTH=1` before
`ampx sandbox` (see [`aws-sandbox-personal.md`](aws-sandbox-personal.md)). The
site template rejects that variable in `infra/site.json`. Without Google the
hosted-UI domain is not created either, so the CMS login button cannot work.

## Per-publication checklist (Pilobolus)

| Step | Where | Value |
| --- | --- | --- |
| Google Cloud project | console.cloud.google.com | e.g. `Papyrus Pilobolus` |
| OAuth consent screen | Google Console | scopes: email, profile, openid |
| Google JS origin | OAuth client → Authorized JavaScript origins | `https://papyrus-pilobol-us.auth.us-east-1.amazoncognito.com` |
| Google redirect URI | OAuth client → Authorized redirect URIs | `https://papyrus-pilobol-us.auth.us-east-1.amazoncognito.com/oauth2/idpresponse` |
| `cms.cognitoDomainPrefix` (with `applyCognitoDomainPrefix`) | `infra/site.json` | `papyrus-pilobol-us-cms` (not applied; live domain is `69a74c507e157f784c3c`) |
| `PAPYRUS_OAUTH_REDIRECT_URLS` | `infra/site.json` (`cms.environment`) | `http://localhost:3001/,https://newsroom.pilobol.us/,https://staging.pilobol.us/` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Amplify console, **Hosting**, **Secrets** (app, branch `main`) | from the Google client |
| Deploy | stack deploy, then Amplify RELEASE on `main` | after the secrets are set |

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

- A Google OAuth client can be shared across publications: add each user pool's Cognito origin and `/oauth2/idpresponse` URI to it.
- `PAPYRUS_OAUTH_REDIRECT_URLS` keeps publication-specific app URLs out of
  `amplify/auth/resource.ts`; p.apyr.us keeps the built-in default list.
- Cognito domain prefixes are **globally unique within an AWS region**. Pick a
  prefix that is unlikely to collide (e.g. `papyrus-<site-id>`).
- Official Amplify reference:
  [External identity providers](https://docs.amplify.aws/react/build-a-backend/auth/concepts/external-identity-providers/).
