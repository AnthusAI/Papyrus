# Plugins

A plugin is a deploy-time extension of a Papyrus site. It can add models and
operations to the site's GraphQL API, a panel to the newsroom, and a web
component to the static pages. It was extracted from one real plugin, `signup`;
there is no registry, no hot-plugging and no second plugin yet.

## What a plugin is

A plugin is code in the Papyrus package, pinned by the Papyrus version a site
installs. Papyrus knows its plugins by name (`amplify/plugins/registry.ts`).
Each plugin lives in `amplify/plugins/<name>/` and ships a manifest,
`papyrus.plugin.ts`:

| Field | Meaning |
|---|---|
| `name`, `contract` | The plugin name and its public contract version (a whole number). |
| `models`, `mutations` | What it adds to the schema. A test pins the schema to these lists. |
| `guest.mutations` | The only operations an anonymous visitor may call. Everything else stays closed to guests. |
| `newsroomPanels` | Panels it adds to the newsroom (`id`, `label`). |
| `staticAssets` | Files the projector writes into the site bucket, such as `_plugins/papyrus-signup@1.js`. |

Beside the manifest the plugin supplies four functions: `resolveConfig` (validate
the site's settings), `schemaDefinitions` (models and operations), `functions`
(Amplify functions) and `wire` (everything that needs the backend to exist: IAM,
environment, a web ACL). `publicSettings` returns the non-secret settings the
newsroom and the page component may read.

## Enabling it

One switch, in the site's `papyrus.config.ts`:

```ts
export default defineSite({
  // ...
  backend: {
    plugins: ["signup"],                       // defaults: forms ["newsletter"], 20 requests a minute, web ACL on
    // plugins: [{ name: "signup", forms: ["news", "events"], addressLimitPerMinute: 30, waf: true }],
  },
});
```

Nothing else changes. Not `infra/site.json`, not `projection.json`:

- The backend reads the list when it synthesizes (`defineSiteBackend`), merges the
  plugins' schema definitions into the site schema, adds their functions, runs
  their `wire`, sets `PAPYRUS_PLUGINS=signup` on the content-actions function (the
  projector then writes the static assets) and publishes the plugins' public
  settings in `amplify_outputs.json` under `custom.papyrusPlugins.<name>`.
- The newsroom shows a plugin's panel only when `custom.papyrusPlugins.<name>` is
  present in the outputs it was built with. A site that lists no plugin has no
  such key and no panel.
- A site with its own projector calls `plugin_static_files(names)` from
  `papyrus_content.projection.plugins` with the same names.

A site that lists no plugin synthesizes the same CloudFormation it did before
plugins existed (see "Existing sites" below).

## What deploying a plugin costs

- **Schema is code.** Amplify Gen 2 builds the schema at synth time, so enabling or
  removing a plugin is a backend deploy. There is no runtime change. Removing a
  plugin removes its model's table; take an export first.
- **Resolvers.** Each model adds a nested stack with its AppSync resolvers (get, list,
  one per secondary index, delete where allowed), and each custom operation adds
  one. `SignupEntry` adds 6 (get, list, create, update, delete, the index query) and `submitSignup` one. The model stacks are chained in waves
  (`amplify/resolver-waves.ts`, `resolverWaveSize`, default 12) so a deploy does not hit
  AppSync's CreateResolver rate limit; a plugin's model is placed in the waves like any
  other model. The first deploy that adds a plugin is a normal backend deploy.
- **Amplify constraint.** Amplify Gen 2 functions must be defined at module level and
  referenced from the schema; `defineSiteBackend` therefore builds the plugin list
  before `defineBackend` and passes the functions in conditionally.

## Versioning

A plugin is a pinned package version, not a separately installed thing. Its public
contract is: the mutation names and inputs, the model fields, the element name and
its attributes, and the static file name (`papyrus-signup@1.js`). When any of those
changes incompatibly: bump `contract` in the manifest, change the static file's
version suffix (`@2`) and say so in the release notes. Old pages keep working
against the old file until they are reprojected. There are no compatibility shims:
the new contract replaces the old one.

## Walk-through: the `signup` plugin

**Data.** `SignupEntry` (`form`, `value`, `submittedAt`). Nobody can create it
through the model. Editors and admins read it, admins delete it. Guests have no
rule on it at all, and a test fails if a guest, API key or custom rule appears.
The entry id is a hash of the form and the lower-cased address, so a repeated
submission is the same entry and changes nothing.

**The one guest operation.** `submitSignup(form, value, renderedAt, website)` returns
`{ status, message }` where status is `accepted`, `invalid`, `expired` or
`throttled`. Its Lambda (`function/handler.py`, Python, no dependencies beyond the
runtime) does these things in order:

1. Counts the request against the caller's address and identity (DynamoDB counters
   with a TTL) and returns `throttled` past 20 a minute per address or 5 a minute
   per identity.
2. Rejects non-text arguments, arguments over 1000 characters, forms not in the
   site's list, and values that are not a plain email address (at most 254
   characters, no spaces, no leading `=`, `+`, `-`, `@`).
3. Rejects a form render timestamp that is not a number, and answers `expired` for one
   older than a day.
4. Answers `accepted` without storing anything when the hidden field is filled or the
   form was submitted less than two seconds after it rendered.
5. Writes the entry through `createSignupEntry`, signed with the function's own role.

**Throttling.** Two layers. The function's counters are exact. A regional AWS WAF web
ACL on the API, with one rate-based rule (`waf: true`, the default), blocks an address
that sends more than the limit of `submitSignup` requests in a minute before the
function runs; only requests whose body names the mutation count, so reads, newsroom
saves and CLI imports from the same address are never limited. The web ACL costs about
6 USD a month plus 0.60 USD per million requests to the API; `waf: false` leaves the
function's counters alone.

**IAM.** The function may `dynamodb:UpdateItem` its own counter table and
`appsync:GraphQL` on the single field `Mutation.createSignupEntry`.

**Front end.** One file, `/_plugins/papyrus-signup@1.js`, no dependencies:

```html
<script src="/_plugins/papyrus-signup@1.js" defer></script>
<papyrus-signup form="newsletter"
  endpoint="https://<id>.appsync-api.<region>.amazonaws.com/graphql"
  identity-pool="<region>:<uuid>"></papyrus-signup>
```

`endpoint` is `data.url` and `identity-pool` is `auth.identity_pool_id` from the
site's `amplify_outputs.json`. A site can set them once for every form with
`window.papyrusSignup = { endpoint, identityPool, region }`. Attributes `label`,
`button` and `success` change the words. The element renders a labelled form into
its own light DOM (`form.papyrus-signup`, `input.papyrus-signup-input`,
`button.papyrus-signup-button`, `p.papyrus-signup-status`), the status is a live
region and every outcome is words ("Error: ..."), never colour alone. It signs its
request as the identity pool's unauthenticated identity; that identity can call
`submitSignup` and read nothing. Without JavaScript the element is empty.

**Markus pages.** Markus has no `:::signup` directive and Papyrus does not add one:
directive names are validated by the pinned Markus CLI, and authors cannot write raw
HTML. Put the element where the site owns the HTML, as `docs/public-surface.md` §2
describes for search: a generated page's fragment or the site chrome
(`SiteChrome.scripts = ("/_plugins/papyrus-signup@1.js",)`). A content directive is a
decision for when a second widget needs one.

**Newsroom.** Administration has a Signups panel when the plugin is on: choose a form,
see the entries, refresh, export CSV. Cells that start with `=`, `+`, `-` or `@` are
written with a leading quote so a spreadsheet does not run them.

## Existing sites

Enabling nothing changes nothing: the plugin code is not loaded into the stacks, no
function, table, web ACL or output is added, `PAPYRUS_PLUGINS` is not set and the
newsroom has no panel. `scripts/synth-site-backend.mts` synthesizes a site's whole
backend into a directory so two configurations can be compared; `npm run test:plugins`
pins the registry, the settings, the web ACL and the manifest-to-schema match.
