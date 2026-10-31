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

`invocationName` is required. `skillName` (default: the invocation name, capitalized), `skillId` (only known after the skill is
created), `accountLinking` (default `false`; linking is optional) and `siteOrigin` (the public https origin) are optional.

`amazonVendorId` is required when `accountLinking` is `true` (uppercase letters and digits). Ryan gets it once from the Alexa developer
console (Settings, Vendor ID) for the Amazon developer account that owns the skills; it names Amazon's account-linking redirect URLs.

## What it deploys

- A TypeScript function, `papyrus-alexa-skill`, defined with Amplify `defineFunction` (bundled, so `ask-sdk-core` ships inside).
- A Lambda permission for the principal `alexa-appkit.amazon.com`, with the skill ID as the event-source condition once
  `skillId` is set. The handler is the second gate: it refuses every request whose skill ID is not the configured one, and
  serves nothing until a skill ID is configured.
- The resolved config as `PAPYRUS_ALEXA_SETTINGS` on the function, and the function ARN as `custom.alexa.functionArn` in
  `amplify_outputs.json` (the skill manifest's endpoint).

## Account linking: the Cognito app client

With `accountLinking: true` the plugin adds one app client, `papyrus-alexa-account-linking`, to the site's own user pool
(`wiring/cognito-client.ts`). Nothing is created when linking is off.

- Authorization code flow only, Google as the only identity provider, scopes `openid email profile`, a generated client secret.
- `ALLOW_REFRESH_TOKEN_AUTH` only (no SRP, password or custom auth), token revocation on, user-existence errors hidden.
- Access and ID tokens last 60 minutes; refresh tokens last 365 days, because Alexa refreshes on its own.
- Callback URLs: `https://pitangui.amazon.com/api/skill/link/<vendorId>`, `https://layla.amazon.com/api/skill/link/<vendorId>` and
  `https://alexa.amazon.co.jp/api/skill/link/<vendorId>`.
- The client depends on the Google identity provider, and the deploy fails if the site has none.
- The secret is stored nowhere. The skill sync reads it with `DescribeUserPoolClient` when it sets up account linking.
- The Lambda gets `PAPYRUS_ALEXA_USER_POOL_ID` and `PAPYRUS_ALEXA_CLIENT_ID`. `amplify_outputs.json` gets
  `custom.alexa.accountLinking = { userPoolId, clientId, hostedUiDomain }` beside `custom.alexa.functionArn`
  (`<domain prefix>.auth.<region>.amazoncognito.com`; Amplify merges `addOutput` calls deeply).
- AppSync: the site's API uses the user pool as its default authorization mode and sets no `appIdClientRegex`, so it accepts
  access and ID tokens from any client of the pool, including this one. This change does not touch AppSync auth.

## The seams

Everything a later task needs is a file in its own folder plus at most one line in an index.

| Seam | Contract (all in `amplify/plugins/alexa/contracts.ts`) | Where | A later task adds |
| --- | --- | --- | --- |
| Intents | `IntentModule`: `id`, `create(dependencies) -> RequestHandler`, optional `interactionModel` (intent, slot types) | `intents/index.ts` (`INTENT_MODULES`) | `intents/<name>.ts` and one line in the index. `intents/launch.ts` is a placeholder the intents task replaces. The skill and the generator both read the registry. |
| APL documents | `AplDocument`: `id`, `document` | `apl/index.ts` (`APL_DOCUMENTS`, `aplRenderDirective(id, datasources)`) | `apl/<name>.ts` and one line in the index |
| Public stories | `PublicStorySource`: `listLatest({ limit })`, `getStory(slug)` returning `PublicStorySummary` / `PublicStory` | `content/index.ts` (`createPublicStorySource`) | `content/<impl>.ts`, then change the one return line (today `stubPublicStorySource`, which throws) |
| Access tokens | `AccessTokenVerifier`: `verify(token) -> { ok, token \| reason }` | `auth/index.ts` (`createAccessTokenVerifier`, `undefined` unless `accountLinking`) | Done: `auth/cognito-access-token-verifier.ts` (reads `PAPYRUS_ALEXA_USER_POOL_ID` and `PAPYRUS_ALEXA_CLIENT_ID`; refuses with "not-configured" without them). Signed-in intents call `linkedUser`, `requireLinkedUser` or `linkAccountResponse` from `auth`. |
| Deploy wiring | `AlexaWiringStep(backend, config, context, lambda)` | `wiring/index.ts` (`ALEXA_WIRING_STEPS`) | `wiring/<step>.ts` (for example the Cognito app client) and one line in the index |
| Static files | file keys the projector writes | `static-assets.ts` (`ALEXA_STATIC_ASSETS`) | the privacy pages' paths; `PLUGIN_STATIC_ASSETS["alexa"]` in `src/papyrus_content/projection/plugins.py` must list the same keys |
| Skill package | `generateSkillPackage(config, { endpointArn })` | `scripts/alexa/generate-skill-package.ts` | the generator task extends it (privacy URLs, APL interfaces, account linking) and adds `scripts/alexa/ask-deploy.ts` |
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
fit. **Chosen: path 1**, `content/public-site-story-source.ts`. `PublishedItem` allows only guest (identity pool) and staff-group callers,
and the site API has no API-key rule on it, so a Lambda role cannot read it without a schema change. The source lists from
`_data/latest.json` (older stories from `_data/search-index.json`) and reads each story's `.md` twin. `content/markus-source.ts` reads the
twin's Markus into the same `MarkusDocument` nodes `bodyIr` holds, and `speech/markus-speech.ts` walks those nodes into SSML units that
`speech/ssml.ts` cuts at a sentence so the output stays under 8000 characters. The intents (launch, `ReadStoryIntent`, next, previous,
repeat, help, stop, cancel, fallback, navigate home, session ended) are in `intents/`; the listener's position lives in session attributes.
A site needs `siteOrigin` set and `publicData.latest` on (the default).

## Markus to SSML

There is no Markus parser package in `node_modules`. Papyrus parses Markus in Python (`derive_body`) and stores the result as
`bodyIr`. The TypeScript side reads that IR: `lib/markus-ir.ts` (typed nodes: headings, paragraphs, lists, directives, inlines and
`parseMarkusDocument`) and `lib/markus-body.ts` (`projectBodyIr` unwraps the stored envelope, resolves citation tokens and
returns plain paragraphs). `lib/markus-projection.ts` flattens the IR to plain text. For SSML, walk the `MarkusDocument` nodes
from `lib/markus-ir.ts` (the envelope's `document`) instead of the Markus text; when only `bodyMarkus` is available, the source
is the `.md` twin and has no IR, so prefer `bodyIr` (the guest path) or the Python projection for the text. Escape `& < >` and keep
within Alexa's speech limits.
