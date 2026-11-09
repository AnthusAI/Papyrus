# Many sites on one Papyrus: the multi-tenant architecture (PPY-25ffa3)

> Status: design, for Ryan to read and decide. Nothing on this page is built. The work is planned on the PPY board under initiative PPY-25ffa3; the milestones are epic PPY-6a6357. Facts about the code were checked on `origin/develop` at 23fabe1d (2026-11-08); facts about Prospectus on its `develop` at 8b8e6b8 (2026-11-07), updated from `develop` at a329ee1 (2026-11-08) for the Prospectus status, provisioning and security-review sections. Where something was not checked, it says so.

## Words used on this page

- **Tenant**: one customer's site (one publication) on the shared service. A tenant belongs to one Prospectus **Account** (the customer that pays and holds members). One Account may own several tenants.
- **Shared tier**: the default plan. Many tenants run on one Papyrus deployment: one API, one set of tables, one bucket, one CloudFront distribution.
- **Dedicated tier**: one customer, or one of our own sites, runs the same Papyrus software in its own AWS deployment with one fixed tenant. This is how every site runs today.
- **AppSync**: the AWS GraphQL API every newsroom and CLI call goes through. **Rules** (authorisation rules) decide who may read or change each kind of record.
- **Claim**: a fact written inside the sign-in token, for example "this session is an editor of tenant `alpha`". The API reads claims to decide.
- **Index (GSI)**: an extra lookup order on a DynamoDB table. A table may gain only **one new index per deploy**, and has a default limit of 20.
- **Key prefix**: putting the tenant id in front of a stored lookup value, for example `alpha#references` instead of `references`, so one tenant's rows are a separate group in an existing index.
- **Edge**: CloudFront, which serves the public pages. **Invalidation** (purge) tells it to drop a cached page; it costs money above 1,000 paths a month per AWS account.
- **Projection**: Papyrus writing a site's public pages as files into S3, which the edge serves.

## The short version

1. The front end is not the hard part. The hard part is that today a site is kept apart from other sites only because it has **its own backend**. `docs/multi-tenancy.md` says so: tenancy is "scoping, not authorization". Before a second customer shares a backend, every record, file, function and background job must check the tenant.
2. **The API does not need a big redesign.** Existing queries and mutations keep their shape. What changes: an optional `tenantId` field on 52 models (additive); six new models (additive, new tables); tenant prefixes inside existing index values (a data change, not a schema change); one new index on each of about nine tables that have no way to list one tenant's rows; and two breaking steps at the end: removing the global group rules on the shared stack, and making `tenantId` required there. The table in [Schema changes](#schema-changes-model-by-model) lists every model.
3. **Isolation is enforced in the API rules, through claims.** A session acts for one tenant at a time; the token carries one claim per role (`papyrus_tenant_editor = alpha`); every tenant model's rule compares the claim with the row's `tenantId`. A three-day spike (PPY-9f3de0) must prove Amplify can do this before we rely on it, with a named fallback.
4. **Serving is one bucket and one distribution** with each tenant under its own prefix and a small edge function that maps the host name to the tenant. Pages are fresh within the cache lifetime (one hour); an editor can still push one page live now, for that tenant only, never with a wildcard.
5. **Threat Intelligence can move at milestone M5**, after isolation is enforced (M3) and shared serving and site-as-data work (M4). **M7 is the first point at which launching a site is a data change only**, and it is when the design partner's three sites launch, directly on the shared tier (never dedicated first). Earliest realistic M7 is about five weeks out (around 2026-12-11). Public self-serve sign-up is M8, after Stripe in Prospectus.

## What exists today (verified)

### Isolation

- Five models carry `tenantId`: Item, PublishedItem, MediaAsset, PublishedMediaAsset and NewsroomSection, with tenant-prefixed index values (`docs/multi-tenancy.md`). **The other 55 of the 60 models do not**: every knowledge model (Reference, corpora, categories, the semantic graph), every conversation model (Message, MessageThread), assignments, procedures, reviews, editorial checks, editions, tags, proposals, the reader-steering models and SignupEntry.
- Every rule grants by Cognito group (`editor`, `admin`, `curator`), never by tenant (`amplify/data/schema.ts`). An editor of one site who could reach another site's API would see everything.
- Six read-only models (PublishedItem and its siblings) allow **guest** reads through AppSync.
- Reference, Message and MessageThread have **realtime subscriptions** on; the topic-steering workspace subscribes to Reference changes. With group rules, every editor would receive every tenant's events.
- Functions learn their tenant from a **build variable**, `PAPYRUS_TENANT_ID`, copied into five functions by `amplify/site-backend.ts` (lines 471-491), and the schema gives every function access to every model (`functionGrants`). On a shared backend a function would act for whatever tenant its variable names.
- Storage rules give editors write and delete on all of `media/*` and `newsroom/*`; nothing mentions a tenant (`amplify/storage/resource.ts`).
- Six DynamoDB tables outside AppSync have no tenant in their keys: the newsletter table, the title-word index, public-form limits, reader and signup rate counters, and the remote-login tables. Neither does the S3 Vectors knowledge index.
- The projection lease (one projection of a site at a time) is keyed by the **bucket name** (`src/papyrus_content/projection/lease.py`), so on a shared bucket all tenants would queue behind one lock.
- The adoption tools (`content adopt-tenant-data`, `content copy-backend --stamp-tenant`) cover only the five tenant models.

### Serving

- Each site has its own bucket and CloudFront distribution. The projection writes to the bucket root (or under `urls.basePath`, which is also the public URL prefix).
- Freshness: the edge keeps pages for a set lifetime (one hour on production sites). Editors can push a page live now with `update-live` and the refresh commands, which purge exact paths with a cap of 25 per call and a dry run above 5 (`docs/site-hosting.md`, "Refreshing pages on demand"). **But the publish path turns any purge of more than 10 paths into one `/*`**, which on a shared distribution would empty every tenant's cache.
- The content-actions function is built with the site's own `web/` files bundled in (`amplify/functions/content-actions/resource.ts`, `setSiteFilesForContentActionsBundle`), and the projector reads `projection.json` from them. The hooks loader runs site Python. Both assume one site per deployment.

### Cost hazards that multiply by tenant count

- The home-page snapshot re-reads the whole corpus (PPY-ee02b8, about 55,000 AppSync requests an hour on Machines on Machines). The fix (PPY-7f1e54) is partly merged: stage A (attributes) is on develop; the index (PR #1239) and the engine (PRs #1241, #1242) are open.
- Reference intake lists the whole Reference table on each delivery (PPY-ee02b8).
- The reader snapshot reads every vote and profile (`docs/reader-steering.md`; PPY-d647ee).

### Prospectus (billing, accounts, usage)

Confirmed by the Prospectus session on 2026-11-08: each site is product `papyrus-<site>` with its own Cognito pool, client and compute role (a reviewed file entry, capped at about 40); there is no self-serve provisioning API and no invite by email (kanbus-59284c, kanbus-4c99c6, kanbus-b09c91, kanbus-db57cb); no lifecycle events (kanbus-6efecd); billing is a plan per deployment, not usage; the weekly quota service is live for Babulus only; cost accounting is designed (epic kanbus-bb0b6c) and Ryan has said to build it and test it on our sites and a design partner's three new sites. Attribution convention: app `papyrus`, deployment = site id, the Account UUID per site; model tokens as namespaced kinds (`openai.tokens.input`, `jev.tokens`) with no dollars; usage batched to an SQS queue by a shared sender library; shared resources tagged `anthus:account=shared` and split by reported usage.

- Built: Accounts and memberships; the weekly usage quota with `check`, `usage` and `reservations` routes (`docs/QUOTA.md`).
- Agreed, not built: cost accounting in microdollars per Account, app and deployment, with shared resources split by each customer's reported usage (`docs/COST_ACCOUNTING.md`).
- Built but limited: billing lines per product per Account with interval plans; "pricing is out of scope"; Stripe not built. (When first read, billing never changed access; that was superseded on 2026-11-08, see below.)
- **Products are one reviewed file entry per site** (`accounts/papyrus-sites.json`: a Cognito client and review id per site). Self-serve sign-up needs one shared `papyrus` product with a deployment per site.
- The newsroom already reads a "selected account" from the Prospectus session (`lib/prospectus-tenant.ts`) and today maps tenant = Account (`lib/tenant-keys.ts`, `tenantIdForProspectusAccount`).

**Since then (Prospectus `develop` a329ee1, 2026-11-08, and PR #143):**

- The Prospectus session filed epic kanbus-b770c2, *Papyrus deployments created through an API and held as data*: deployment records and routes (kanbus-271b4a), shared sign-in bound to a deployment (kanbus-3e5e82), shared-tier cost accounting (kanbus-f45f7f), custom domains with DNS proof (kanbus-6daa8f), bring-your-own Google client (kanbus-3c5b8b) and its own security review (kanbus-fa72e8). Its first text said the partner's sites would start dedicated; Prospectus #143 corrected that and raised kanbus-fa72e8, kanbus-271b4a, kanbus-3e5e82 and kanbus-f45f7f to priority 1 for the partner launch at M7.
- Billing standing now changes access in Prospectus's own docs (`docs/BILLING.md`, "Billing standing and access"): standing is derived from the ledger (kanbus-b19d5a) and published as events through kanbus-6efecd. Its decision 7 ("billing never changes access", kanbus-8e3174) is superseded.
- Cost accounting is partly built: the `@anthus/cost-accounting` package (`applyCostTags`, `assertCostTags`, a TypeScript `UsageSender`), the private cost ledger and the quota on real cost are merged; the per-product usage queues are merged behind a flag that is off until Ryan approves the permissions (kanbus-71ff98). There is no Python sender yet; Papyrus's model calls are Python.

## The target architecture

One artefact, two ways to run it. The **shared stack** is the normal Papyrus backend deployed once in "shared" tenancy mode, ideally in its own AWS account. A **dedicated site** is the same backend with one fixed tenant. The renderer, components, content model and rules are identical; only where configuration comes from, where pages are written and who may use IAM differ.

```text
 reader ──> <site>.p.apyr.us or custom domain
              │
              ▼
   CloudFront (one distribution) ── edge function: host → tenant (KeyValueStore)
              │                               rewrites /x/ → /sites/<tenant>/x/
              ▼
   S3 (one bucket): sites/<tenant>/...  (pages, renditions, data files, brand.css)
              ▲
              │ projection (per-tenant lease, fair-share queue)
              │
 editor ──> newsroom.p.apyr.us (one newsroom app, Google sign-in, tenant switcher)
              │  token carries papyrus_tenant_<role> = <tenant>
              ▼
   AppSync (one API) ── rules: row.tenantId must equal the role claim
              │
              ▼
   DynamoDB (one table per model, tenant-prefixed keys) + S3 tenants/<tenant>/...
              │
              └─> Prospectus: quota check before model work, usage reports after,
                  daily per-tenant share of shared resources; billing; accounts
```

### How a request knows its tenant

- **Editors and agents.** A person signs in with Google on the one newsroom host and picks a site. A Cognito pre-token Lambda reads their `TenantMembership` row for that site and writes one claim per role (`papyrus_tenant_admin`, `_editor`, `_curator`, `_member`, each holding the tenant id). Switching site re-issues the token. Prospectus says who belongs to an Account; `TenantMembership` says what role they have on a site and is granted only to Account members. The token Lambda reads only the local table, so sign-in never waits on Prospectus. Agents acting for a customer use that customer's signed-in session (remote login), not an IAM role.
- **Functions.** Each function builds its tenant from the caller's claims and uses the tenant-scoped client for every read and write. An IAM call must name the tenant and is allowed only for the platform operator role.
- **Readers.** The reader API takes the tenant from the host the page was served on (looked up in `TenantDomain`), never from the browser's request body.
- **Background work.** Monitors, knowledge runs and scheduled jobs carry an explicit tenant and write an audit line.

### Why claims rather than the alternatives

| Option | Why not (or why) |
| --- | --- |
| One Cognito group per tenant (`alpha-editor`) | Groups appear in every token (a member of many sites gets a huge token), the pool allows 10,000 groups, and Amplify's group rules cannot compare a group with the row's tenant without listing groups on every row. |
| A Lambda authoriser on the API | A function call on every request (cost, latency), and Amplify's model rules then become all-or-nothing, so every row check moves into hand-written resolvers. |
| **Role claims compared with `tenantId`** (recommended) | Amplify supports owner rules that compare a field with a chosen claim. One rule per role gives "right tenant AND right role". To be proven by the spike PPY-9f3de0, including list pages, subscriptions, the immutability of `tenantId`, and which Cognito plan the token customisation needs. Fallback if it fails: tenant models reached only through custom queries and mutations whose resolvers read the claims. |

### Rolling out the rules without breaking anyone

1. **Stage 1, additive** (PPY-06ae68): add the tenant rules beside the group rules. Rules are OR-ed, so nothing changes yet and nothing is isolated yet.
2. **Backfill**: every row gets its tenant and prefixed keys (PPY-8f9462).
3. **Stage 2, breaking, shared stack only** (PPY-bdc4ee): stop generating the global group rules. Now only claims grant access. Blocked by the adversarial suite and security review gate 1.
4. **Stage 3** (PPY-b99fc0): `tenantId` becomes required on the shared stack.
5. **Dedicated sites** adopt their fixed tenant one at a time (PPY-13fbea), then drop the group rules too, so both tiers end on one rule set.

### Proving isolation

A mandatory adversarial suite (PPY-29f730), generated from the schema so a new model or function without a case fails the build. It tries every model operation across tenants, every custom mutation with foreign ids, subscriptions, storage, search (the vector index and the title-word table), snapshot files, the edge (host spoofing, path tricks), the reader API and exports. It gates every release to the shared stack (PPY-f7ce77). An internal security review before isolation is claimed and an external one before the first outside tenants, the design partner's sites at M7 (PPY-3ff465, D22).

## Schema changes, model by model

"Stage" refers to the rollout above: **A** = additive release any site can take; **P** = key-prefix writers plus backfill (data, no schema change); **I** = index release (one index per table per deploy); **B2** = breaking authorisation change on the shared stack; **B3** = `tenantId` required on the shared stack. Every tenant model also gets stage-1 tenant rules (additive) and loses its global group rules at B2.

| Model or table | Change | Additive or breaking | Index impact | Stage |
| --- | --- | --- | --- | --- |
| Item, PublishedItem, MediaAsset, PublishedMediaAsset, NewsroomSection | already have `tenantId` and prefixed keys; rules only; media keys move to `tenants/<t>/media/` | rules breaking at B2 | none | B2, B3 |
| UserProfile, UserIdentity, PublicHandleClaim | stay global (a person spans sites); owner/admin rules kept | none | none | — |
| UserRoleAssignment | superseded by TenantMembership on the shared stack; kept on dedicated | additive | none | A |
| Reference | `tenantId`; corpus ids become tenant-unique, which makes `feedStateKey`, `starFeedKey`, `mediumFeedKey`, `contentNeededKey`, `publicFeedKey` tenant-safe; prefix `newsroomFeedKey`, `versionState`, `curationStatus(Key)`, `reviewedFeedKey` | additive + data | **none** (15 indexes, 16 with PR #1239; corpusId index lists a tenant) | A, P, B2, B3 |
| ReferenceAttachment, KnowledgeImportRun, KnowledgeRawPayload, KnowledgeArtifact | `tenantId`; keys are ids or corpus ids | additive | none expected (confirm in PPY-cd5926) | A, P |
| KnowledgeCorpus | `tenantId`; id `<tenant>.<corpus>`; prefix `role` | additive + data (corpus id rewrite) | none | A, P |
| CategorySet, Category, CategoryKeyword, LexicalSteeringRule, SteeringProposal, SteeringDecision | `tenantId`; prefix status/scope/domain/keyword values | additive + data | none | A, P |
| SemanticNode, SemanticRelation, SemanticRelationType | `tenantId`; prefix `newsroomFeedKey`, `nodeKey`, `key`, `domain`, `status`, `relationTypeKey`, `relationDomain` | additive + data | none | A, P |
| CurationDelegationRecord | `tenantId` | additive | none | A |
| Message, MessageThread | `tenantId`; prefix `newsroomFeedKey`, `status`, `messageKind`, `messageDomain`, `threadKind`, `primaryAnchorKey`, …; subscriptions off on the shared stack | additive + data; subscriptions removed (shared) | none | A, P, B2 |
| ModelAttachment | `tenantId`; prefix `role` | additive + data | none | A, P |
| Assignment, AssignmentEvent | `tenantId`; prefix `newsroomFeedKey` (`assignment#<status>`), queue, type, status and section keys | additive + data | none | A, P |
| ProcedureDefinition, ProcedureVersion, ProcedureRun | `tenantId`; prefix procedure key, status keys | additive + data | none | A, P |
| Automation, ReviewRequest, ReviewReadMark, ReviewRecipientRule | `tenantId` | additive | **adds one `tenantId` index each** (they have no index today) | A, I |
| StoryVariation | `tenantId` (lineage ids are unique) | additive | none | A |
| EditorialPolicy, EditorialCheckSettings | `tenantId` | additive | **adds one `tenantId` index each** | A, I |
| EditorialFeedback, EditorialCheckRun | `tenantId` (item and lineage ids are unique) | additive | none | A |
| Proposal | `tenantId`; prefix `state` | additive + data | none | A, P |
| Tag, ItemTag | `tenantId`; prefix `slug`, `type` | additive + data | none | A, P |
| Edition, EditionItem, PublishedEdition, PublishedEditionItem | `tenantId`; prefix `slug`, `status`, `versionState` | additive + data | none | A, P |
| PublishedCategorySet, PublishedCategory | `tenantId`; prefix `status`, `classifierId`, `categoryKey`; guest read removed on the shared stack | additive + data; guest rule removed (shared) | none | A, P, B2 |
| ReaderProfile, ReaderComment, ReaderSubmission, ReaderReport, ModerationAction | `tenantId`; tenant in ids and keys | additive + data | none | A, P |
| ReaderHandle, ReaderVote, ReaderFlag | `tenantId`; tenant in ids | additive + data | **adds one `tenantId` index each** | A, P, I |
| SignupEntry | `tenantId`; prefix `form` | additive + data | none | A, P |
| NewsletterTable, ReferenceWordTable, PublicFormsLimits, reader and signup rate tables, remote-login tables (outside AppSync) | tenant in partition keys | data (key rewrite) | none (keys, not indexes) | P |
| S3 Vectors knowledge index | one index per tenant or a mandatory tenant filter (decided with a measurement) | data | n/a | P |
| Projection lock table | key `<bucket>#<tenant>` | data | none | A |
| **Tenant** (new) | site id, owning Account, state, plan, entitlements | additive (new table) | created with indexes `accountId`, `stateKey` | A |
| **TenantMembership** (new) | `<tenant>#<userSub>`, role | additive (new table) | created with `userSub`, `tenantId` | A |
| **TenantDomain** (new) | host name → tenant, status, certificate | additive (new table) | created with `tenantId` | A |
| **SiteDocument**, **SiteDocumentVersion** (new) | catalogue rows for SiteConfig, BrandPack, nav; bodies in S3 | additive (new tables) | created with `documentId` + version | A |
| **TenantUsageCounter** (new) | `<tenant>#<meter>#<period>`, atomic counters | additive (new table) | created with `tenantId` + period | A |
| `previewSitePage` (new query) | renders one page from unsaved settings | additive | none | A |

The list of tables that need a `tenantId` index is confirmed by the generated inventory (PPY-cd5926). New tables can be created with all their indexes in one deploy; the one-index limit applies to changing an existing table. All the "adds one index" tables are different tables, so they can share one release, but never with another index change on the same table. A CI check (PPY-8f2c4f) enforces that.

## Serving

- **One bucket, tenant prefixes.** Each tenant's pages, image renditions, data files, `404.html`, `robots.txt` and sitemap live under `sites/<tenant>/`. The output prefix is separate from `urls.basePath`, which keeps meaning "a public URL prefix". Dedicated sites keep writing to the bucket root.
- **Host routing at the edge.** A CloudFront Function maps the host to the tenant through a KeyValueStore and rewrites the path into the tenant's prefix; unknown hosts get a 404. Redirects become per tenant. A synthetic check compares each page's tenant marker with its host. Whether we use this or CloudFront's own multi-tenant distributions is decided by the spike PPY-3b3cc3 (not checked against current AWS documentation).
- **Default subdomains** on one wildcard certificate for `*.p.apyr.us` (decided: `<site>.p.apyr.us`). **Custom domains** in every plan: the tenant creates DNS records we show, a workflow issues the certificate and adds the host. No Amplify domain associations (they throttle and refuse cross-account host names).
- **One newsroom host** for every tenant, recommended `newsroom.p.apyr.us` (Cognito allows 100 callback URLs per app client, and a wildcard certificate covers one label only).
- **Freshness.** Pages are fresh within the cache lifetime (one hour) with no purge on save. `update-live` and refresh still purge exact paths for that tenant, capped at 25 per call, metered to the tenant. The publish path never sends `/*` on the shared distribution. The 1,000 free paths a month belong to the AWS account, so no tenant is promised them.
- **Fair projection.** The lease is per tenant; bulk work (re-renders, snapshots, re-projection after a release) goes through one queue with the tenant as the message group, so one tenant's big job cannot hold everyone up.
- **Cost per tenant** is measured on staging before pricing (PPY-04ce84): storage, requests and bytes served, edge function and KeyValueStore reads, projection time and writes, API requests, model spend, purged paths and email.

## Sign-in for the shared tier

Ryan's rule (2026-11-08): launching a site cannot need code or a deployment, so sign-in cannot need per-site configuration. Google sign-in only; never create Cognito password users.

- **Default: one of everything.** The shared stack has one Cognito user pool, one Google identity provider using one Google OAuth client that we own, and one app client. Its callback list is fixed and tiny: `https://newsroom.p.apyr.us/` (and its `/newsroom` forms), the CLI's loopback callbacks, and localhost for development. It never grows with tenants, so the limit of 100 callback URLs per app client never binds (PPY-fdbbd7).
- **How a site reaches it.** `<site>.p.apyr.us/newsroom` (or a custom domain's `/newsroom`) redirects to `newsroom.p.apyr.us` with the site preselected; the person signs in with Google, then works in the site they chose. The site id travels in the OAuth state and is checked against `TenantDomain`.
- **Scoping after sign-in.** Signing in proves who the person is, nothing more. The pre-token Lambda issues role claims only for a `TenantMembership` the person holds for the chosen site; with none, they see nothing.
- **Bring your own Google client (later, optional; PPY-496c0b).** A tenant admin enters its own client id and secret. Stored as SSM Parameter Store SecureString under `/papyrus/shared/tenants/<tenant>/google-oauth/client-id` and `/client-secret` (never Secrets Manager unless a service requires it), written only by one function on a tenant admin's request; the secret is never returned or logged. Validated before use: format, the redirect URI we show (the pool's `/oauth2/idpresponse` address) registered in the tenant's Google project, and one successful test sign-in while the client is "pending". Rotation: a new parameter version, the provider updated, the test repeated, the old version kept until it passes. Removal or repeated failure: the tenant falls back to the shared Google client at once; members keep their roles because membership is keyed on the person's profile, not on one provider's user id.
- **What Cognito allows (to verify, spike PPY-8eca5b, 2 days).** I believe the built-in Google provider has a fixed name, so a pool holds only one; a tenant's own client would be added as a generic OIDC provider (issuer `https://accounts.google.com`) with a per-tenant name. Not verified: that this gives the same claims and `email_verified` mapping; the number of identity providers and app clients a pool allows; whether each such tenant needs its own app client so the sign-in page offers only its provider; and whether a person signing in through both providers can be linked to one Cognito user (otherwise Papyrus maps both to one profile through `UserIdentity`). The tenant's consent screen will show our Cognito domain unless the pool has a custom domain (one per pool).

## Site as data and the brand pack

A shared-tier site is data, never code: a **SiteConfig** document (name, tagline, purpose line, sections, nav order, home template, footer links, analytics id, consent region policy, which feature blocks are on), a **BrandPack** (logo, colours for light and dark, fonts from an allow-list, under the validator), and pages. Customers cannot set in v1: hooks or any code, arbitrary CSS, sizes, spacing, the image ratio, borders, URL style, base path, pattern redirects, the image pipeline, cache settings or plugins (plugins are plan entitlements). The renderer reads these from the site store at run time on the shared stack and refuses to load hooks. A brand change writes one small stylesheet of custom properties; the core stylesheet is one shared file per release. Live preview renders one page from unsaved settings. Machines on Machines stays a dedicated site; core tests use a fictional fixture with its structure, so the layout is tested without MoM becoming a tenant.

## Metering and spend

Papyrus reports usage to Prospectus in Prospectus's own item kinds (PPY-3fd951): model tokens per model, images, web searches, function GB-seconds, Batch vCPU-seconds, API requests, estimated DynamoDB units, S3 writes, purged paths, emails; daily, storage per tenant prefix and requests and bytes per host. Model work checks the tenant's Account quota first and stops cleanly when the budget is used (PPY-889ab5); serving pages never depends on it. Shared resources are tagged `anthus:account=shared` and Prospectus splits their cost by the reported usage. Noisy neighbours are slowed by limits learned from each tenant's own traffic, not fixed caps.

## Launching a site as data only (target at M7)

Ryan's rule (2026-11-08): launching a site is a data change only. No code edit, no deploy, no Cognito change, no new certificate. Today each site is a reviewed `papyrus-<site>` entry in Prospectus's `accounts/papyrus-sites.json`, capped at about 40, with its own pool, client and role. On the shared tier this becomes one `papyrus` product whose deployments are records created by API.

```text
operator (partner)          Prospectus                          Papyrus shared stack
or checkout (M8)
     │  create deployment       │                                      │
     │  <site>, Account, op id  │                                      │
     └────────────────────────> │ deployment record (only writer)      │
                                │ ── deployment.changed event ───────> │ provisioning (PPY-70a429)
                                │ <── reconcile: list changed since ── │   re-read deployment, entitlement,
                                │ <── authorize / standing read ────── │   standing; rate limits; names
                                │                                      │   Tenant, owner membership,
                                │                                      │   <site>.p.apyr.us + edge entry,
                                │                                      │   SiteDocuments from the starter,
                                │                                      │   sections, corpus, counters,
                                │                                      │   first projection
owner ── <site>.p.apyr.us/newsroom ──> newsroom.p.apyr.us ── Google (shared client)
                                │ authorize: token bound to <site>,    │ pre-token Lambda issues role
                                │ Account owns it, person is a member  │ claims for <site> only
```

1. An operator (for the design partner) or, from M8, self-serve checkout creates deployment `<site>` of product `papyrus` for an Account through the Prospectus API (kanbus-271b4a), idempotent by operation id. Prospectus is the only writer of deployment records and of hostname claims (decisions D7, D8).
2. Prospectus publishes `deployment.changed` (asked on PPY-966ef5, through kanbus-6efecd). Papyrus also sweeps deployments changed since its last cursor, so a lost event only delays a launch.
3. Papyrus's provisioning workflow never trusts the event body: it re-reads the deployment, the entitlement and the billing standing, checks the learned rate limit and the reserved-name list, then creates everything in steps that are each idempotent (key: deployment id plus revision) and audited outside tenant data.
4. The owner signs in on the one newsroom host with the shared Google client; Prospectus `authorize` checks that the token is bound to that deployment and that the person is a member (kanbus-3e5e82); only then does the pre-token Lambda issue role claims.
5. Lifecycle: `billing.standing_changed` makes editing read-only at the next token refresh (public site stays up); `deployment.deletion_due` runs export-then-delete and Papyrus confirms deletion back to Prospectus. A retired deployment's edge host entry is removed before Prospectus releases the hostname (takeover protection).

## Shared-tier request flow (for the joint security review, kanbus-fa72e8)

The rule everywhere: **the tenant comes from who is calling or from where the page was served, never from the request body.** A tenant id in a body, query string or header is either ignored or must equal the derived tenant, or the call is refused.

### 1. Editors and agents (newsroom, CLI, MCP)

1. A person opens `<site>.p.apyr.us/newsroom` (or a custom domain's `/newsroom`). The edge redirects to `https://newsroom.p.apyr.us/` with OAuth `state` carrying only the site id. The site id is a hint for the site picker; it grants nothing.
2. Sign-in is Google only, through the one shared Google OAuth client and the one Cognito app client of the shared pool. The callback list is fixed: the newsroom host, the CLI loopback addresses and localhost for development. No Cognito password users exist.
3. The person picks a site (or the hint preselects it). The newsroom server calls **Prospectus `authorize`** with the person's verified identity and the **deployment** (site id) and gets back a yes or no, the capabilities and the billing standing (kanbus-3e5e82). Prospectus checks three things: the token is bound to that deployment (host or audience), the deployment's Account owns it, and the person is a member of that Account.
4. Cognito's pre-token-generation Lambda issues role claims for **that one deployment only**, and only when two things hold: `authorize` approved it, and the person has a `TenantMembership` row for it. The claims are `papyrus_tenant_admin`, `_editor`, `_curator` and `_member`, each holding the tenant id. If billing standing is restricted, it issues read-only claims. Switching site means a new token. The Lambda reads its own table only, so sign-in never waits on Prospectus at token refresh. Membership changes and standing changes arrive by events.
5. Every AppSync call carries that token. Each tenant model's rule compares the row's `tenantId` with the role claim (spike PPY-9f3de0, fallback named). `tenantId` cannot be changed after create. Lists go through tenant-prefixed index keys. No group rule grants anything on the shared stack (PPY-bdc4ee).
6. Every function builds a `TenantContext` from the AppSync identity's claims (PPY-cc8a4c) and uses the tenant-scoped client for every read and write: DynamoDB, S3 under `tenants/<t>/` and `sites/<t>/`, the vector index and the tables outside AppSync. `PAPYRUS_TENANT_ID` is not used on the shared stack.
7. Agents acting for a customer use that customer's signed-in session (remote login), so they get exactly the person's claims. IAM calls are for platform staff only. On a shared stack an IAM call must name a tenant explicitly, is refused without one, and is audited.

### 2. Readers (public pages and the reader API)

1. Pages are static files that CloudFront serves from `sites/<tenant>/`. A CloudFront Function maps the `Host` header to a tenant through a KeyValueStore written only by the provisioning and domain workflows, and rewrites the path into that prefix. An unknown host gets a 404. A request cannot name a prefix: a path that tries is rewritten under the host's tenant.
2. There are no guest AppSync reads on the shared stack (PPY-baa75d).
3. Reader writes (votes, comments, submissions, sign-ups) go to the reader API, which takes the tenant from the **host the page was served on**, looked up in `TenantDomain`, never from the body (PPY-6b084f). Reader identities are pairwise per deployment (Prospectus kanbus-3e5e82; PPY-5219fc).

### 3. Background work

Monitors, knowledge runs, projections and scheduled jobs carry an explicit tenant from the record that created them. They write an audit line, use the per-tenant lease and the fair queue, and cannot reach another tenant's prefix: writers refuse keys outside their own prefix.

### 4. Where Papyrus calls Prospectus

| Call | When | Direction | What it carries |
| --- | --- | --- | --- |
| `authorize` | When a person picks or switches site, then cached briefly | Papyrus → Prospectus, signed | identity, deployment; returns allow, capabilities, standing |
| Quota `check` | Before model work, cached a few seconds | Papyrus → Prospectus, signed | Account, deployment |
| Usage messages | About once a minute, or at the end of each invocation | Papyrus → `prospectus-usage-papyrus` SQS queue (one queue, one sending role) | Account, app `papyrus`, deployment, item kinds and quantities, operation id; no dollars, no personal data |
| Deployment record read | On each provisioning step and lifecycle action | Papyrus → Prospectus, signed | deployment id; returns Account, hostnames, status, revision |
| Changed-since list | Reconcile sweep on a schedule | Papyrus → Prospectus, signed | cursor; returns changed deployments |
| `deployment.changed`, `billing.standing_changed`, `deployment.deletion_due`, membership and entitlement events | When they happen | Prospectus → Papyrus (kanbus-6efecd), at least once | ids and revisions only; Papyrus re-reads before acting |
| Deletion confirmed | After verified-empty deletion | Papyrus → Prospectus | deployment id |

The Papyrus shared-tier role may read deployments and request hostname changes for its own tenants. It cannot create Accounts, grant entitlements or write billing.

### 5. What a token for one deployment cannot do

A session token issued for deployment `alpha` cannot:

- read, list, create, update or delete any row of `beta`, including through an index, a custom query or mutation, a search (vector index, title-word table) or a snapshot file;
- move a row from `alpha` to `beta`, or create a row stamped `beta`;
- upload to, read from or delete under `beta`'s storage prefixes;
- receive `beta`'s events (subscriptions are off on the shared stack);
- obtain `beta` claims by refreshing, by sending `beta` in a request body or in OAuth `state`, or by opening `beta`'s newsroom URL: `authorize` refuses and no claim is issued;
- act as `alpha` after the person's membership is removed or `alpha` is suspended, beyond the next token refresh;
- trigger provisioning, change hostnames or set sign-in clients for any deployment (these are operator, Prospectus or tenant-admin actions, each re-checked server-side).

Every item has a case in the adversarial suite (PPY-29f730), which gates every shared-stack release (PPY-f7ce77). The scenario "A token for one deployment cannot act on another" is on PPY-1da916.

## Security review of data-driven provisioning

There is no human gate any more, so provisioning is attack surface. Two reviews run together on one threat model: Papyrus's (PPY-1da916) and Prospectus's (kanbus-fa72e8). Inputs from the Prospectus review that Papyrus must answer or match:

| # | Question (kanbus-fa72e8) | Papyrus's answer or control |
| --- | --- | --- |
| 1 | Who may create, change and delete a deployment; abuse limits | Prospectus operators and later checkout create; the Papyrus shared-tier role reads and requests hostname changes only. Papyrus adds learned per-Account and global creation limits with an operator stop. |
| 2 | Binding a shared-client token to one deployment | `authorize` checks host or audience centrally; the pre-token Lambda issues claims only for the deployment `authorize` approved. Scenario: "A token for one deployment cannot act on another". |
| 3 | Custom domain proof, uniqueness, takeover after deletion | Prospectus holds the claim and DNS proof with a cooling-off period; Papyrus removes the edge entry first and mirrors the claim in `TenantDomain`. |
| 4 | Bring-your-own Google client secrets | One owner (D11, recommended Papyrus's shared stack, SSM SecureString); never returned or logged; off the M7 path. |
| 5 | One shared-tier role in the Prospectus resource policy | One `papyrus` shared-tier role instead of a per-site list; its grant is reviewed (item 9). |
| 6 | Cyclotron lab verifier trust | Moves from the site registry to deployment records; the tenant's Cyclotron id is derived at provisioning. |
| 7 | Reader subjects per deployment | Pairwise per deployment, matching PPY-5219fc. |
| 8 | Deletion and export under billing standing | Export always available; deletion only on `deployment.deletion_due`, verified empty, confirmed back. |
| 9 | Every new IAM permission and parameter | Listed for Ryan's approval before deploy, on both sides. |

Papyrus-side controls: only a paid, verified entitlement can provision (re-read, never from the event); input validation and moderation of names and starter text; the provisioning role cannot read tenant content; an append-only audit trail that survives tenant deletion; replay keys; one-command takedown (PPY-d7c279).

## Cost accounting on our sites and the partner's

Ryan asked for Prospectus cost accounting (`docs/COST_ACCOUNTING.md`, epic kanbus-bb0b6c) to be built and tested on our own sites and the design partner's three sites (PPY-25e0d7). Order: tags first with the Prospectus package (PPY-f98e05: `applyCostTags` in `amplify/site-backend.ts`, `assertCostTags` in CI), which makes Cost Explorer attribution work from day one on dedicated stacks; then model-token reports through the usage sender once the `papyrus` queues are switched on (kanbus-71ff98, needs Ryan's approval) and a Python sender exists; then, on the shared stack, per-tenant usage of shared resources (PPY-49d059) so Prospectus can split the `anthus:account=shared` cost (kanbus-f45f7f). Acceptance: a week of one site's ledger agrees with Cost Explorer and the OpenAI usage report within a stated tolerance.

## The design partner's three sites

Ryan (2026-11-08, repeated): the design partner's three new sites launch **directly on the shared tier at M7**, as tenant deployments created by data. They never start as dedicated sites; there is no dedicated launch, no later move and no migration runbook for them (PPY-37f2ec). M7 therefore includes everything they need to be live: provisioning from a Prospectus deployment record, shared Google sign-in on `newsroom.p.apyr.us`, branding and layout as data (publication preset, SiteConfig, BrandPack, starter template), lifecycle, export and deletion, cost accounting basics (shared stack tagged, model tokens and per-tenant shared usage reported, spend ceiling on), and the isolation and review gates. They are the first outside test of Prospectus cost accounting on the shared tier (kanbus-f45f7f). An operator creates their deployments and the partner is invoiced; self-serve checkout is M8.

## Critical path to M7

Full plan, release order, schedule and dispatch list: PPY-e38a2d. M7 is the launch of the design partner's three sites on the shared tier. Three chains of similar length, so all three are managed as critical (estimates in one-agent sessions of 2 to 4 hours):

| Chain | Steps | Size |
| --- | --- | --- |
| Isolation | auth spike PPY-9f3de0 → session claims PPY-0bb0fd → functions take the tenant from the caller PPY-7dc463 → workers PPY-203ce2 → group rules removed PPY-bdc4ee (also waits for tenantId PPY-94d609 → key prefixes → adoption PPY-8f9462) → gate 1 PPY-3ff465 → TI rehearsal PPY-e1d26f → TI cut-over PPY-e51189 | about 15 |
| Layout | card and brand pack slices → publication preset PPY-cf7e6e (largest item, about 8) → TI brand-neutral acceptance PPY-7e396d → TI cut-over; preset → starter template PPY-3aa10f → provisioning PPY-70a429 → review PPY-1da916 | about 16 |
| Prospectus | deployment records and shared sign-in (kanbus-271b4a, kanbus-3e5e82) → PPY-966ef5 → provisioning → joint review; lifecycle events (kanbus-6efecd, kanbus-b19d5a) → PPY-6cb44b → PPY-d7274f → deletion PPY-62f10d | about 11 plus Prospectus work and approvals |

```text
M0 spikes ──┬─> M2 additive data + claims ──> M3 isolation (staging shared stack) ──┐
            │                                                                     ├─> M5 TI cut-over ──┐
            ├─> M1 cost fixes + preset ─────────> M4 shared serving + site data ──┘                     ├─> M7 data-only launch
            │                                     └─> M6 metering ──────────────────────────────────────┤
            └─> Prospectus: deployments API, shared sign-in, lifecycle events, review ───────────────────┘
```

**Can start today, in parallel** (one session each, no blockers): auth spike parts PPY-867f76 and PPY-f4d892; CDN spike PPY-7cd7a2; tenancy mode switch PPY-46635e; tenantId fields PPY-94d609; tenant models PPY-31c45c; key inventory PPY-cd5926; suite generator PPY-65e5a9; output prefix PPY-16d75b; SiteConfig schema PPY-ee1e02; core cards PPY-ecb656; brand pack validator PPY-7bc5b7; GSI ledger PPY-8f2c4f; cost tags PPY-f98e05. The Prospectus session works its chain at the same time.

**Not on the path to M7:** the ordering rule and native tokens (D4), bring-your-own Google client, overage billing, TI's 14-day close (D3), dedicated-site adoption (D13), managed upgrades, the cost model, preview, home templates, onboarding polish and reader features (D6).

**Schedule:** with six Papyrus agents and one Prospectus agent, a release every one to two days and approvals within a day, earliest realistic M7 is about five weeks out (around 2026-12-11; optimistic 2026-12-02; pessimistic late January 2027). The biggest risks to the date: the auth spike failing (adds 1 to 2 weeks), Prospectus capacity or approvals, and scope creep in the preset.

## Milestone acceptance

Each milestone task on the board lists its Gherkin scenarios (by name and feature file) and acceptance checks. In short:

| Milestone | Key scenarios | Acceptance checks |
| --- | --- | --- |
| M0 Decisions and spikes | "A token for alpha cannot touch beta's Item"; "An index list returns full pages for the caller's tenant"; "Purging alpha's page leaves beta's cached"; "The inventory is current" | yes/no per spike question with evidence; sandbox stacks destroyed; decisions answered |
| M1 Cost fixes and layout | "Cost does not grow with corpus or tenant count"; "A site picks the preset in configuration only"; "The shared suite passes for a second brand" | no whole-table read; TI on the preset with no MoM change; policy checks in both themes |
| M2 Additive data | "A client without a tenant writes exactly as before"; "A member of two sites acts for one at a time"; "A single-tenant backend is copied into a tenant completely" | dedicated sites unchanged; zero tenant-less rows on a Pilobolus copy; one index per table per release |
| M3 Isolation | "A Cognito group alone grants nothing on the shared stack"; "A model with no isolation case fails the build"; "A guest cannot list published rows on the shared stack" | suite green twice on staging; gate 1 signed off |
| M4 Shared serving | "Each host shows its own tenant"; "A large publish never becomes a wildcard"; "A new site needs no sign-in configuration change" | tenant-marker check clean; fixed callback list; no `/*` purge; load test |
| M5 TI | "The staging tenant matches the live TI site"; "A bad cut-over can be reversed without losing edits" | URL parity; second copy changes nothing; rollback rehearsed |
| M6 Metering | "A model call on a dedicated site reaches the cost ledger once"; "A tenant over its weekly budget cannot start model work" | ledger agrees with Cost Explorer for a week; no unknown item kinds |
| M7 Partner sites live on the shared tier | "A new shared-tier site is created with no code change"; "A deployment record creates one tenant even when the event repeats"; "A token for one deployment cannot act on another"; "Deletion leaves nothing behind" | on production a test deployment goes live with no commit, deploy or callback change; replay safe; export and delete verified; provisioning and external reviews closed; the partner's three sites live with cost per deployment |
| M8 Public self-serve sign-up | "A paid sign-up reaches a live site"; "A tenant that opted in keeps working past its quota and is billed for it" | a stranger signs up and pays with no operator step; first invoice matches the ledger |

- Unchanged: Threat Intelligence moves at M5; M7 needs TI's cut-over, not its 14-day close (D3).

## Threat Intelligence first

TI's rows carry no tenant today. The move is a full copy into a tenant of the shared stack (`copy-backend --stamp-tenant threat-intelligence` extended to every model), a rehearsal on staging with every URL compared, then a cut-over day: freeze, final copy (the second run must change nothing), add `threat-intelligence.anth.us` as a custom domain, switch the alias record to the shared distribution, verify, open the shared newsroom to TI's editors. Rollback for 14 days by switching the alias back and copying any new edits back. Done after 14 green days; then the old backend is retired with approval. Pilobolus is the recommended second site. Shipped, Anth.us and Machines on Machines stay dedicated for now; Distinctive Mark stays dedicated until its staged upgrade.

## Risks

1. **A cross-tenant leak** through a path the rules do not cover (a function's schema-wide grant, IAM, a subscription, search, a snapshot file). Mitigation: claims-based rules, functions that take the tenant from the caller, the generated adversarial suite as a release gate, two security reviews.
2. **The claim design does not work in Amplify** for index lists or subscriptions. Mitigation: three-day spike first, fallback named in advance.
3. **Invisible rows after the breaking step**: a row without `tenantId` disappears for its editors. Mitigation: backfill reports must show zero tenant-less rows before stage 2; stage 2 is a rules-only release that can be rolled back.
4. **Cost multiplies by tenant count**: whole-corpus snapshots, whole-table intake, wildcard purges. Mitigation: PPY-7f1e54, PPY-ee02b8, PPY-d647ee in M1; no wildcard on the shared stack; call-count tests at 50 tenants; load test before TI moves.
5. **Wrong host routing** sends one tenant's host to another's pages. Mitigation: only workflows write the KeyValueStore, with read-back; a synthetic tenant-marker check.
6. **Prospectus is not ready** for self-serve: products per site (each with its own pool, client and compute role, capped at about 40), no provisioning API, no invites by email, no lifecycle events, billing per deployment plan rather than usage, quota live for Babulus only. Mitigation: each gap is a filed issue (PPY-966ef5, PPY-6cb44b, PPY-8a3c6a, PPY-25e0d7); Prospectus has filed each (kanbus-b770c2) and raised them to priority 1 for the partner launch at M7; TI moves onto the shared tier before the partner's sites.
11. **Data-driven provisioning has no human gate**, so a flaw lets anyone who can pay create sites at scale. Mitigation: the provisioning security review (PPY-1da916): entitlement re-read from Prospectus, learned rate limits with an operator stop, input validation and moderation, an audit trail kept outside tenant data, replay keys, one-command takedown.
7. **Noisy neighbours** on the projection, the API's request rate or the account's Lambda concurrency. Mitigation: per-tenant lease, fair queue, learned limits, the shared stack in its own AWS account.
8. **One bad release breaks every tenant.** Mitigation: staging shared stack first, golden renders, browser matrix, release gate, rollback runbook.
9. **Adopting every dedicated site** to a fixed tenant is a long, per-site data migration. Mitigation: one site at a time, Pilobolus first, Anth.us last and only on instruction.
10. **Restoring one tenant's data** is hard because point-in-time restore works per table. Mitigation: a rehearsed runbook (restore into new tables and copy back only that tenant's rows).

## Decisions only Ryan can make

**Already decided (Ryan, 2026-11-07 and 2026-11-08):** the design partner's three sites launch directly on the shared tier at M7, never dedicated first; launching a site is a data change only, through one Prospectus `papyrus` product whose deployments are created by API, with its own security review; billing may change access (read-only 14 days past due, deletion 30 days after cancellation, export throughout); build cost accounting and test it on our sites and the partner's three; one shared Google OAuth client by default, a tenant's own client later; public sites at `<site>.p.apyr.us`; subscriptions off on the shared stack; Google sign-in only, never Cognito password users; usage pricing through Prospectus, no free tier.

**Still open, each with my recommended default.** If you do not answer, agents go ahead with the default.

| # | Question, in plain words | Recommended default |
| --- | --- | --- |
| D2 | Where do editors of shared-tier sites sign in? | One shared address, `newsroom.p.apyr.us`, picking the site after sign-in. A separate newsroom address per site needs a certificate per site and runs into Cognito's limit of 100 sign-in return addresses. |
| D3 | Can the partner's sites go live once TI has moved, without waiting for TI's 14 trouble-free days? | Yes. The 14 days still decide when TI's old backend is retired. |
| D4 | Leave the new sizing system (retiring the scaler) and the one ordering rule for every list out of the M7 path? | Yes. The layout ships on today's sizes; both follow after M7. |
| D5 | For the partner, does an operator create its sites in Prospectus and invoice it, rather than waiting for Stripe checkout? | Yes. Self-serve checkout comes at M8. |
| D6 | Do the partner's sites need reader votes and comments, live preview or the guided first-run setup at launch? | No; they follow after M7 unless the partner needs them. Please ask the partner. Same for custom domains (the plan supports them). |
| D7 | Who creates a site's record: Prospectus or Papyrus? | Prospectus only. Papyrus reacts to Prospectus's event and double-checks with a regular sweep. |
| D8 | Who proves that a customer owns its custom domain: Prospectus or Papyrus? Both had planned it. | Prospectus holds the claim and the proof; Papyrus copies it and handles the certificate and the edge. |
| D9 | May agents run the spikes in the personal sandbox AWS account without asking each time? | Yes, sandbox only, everything destroyed afterwards. |
| D10 | Put the shared stack in its own new AWS account (recommended name `papyrus-shared`), created this week? | Yes: separate blast radius, limits and cost line. |
| D11 | When a tenant later brings its own Google sign-in client, which system keeps its secret? Both had planned it. | Papyrus's shared stack (the sign-in pool that uses it), as an SSM SecureString; Prospectus records only that the site has its own client. |
| D12 | Register `p.apyr.us` on the Public Suffix List so browsers treat each site as separate (no shared cookies)? | Yes, submit early; it takes weeks and is hard to undo. |
| D13 | Keep our dedicated sites off the tenant data migration until after M7? | Yes, one site at a time afterwards, Pilobolus first, Anth.us last and only on your instruction. |
| D14 | Is a tenant one site (an Account may own several), rather than the whole Account? | Yes: tenant = site. |
| D15 | How fresh are shared-tier pages? | Live within an hour; "Update live now" for urgent pages, each purge counted as usage, 25 pages per click. |
| D16 | After adopting their tenant, do dedicated sites drop the old group rules too, so both tiers run one rule set? | Yes, one site at a time. |
| D17 | Analytics on tenant sites: only the tenant's own measurement id? | Yes, never ours without disclosure. |
| D18 | Keep each site's readers separate, so no tenant can link its readers to another's? | Yes (Prospectus already plans per-site reader ids). |
| D19 | When a tenant hits its weekly model budget, stop model work or keep going as paid overage? | Stop model work; reading, editing and serving continue. Paid overage as an opt-in after M7 (PPY-8a3c6a). |
| D20 | Restoring one tenant's data after a mistake: a promise or best effort? | Best effort with a rehearsed runbook in v1. |
| D21 | Agents working for a customer act only through that customer's signed-in session; AWS-level access is for our staff only? | Yes. |
| D22 | Move the external security review in front of the partner's launch at M7 (they are our first outside tenants), instead of M8? | Yes; book it now so it runs during M4 to M6 and does not lengthen the path. |

## What the 2026-11-07 memo got wrong or missed

- It said three models lack tenant isolation (Reference, KnowledgeCorpus, KnowledgeImportRun). In fact 55 of 60 models have no `tenantId`.
- It marked "content-actions is built with the site's `web/` bundled in" as inferred; it is true (`setSiteFilesForContentActionsBundle`).
- It said PPY-7f1e54's PRs #1238 to #1242 were unmerged; #1238 (stage A) is now merged; #1239, #1241 and #1242 are open.
- It recommended "no invalidations" for the shared tier. Since then targeted, capped, per-page purges shipped (page refresh, `update-live`), and the real hazard is different: the publish path collapses more than 10 paths into `/*`, which on a shared distribution empties every tenant's cache.
- It missed: functions take their tenant from a build variable and have schema-wide grants; guest AppSync reads on the published models; realtime subscriptions on three models; the bucket-keyed projection lease; the six tables outside AppSync and the vector index; Cognito's 100-callback limit (which forces one newsroom host); DynamoDB's 20-index limit (which rules out a tenant index per existing index and forces key prefixes); and that Prospectus products are a reviewed file per site and billing never suspends automatically.
- It proposed per-Account Cognito groups as a first option; group-per-tenant hits token size and group limits, so this design uses role claims.
- Its decision 10 (seats plus included spend) is superseded by Ryan's decision: usage only, through Prospectus.

## Not verified

- CloudFront multi-tenant distributions: features, quotas, prices, and whether an invalidation path matches the requested or the rewritten path (spike PPY-3b3cc3).
- Amplify owner rules with custom claims on index lists and subscriptions, and which Cognito feature plan the token customisation needs (spike PPY-9f3de0).
- Amazon SQS fair queues for the projection queue (measured in PPY-994bd0).
- AppSync's per-API request rate quota for a shared API.
- Data volumes of TI's current backend.
- Cognito limits for several Google clients in one pool, and the OIDC route for a tenant's own Google client (spike PPY-8eca5b).
- Whether Prospectus will publish the Python usage sender (kanbus-40dc2a promises one; it is TypeScript only today), or Papyrus writes a twin against the same message format.
- Whether Prospectus will publish a `deployment.changed` event and a changed-since list route (asked on PPY-966ef5).

## The plan on the board

Initiative PPY-25ffa3; critical-path plan PPY-e38a2d (dispatch list in its first comment); milestones epic PPY-6a6357 (M0 to M8, one task each, each with Gherkin scenario names and acceptance checks). Workstreams: isolation PPY-e0c34a; data model PPY-15945e; serving PPY-d63ce1; provisioning and lifecycle PPY-cada52; metering and cost control PPY-e0fd12; site as data PPY-f8ec52 (with PPY-31efef and PPY-2a44b2); Threat Intelligence PPY-fe8bc6 and the dedicated tier PPY-4f5fb1; reader features PPY-149b82; governance PPY-84abde and docs PPY-02227e.
