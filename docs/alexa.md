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
`icon-512.png`), `privacyPolicyUrl` / `termsOfUseUrl` (default `<siteOrigin>/alexa/privacy/` and `/alexa/terms/`).
`skillId` is no longer needed: the deploy creates the skill and the function reads the ID from SSM. It stays as an explicit
override (an existing skill you want the site to use).

`amazonVendorId` is required when `accountLinking` is `true` (uppercase letters and digits). Ryan gets it once from the Alexa developer
console (Settings, Vendor ID) for the Amazon developer account that owns the skills; it names Amazon's account-linking redirect URLs.

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
| Static files | file keys the projector copies | `static-assets.ts` (`ALEXA_STATIC_ASSETS`) | nothing today (the lists are empty and must stay equal to `PLUGIN_STATIC_ASSETS["alexa"]` in `src/papyrus_content/projection/plugins.py`). The privacy and terms pages are rendered pages, not copied files: see below. |
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

## On-screen documents (APL)

`apl/feed.ts` and `apl/story.ts` are APL 2023.3 documents for Echo Shows and Fire TV. They import `alexa-viewport-profiles` and choose
their sizes with `when` conditions for `hubRoundSmall`, `hubLandscapeSmall`, `hubLandscapeMedium`, `hubLandscapeLarge` and
`tvLandscapeXLarge`. Colours are datasource values, never baked in: `theme` in the plugin settings (`background`, `surface`, `text`,
`mutedText`, `accent`, each `#rrggbb`, text at least 4.5:1 against both grounds) or, when absent, the Pilobolus dark palette. There are
no borders or hairlines; cards are flat fills with rounded corners.

The functions the intents call (all pure, in `apl/support/`):

- `supportsApl(requestEnvelope)` (`device.ts`): is `Alexa.Presentation.APL` in `context.System.device.supportedInterfaces`.
- `feedDirective(stories, theme, publication)` and `storyDirective(story, bodyParagraphs, theme)` (`directives.ts`): the
  `RenderDocument` directive with datasources. Stories may carry an optional `imageUrl`.
- `themeFromConfig(config)`, `themeFromTokens(tokens, mode)` and `DEFAULT_APL_THEME` (`theme.ts`).

The conversation (`speech/conversation.ts`) sends the screens: `readHeadlines` adds the feed and `readStory` adds the story, whose
paragraphs come from `storyParagraphs` (the same Markus nodes the speech reads, as plain text). Both check `supportsApl` first, so a
voice-only device gets speech alone. A touched feed card sends a UserEvent with `["openStory", <index>]`; `intents/apl-user-event.ts`
calls `openStoryAt(handlerInput, index, dependencies)`, which reads that story exactly as a spoken request would (an index past the
list reads the headlines again). Tests inject another opener with `createAplUserEventIntent({ openStory })`.

`npx tsx scripts/alexa/render-apl-previews.ts` writes `docs/alexa-apl-previews/<feed|story>-<profile>.json`: the document, a sample
datasource and the profile's nominal viewport, for the APL authoring tool. The tests fail when they are out of date.

## Privacy and terms pages

A site that enables the plugin serves `/alexa/privacy/` and `/alexa/terms/` (the skill manifest links to them). The projector renders them
with the site's normal header, theme and footer, in the directory form whatever `urls.style` says, like the newsletter pages
(`src/papyrus_content/projection/standard/alexa_pages.py`). The publication name comes from the site identity. The contact line links
`footer.family.contactUrl` when the site sets it and otherwise points at the footer's Contact link; no address is committed.
`PLUGIN_PAGE_PREFIXES["alexa"]` keeps a reconcile from deleting them.

## Reviewing references

The MVP Ryan set on 2026-10-31: a linked editor reviews the newsroom's unrated References one at a time by voice. Alexa reads the
title, where it is from, the subtitle and the summary; the Echo Show shows the reference card (`apl/reference.ts`) with Accept,
Reject and Skip buttons; the editor says accept, or reject and why, or skip; the answer is recorded and the next one follows.

**Two lists.** *Best bets*: unrated References by the Cyclotron's P(accept), highest first, the newsroom's Best bets sort. *Needs my
help*: by uncertainty `1 - |2P - 1|`, the newsroom's "What needs me" rule. Both share the newsroom's own functions
(`lib/reference-feed-ranking.ts`, `lib/needs-me-ranking.ts`), compiled into the package with `lib/reference-policy.ts`,
`lib/newsroom-references.ts` and `lib/relevance-decisions.ts` (`packages/papyrus/scripts/stage.mjs`). Without a named list the
review starts with what needs help.

**The editor's own sign-in.** `review/newsroom.ts` calls the site's AppSync API with the linked editor's Cognito access token (the
`Authorization` header), never with the skill's role, so AppSync checks the `editor`/`admin` groups and `reviewReferenceCuration`
records `curationActorKind: human`, which trains the Cyclotron. This is the one exception to IAM-only Lambdas
(`docs/agent-rules-detail.md`). The plugin wiring sets `PAPYRUS_ALEXA_GRAPHQL_ENDPOINT` (and `PAPYRUS_ALEXA_HOSTED_UI_ORIGIN`, for
the editor's email from `/oauth2/userInfo`, which becomes the vote's `actorLabel`); there is no IAM grant.

**Data paths.**

| What | Where |
| --- | --- |
| The queue | `listReferencesByFeedStateAndPrediction(feedStateKey: "<corpusId>#unrated", DESC)`; the corpus is `knowledge-corpus-<corpusKey or siteId>` (`corpusKey` setting). Needs the feed keys backfilled (`docs/reference-feed-indexes.md`). Up to 300 are ordered; a session carries 25 and counts them all. |
| Subtitle | The preview `ReferenceAttachment`'s `metadata.description`, and its `siteName` for "From ..." and for trimming the title. |
| Summary | The curation card's `summary.text`, else the summarizer's `metadata` ModelAttachment through `createModelAttachmentDownload`. |
| Decision | The current `relevance_decision_is` relation (`currentRelevanceDecisions`): its id goes with the vote; its confidence and review reason answer "why this one". |
| Vote | `reviewReferenceCuration(referenceId, action, note, reasonCode, decisionRelationId, actorLabel)`. A reject needs a reason: the spoken words are the `note` and `rejectionReasonCodeForWrittenReason` gives the code. Undo is `reopen`. |

**Who may review.** Not linked: a LinkAccount card (an Echo Show shows Amazon's QR code). Linked without `editor`/`admin`: told review
is for editors and offered the stories. A refused token (AppSync 401/403 or "Not Authorized") asks the editor to link again; a failed
write says nothing was recorded.

### Conversation design

Voice starts from a low point: the editor cannot see a menu, mishearing is normal, and silence is confusing. The rules:

- **Always say where they are.** Every Reference starts "Number 3 of 12"; the card says the list and the place.
- **Short once learned.** The first prompt explains ("Say accept, or reject and why, like reject because it's off topic. Or say
  skip."); after that it is "Accept, reject, or skip?". Confirmations are one word ("Accepted.") before the next Reference.
- **No dead ends.** A misheard answer during a review gets the short choices, never the headlines; review words outside a review
  say how to start one; an empty list says nothing is waiting; the end of a list offers the other one.
- **A rejection always has a reason**, in the editor's words. A bare "reject" asks why; "because ..." answers. A stray "because ..."
  checks first.
- **Shared words mean review things during a review.** Next is skip; previous, repeat, help, more, stop and cancel act on the
  Reference; "headlines" leaves the review for the stories.

What editors will say, and what happens:

| They say | The skill |
| --- | --- |
| "what needs my help", "best bets", "review references", "show me references" | Starts that list (needs my help if unnamed) |
| "accept", "keep it", "yes", "thumbs up" | Accepts, then the next one |
| "reject because it's a press release", "no it's off topic", "reject" | Rejects with the reason (asks why if none) |
| "skip", "not sure", "come back to it", "next" | Moves on, nothing recorded |
| "undo", "I changed my mind", "oops" | Reopens the last answer and reads that one again |
| "how many are left", "where am I" | The count, counting this one |
| "why this one", "how sure are you" | The Cyclotron's guess in percent, and whether it asked for help or is auditing |
| "who published it", "when was it published" | Source name and date |
| "more", "read the whole summary" | Everything there is, as much as one reply can say |
| "send it to my phone", "give me the link" | An Alexa app card with the title, subtitle and link |
| "accept all", "reject them all" | Refused kindly: one at a time |
| "repeat", "go back" | The same Reference again, or the previous one |
| "that's enough", "pause", "stop" | Stops; says unanswered ones will still be waiting |
| "help" | Where they are and every option |

Tests: `scripts/test-alexa-review.ts` runs whole conversations against a fake newsroom (`features/alexa-review.feature`). The misses
Ryan finds on a real Echo Show become new rows here and new tests.

