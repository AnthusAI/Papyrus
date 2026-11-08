# Many sites on one Papyrus: the multi-tenant architecture (PPY-25ffa3)

> Status: design, for Ryan to read and decide. Nothing on this page is built. The work is planned on the PPY board under initiative PPY-25ffa3; the milestones are epic PPY-6a6357. Facts about the code were checked on `origin/develop` at 23fabe1d (2026-11-08); facts about Prospectus on its `develop` at 8b8e6b8 (2026-11-07). Where something was not checked, it says so.

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
5. **Threat Intelligence can move at milestone M5**, after isolation is enforced (M3) and shared serving and site-as-data work (M4). The first outside paying customer is M8, after an external security review and Prospectus's billing work.

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

- Built: Accounts and memberships; the weekly usage quota with `check`, `usage` and `reservations` routes (`docs/QUOTA.md`).
- Agreed, not built: cost accounting in microdollars per Account, app and deployment, with shared resources split by each customer's reported usage (`docs/COST_ACCOUNTING.md`).
- Built but limited: billing lines per product per Account with interval plans; "pricing is out of scope"; Stripe not built; billing never suspends access on its own (`docs/BILLING.md`).
- **Products are one reviewed file entry per site** (`accounts/papyrus-sites.json`: a Cognito client and review id per site). Self-serve sign-up needs one shared `papyrus` product with a deployment per site.
- The newsroom already reads a "selected account" from the Prospectus session (`lib/prospectus-tenant.ts`) and today maps tenant = Account (`lib/tenant-keys.ts`, `tenantIdForProspectusAccount`).

## The target architecture

One artefact, two ways to run it. The **shared stack** is the normal Papyrus backend deployed once in "shared" tenancy mode, ideally in its own AWS account. A **dedicated site** is the same backend with one fixed tenant. The renderer, components, content model and rules are identical; only where configuration comes from, where pages are written and who may use IAM differ.

```text
 reader ──> <site>.apyr.us or custom domain
              │
              ▼
   CloudFront (one distribution) ── edge function: host → tenant (KeyValueStore)
              │                               rewrites /x/ → /sites/<tenant>/x/
              ▼
   S3 (one bucket): sites/<tenant>/...  (pages, renditions, data files, brand.css)
              ▲
              │ projection (per-tenant lease, fair-share queue)
              │
 editor ──> newsroom.apyr.us (one newsroom app, Google sign-in, tenant switcher)
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

A mandatory adversarial suite (PPY-29f730), generated from the schema so a new model or function without a case fails the build. It tries every model operation across tenants, every custom mutation with foreign ids, subscriptions, storage, search (the vector index and the title-word table), snapshot files, the edge (host spoofing, path tricks), the reader API and exports. It gates every release to the shared stack (PPY-f7ce77). An internal security review before isolation is claimed and an external one before the first outside customer (PPY-3ff465).

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
- **Default subdomains** on one wildcard certificate (recommended `<site>.apyr.us`). **Custom domains** in every plan: the tenant creates DNS records we show, a workflow issues the certificate and adds the host. No Amplify domain associations (they throttle and refuse cross-account host names).
- **One newsroom host** for every tenant (Cognito allows 100 callback URLs per app client).
- **Freshness.** Pages are fresh within the cache lifetime (one hour) with no purge on save. `update-live` and refresh still purge exact paths for that tenant, capped at 25 per call, metered to the tenant. The publish path never sends `/*` on the shared distribution. The 1,000 free paths a month belong to the AWS account, so no tenant is promised them.
- **Fair projection.** The lease is per tenant; bulk work (re-renders, snapshots, re-projection after a release) goes through one queue with the tenant as the message group, so one tenant's big job cannot hold everyone up.
- **Cost per tenant** is measured on staging before pricing (PPY-04ce84): storage, requests and bytes served, edge function and KeyValueStore reads, projection time and writes, API requests, model spend, purged paths and email.

## Site as data and the brand pack

A shared-tier site is data, never code: a **SiteConfig** document (name, tagline, purpose line, sections, nav order, home template, footer links, analytics id, consent region policy, which feature blocks are on), a **BrandPack** (logo, colours for light and dark, fonts from an allow-list, under the validator), and pages. Customers cannot set in v1: hooks or any code, arbitrary CSS, sizes, spacing, the image ratio, borders, URL style, base path, pattern redirects, the image pipeline, cache settings or plugins (plugins are plan entitlements). The renderer reads these from the site store at run time on the shared stack and refuses to load hooks. A brand change writes one small stylesheet of custom properties; the core stylesheet is one shared file per release. Live preview renders one page from unsaved settings. Machines on Machines stays a dedicated site; core tests use a fictional fixture with its structure, so the layout is tested without MoM becoming a tenant.

## Metering and spend

Papyrus reports usage to Prospectus in Prospectus's own item kinds (PPY-3fd951): model tokens per model, images, web searches, function GB-seconds, Batch vCPU-seconds, API requests, estimated DynamoDB units, S3 writes, purged paths, emails; daily, storage per tenant prefix and requests and bytes per host. Model work checks the tenant's Account quota first and stops cleanly when the budget is used (PPY-889ab5); serving pages never depends on it. Shared resources are tagged `anthus:account=shared` and Prospectus splits their cost by the reported usage. Noisy neighbours are slowed by limits learned from each tenant's own traffic, not fixed caps.

## Threat Intelligence first

TI's rows carry no tenant today. The move is a full copy into a tenant of the shared stack (`copy-backend --stamp-tenant threat-intelligence` extended to every model), a rehearsal on staging with every URL compared, then a cut-over day: freeze, final copy (the second run must change nothing), add `threat-intelligence.anth.us` as a custom domain, switch the alias record to the shared distribution, verify, open the shared newsroom to TI's editors. Rollback for 14 days by switching the alias back and copying any new edits back. Done after 14 green days; then the old backend is retired with approval. Pilobolus is the recommended second site. Shipped, Anth.us and Machines on Machines stay dedicated for now; Distinctive Mark stays dedicated until its staged upgrade.

## Risks

1. **A cross-tenant leak** through a path the rules do not cover (a function's schema-wide grant, IAM, a subscription, search, a snapshot file). Mitigation: claims-based rules, functions that take the tenant from the caller, the generated adversarial suite as a release gate, two security reviews.
2. **The claim design does not work in Amplify** for index lists or subscriptions. Mitigation: three-day spike first, fallback named in advance.
3. **Invisible rows after the breaking step**: a row without `tenantId` disappears for its editors. Mitigation: backfill reports must show zero tenant-less rows before stage 2; stage 2 is a rules-only release that can be rolled back.
4. **Cost multiplies by tenant count**: whole-corpus snapshots, whole-table intake, wildcard purges. Mitigation: PPY-7f1e54, PPY-ee02b8, PPY-d647ee in M1; no wildcard on the shared stack; call-count tests at 50 tenants; load test before TI moves.
5. **Wrong host routing** sends one tenant's host to another's pages. Mitigation: only workflows write the KeyValueStore, with read-back; a synthetic tenant-marker check.
6. **Prospectus is not ready** for self-serve: products per site, no usage pricing, no Stripe, no automatic suspension. Mitigation: a spike turns each gap into a Prospectus issue; the shared tier serves our own sites (TI) long before outside customers.
7. **Noisy neighbours** on the projection, the API's request rate or the account's Lambda concurrency. Mitigation: per-tenant lease, fair queue, learned limits, the shared stack in its own AWS account.
8. **One bad release breaks every tenant.** Mitigation: staging shared stack first, golden renders, browser matrix, release gate, rollback runbook.
9. **Adopting every dedicated site** to a fixed tenant is a long, per-site data migration. Mitigation: one site at a time, Pilobolus first, Anth.us last and only on instruction.
10. **Restoring one tenant's data** is hard because point-in-time restore works per table. Mitigation: a rehearsed runbook (restore into new tables and copy back only that tenant's rows).

## Decisions only Ryan can make (my recommended default in brackets)

1. Is a tenant one **site** owned by an Account (one Account may own several sites), rather than the Account itself? [Yes: tenant = site. Today's code maps tenant = Account.]
2. Should the shared stack live in **its own AWS account** rather than papyrus-production? [Yes: separate blast radius, Lambda concurrency and cost line.]
3. Which **domain** for default subdomains and the shared newsroom? [`<site>.apyr.us` and `newsroom.apyr.us`.]
4. Ask Prospectus for **one `papyrus` product with a deployment per site** instead of a product per site? [Yes; required for sign-up with no human step.]
5. Does a **past-due** account become read-only automatically? Prospectus billing never suspends today. [Yes after 14 days past due: editing becomes read-only, the public site stays up, export stays available; nothing is deleted until 30 days after cancellation.]
6. **Freshness promise** for the shared tier? [Live within one hour by default; "Update live now" for urgent pages, each purge metered as usage, 25 paths per call.]
7. Do **dedicated sites** drop the group rules after adopting their tenant, so both tiers run one rule set? [Yes, one site at a time.]
8. **Analytics** on tenant sites: only the tenant's own measurement id, never ours without disclosure? [Yes.]
9. **Reader identity** separate per site, so no tenant can link its readers to another's? [Yes.]
10. **Budget stop**: when a tenant reaches its weekly model budget, does model work stop (hard ceiling) or continue as billed overage? [Stop model work; serving and editing continue.]
11. **Grace period** before a cancelled tenant's data is deleted? [30 days, export available throughout; backups age out on their schedule, stated in the terms.]
12. **Per-tenant restore**: promise it, or best effort? [Best effort with a rehearsed runbook in v1; not a contractual promise.]
13. **Subscriptions off** on the shared stack, with the topic-steering workspace refreshing by query? [Yes.]
14. **Agents for a customer** act only through that customer's signed-in session; IAM is for platform staff. [Yes.]

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
- The state of Prospectus's lifecycle events (kanbus-6efecd).

## The plan on the board

Initiative PPY-25ffa3; milestones epic PPY-6a6357 (M0 to M8, one task each). Workstreams: isolation PPY-e0c34a; data model PPY-15945e; serving PPY-d63ce1; provisioning and lifecycle PPY-cada52; metering and cost control PPY-e0fd12; site as data PPY-f8ec52 (with PPY-31efef and PPY-2a44b2); Threat Intelligence PPY-fe8bc6 and the dedicated tier PPY-4f5fb1; reader features PPY-149b82; governance PPY-84abde and docs PPY-02227e.
