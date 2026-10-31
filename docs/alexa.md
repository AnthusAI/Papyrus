# Papyrus on Amazon Alexa

The `alexa` plugin gives a site one Alexa custom skill: "Alexa, open `<publication>`" reads the latest published stories.
It is off unless the site lists it (initiative PPY-704ae1; this page describes the contract the later tasks build on).

```ts
export default defineSite({
  backend: {
    plugins: [{ name: "alexa", invocationName: "pilobolus", skillId: "amzn1.ask.skill.<uuid>", accountLinking: false }],
  },
});
```

`invocationName` is required. Optional: `skillName` (default: the invocation name, capitalized), `accountLinking` (default `false`;
linking is optional), `siteOrigin` (the public https origin; the skill manifest needs it unless the four URLs below are set),
`siteId` (default: the invocation name with other characters turned into hyphens; it names the skill's SSM parameters),
`locales` (default `["en-US"]`), `keywords`, `iconSmallUri` / `iconLargeUri` (default `<siteOrigin>/alexa/icon-108.png` and
`icon-512.png`), `privacyPolicyUrl` / `termsOfUseUrl` (default `<siteOrigin>/alexa/privacy` and `/alexa/terms`).
`skillId` is no longer needed: the deploy creates the skill and the function reads the ID from SSM. It stays as an explicit
override (an existing skill you want the site to use).

## What it deploys

- A TypeScript function, `papyrus-alexa-skill`, defined with Amplify `defineFunction` (bundled, so `ask-sdk-core` ships inside).
- A Lambda permission for the principal `alexa-appkit.amazon.com`. See "Deploying the skill" for how it becomes skill-scoped.
  The handler is the second gate: it refuses every request whose skill ID is not the site's, and serves nothing until the
  site has a skill ID (the SSM parameter below, or `skillId` in the config).
- `ssm:GetParameter` on `/papyrus/<site-id>/alexa/skill-id` for the function, which reads it at cold start and caches it. A missing
  parameter fails closed and is re-read at most once a minute.
- The resolved config as `PAPYRUS_ALEXA_SETTINGS` on the function, and in `amplify_outputs.json`: `custom.alexa.functionArn`
  (the skill manifest's endpoint) and `custom.alexa.settings` (the same resolved config, nothing secret, so the deploy sync needs
  no copy of `papyrus.config.ts`).

## Deploying the skill

The skill is created and kept current by the site's own deploy. `papyrus-app alexa-sync` (code: `amplify/plugins/alexa/sync/`,
shipped inside `@anthusai/papyrus`; `scripts/alexa/ask-deploy.ts` runs it by hand) is the line after `ampx pipeline-deploy` in the
generated production build spec (`infra/amplify-app-shell/lib/build-specs.ts`). It needs the function ARN, so it cannot run earlier.
It talks to the Skill Management API (`https://api.amazonalexa.com/v1/skills`) directly, with a Login with Amazon access token. The
ASK CLI is not used.

**Credentials.** One Anthus Amazon developer account serves every site. Its credentials are read at sync time from SSM
SecureString parameters in the site's account and region, created once by hand:

| Parameter | Value |
| --- | --- |
| `/papyrus/alexa/lwa-client-id` | the LWA security profile's client ID |
| `/papyrus/alexa/lwa-client-secret` | its client secret |
| `/papyrus/alexa/lwa-refresh-token` | a refresh token with the `alexa::ask:skills:readwrite` scope |
| `/papyrus/alexa/vendor-id` | the developer account's vendor ID |

When any is absent, the sync logs one line (`alexa-sync: skipped, the Amazon developer credentials are not in SSM ...`) and exits 0.
A site without the plugin logs one line too. A refusal from Amazon is logged as `alexa-sync: failed, ...`; the build spec never lets
that fail the site deploy.

**What it does.**

1. Generates the manifest and one interaction model per locale (`amplify/plugins/alexa/skill-package.ts`, deterministic) and hashes
   them with the account linking request.
2. First sync: `POST /v1/skills`, then stores the skill ID in the plain String parameter `/papyrus/<site-id>/alexa/skill-id`
   (before anything else can fail, so a retry updates the same skill), then uploads each locale's model (Amazon builds the model as
   part of accepting it; the sync waits for the build).
3. Later syncs: compares the hash with `/papyrus/<site-id>/alexa/content-hash`. Equal: no call to Amazon. Different: update the
   manifest and the models, then store the new hash (last, so a failed update is retried by the next deploy).
4. Account linking (only when `accountLinking` is true): `PUT /v1/skills/{id}/stages/development/accountLinkingClient` with type
   `AUTH_CODE`, `authorizationUrl` `<hosted UI>/oauth2/authorize`, `accessTokenUrl` `<hosted UI>/oauth2/token`, the client ID,
   scopes `openid email profile`, `HTTP_BASIC`, and `skipOnEnablement: true` (linking stays optional). The client secret is read
   from the Cognito client with `DescribeUserPoolClient` at sync time; nothing stores it. A rotated secret changes the hash and is
   pushed again.

**Account linking outputs contract.** The Cognito task publishes `custom.alexa.accountLinking = { userPoolId, clientId,
hostedUiDomain }` in `amplify_outputs.json`. `hostedUiDomain` is the hosted UI prefix (`papyrus-pilobol-us-cms`; the host becomes
`<prefix>.auth.<region>.amazoncognito.com`, the region taken from the pool ID) or a full host name (contains a dot). That client must
have a generated secret, and its callback URLs must include the redirect URLs Amazon shows for the skill (Alexa developer console,
Account Linking page); the sync does not edit the Cognito client.

**Lambda permission.** Amazon accepts a Lambda endpoint only once the Alexa trigger exists, and the skill ID exists only after the
skill is created, so the first deploy has to create the trigger without an event-source condition. After creating the skill (and on
every later sync, with no Amazon call), the sync calls the Lambda API: it adds a permission whose condition is the skill ID
(`lambda:EventSourceToken`), then removes every other `alexa-appkit.amazon.com` statement. That heals a CloudFormation redeploy
that puts the unconditional statement back. The alternative, reading the SSM parameter at synth time, needs AWS calls during
synthesis and a second deploy before the function is scoped, so it was not chosen. Between the first deploy and the sync the handler is
the gate, and it serves nothing without a skill ID. The build's service role needs `lambda:GetPolicy`, `AddPermission`,
`RemovePermission`, `cognito-idp:DescribeUserPoolClient` and SSM read/write on `/papyrus/*` (the production Amplify service role has
AdministratorAccess today).

**Not verified against Amazon yet.** The developer account does not exist, so the SMAPI calls (the `Authorization: Bearer` header,
the status resources polled, the `accountLinkingRequest` body) follow the public API reference and are tested only against fakes.
Expect to adjust them on the first real run.

## The seams

Everything a later task needs is a file in its own folder plus at most one line in an index.

| Seam | Contract (all in `amplify/plugins/alexa/contracts.ts`) | Where | A later task adds |
| --- | --- | --- | --- |
| Intents | `IntentModule`: `id`, `create(dependencies) -> RequestHandler`, optional `interactionModel` (intent, slot types) | `intents/index.ts` (`INTENT_MODULES`) | `intents/<name>.ts` and one line in the index. `intents/launch.ts` is a placeholder the intents task replaces. The skill and the generator both read the registry. |
| APL documents | `AplDocument`: `id`, `document` | `apl/index.ts` (`APL_DOCUMENTS`, `aplRenderDirective(id, datasources)`) | `apl/<name>.ts` and one line in the index |
| Public stories | `PublicStorySource`: `listLatest({ limit })`, `getStory(slug)` returning `PublicStorySummary` / `PublicStory` | `content/index.ts` (`createPublicStorySource`) | `content/<impl>.ts`, then change the one return line (today `stubPublicStorySource`, which throws) |
| Access tokens | `AccessTokenVerifier`: `verify(token) -> { ok, token \| reason }` | `auth/index.ts` (`createAccessTokenVerifier`, `undefined` unless `accountLinking`) | `auth/<impl>.ts`, then change the one return line (today refuses every token). `aws-jwt-verify` is already a dependency. |
| Deploy wiring | `AlexaWiringStep(backend, config, context, lambda)` | `wiring/index.ts` (`ALEXA_WIRING_STEPS`) | `wiring/<step>.ts` (for example the Cognito app client) and one line in the index |
| Static files | file keys the projector writes | `static-assets.ts` (`ALEXA_STATIC_ASSETS`) | the privacy pages' paths; `PLUGIN_STATIC_ASSETS["alexa"]` in `src/papyrus_content/projection/plugins.py` must list the same keys |
| Skill package | `generateSkillPackage(config, { endpointArn })` | `amplify/plugins/alexa/skill-package.ts` (the command line is `scripts/alexa/generate-skill-package.ts`) | done: manifest, models, account linking request. `scripts/alexa/ask-deploy.ts` runs the deploy sync by hand |
| Tests | `npm run test:alexa` runs every `scripts/test-alexa-*.ts` and `cucumber-js --profile alexa` (every `features/alexa-*.feature` with its `features/step_definitions/alexa-*.steps.js`) | `package.json`, `cucumber.js`, `.github/workflows/tests.yml` already cover them | new test files only; none of the three shared files changes again |

The tests fail when an intent or APL file exists but is not listed in its index, when ids repeat, or when a document is not APL.
Intent handlers are tried in registry order, so list specific handlers before catch-alls.

## Where the public stories come from

Only what an anonymous visitor can read:

1. The S3 projection under the site origin: every page has a Markus twin (`x.md`, `index.md`), plus the RSS and Atom feeds and
   `llms.txt` (see "Agent-readable pages" in [building a static site](building-a-papyrus-static-site.md)). The twin is the
   story's facts plus its Markus source, verbatim.
2. The guest `PublishedItem` model (`allow.guest().to(["read"])`): `listPublishedItemsByTypeStatusAndPublishedAt` with
   `typeStatus: "article#published"` (tenant-scoped when the site has a tenant), then `publishedItemBySlug`. It carries `headline`,
   `deck`, `byline`, `publishedAt`, `bodyMarkus` and `bodyIr`. `lib/graphql-content-repository.ts` is the existing client.

The skill function has no AppSync credentials; a guest read needs the API's guest (identity pool) mode, so path 1 is the simpler
fit. The content source task chooses.

## Markus to SSML

There is no Markus parser package in `node_modules`. Papyrus parses Markus in Python (`derive_body`) and stores the result as
`bodyIr`. The TypeScript side reads that IR: `lib/markus-ir.ts` (typed nodes: headings, paragraphs, lists, directives, inlines and
`parseMarkusDocument`) and `lib/markus-body.ts` (`projectBodyIr` unwraps the stored envelope, resolves citation tokens and
returns plain paragraphs). `lib/markus-projection.ts` flattens the IR to plain text. For SSML, walk the `MarkusDocument` nodes
from `lib/markus-ir.ts` (the envelope's `document`) instead of the Markus text; when only `bodyMarkus` is available, the source
is the `.md` twin and has no IR, so prefer `bodyIr` (the guest path) or the Python projection for the text. Escape `& < >` and keep
within Alexa's speech limits.
