# Many sites on one Papyrus: the multi-tenant architecture (PPY-25ffa3)

> Status: design, updated 2026-11-13 with Ryan's decisions of that day (no new AWS account; D2, D7, D8, D12, D19 accepted; D10 answered no; the breaking steps approved only as gated steps). The first additive building blocks are merged to `develop` (listed under [What exists today](#built-since-2026-11-08-on-develop)); isolation is not enforced anywhere yet and no shared stack exists. The work is planned on the PPY board under initiative PPY-25ffa3; the milestones are epic PPY-6a6357. Facts about the code were checked on `origin/develop` at 810c6927 (2026-11-13); facts about Prospectus on its `develop` at 8b8e6b8 (2026-11-07), updated from `develop` at a329ee1 (2026-11-08) for the Prospectus status, provisioning and security-review sections (not re-checked on 2026-11-13). Where something was not checked, it says so.

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
2. **The API does not need a big redesign.** Existing queries and mutations keep their shape. What changes: an optional `tenantId` field on 52 models (additive, merged in #1370); six new models (additive, new tables); tenant prefixes inside existing index values (a data change, not a schema change); one new index on each of about nine tables that have no way to list one tenant's rows; and two breaking steps at the end: removing the global group rules on the shared stack, and making `tenantId` required there. The table in [Schema changes](#schema-changes-model-by-model) lists every model.
3. **Isolation is enforced in the API rules, through claims.** A session acts for one tenant at a time; the token carries one claim per role (`papyrus_tenant_editor = alpha`); every tenant model's rule compares the claim with the row's `tenantId`. The offline half of the spike (PPY-9f3de0; #1371, #1372) says Amplify can do this, with three conditions: the claims must be on the access token (pre-token trigger version 2, Cognito Essentials), `tenantId` needs a field-level lock, and lists need tenant-prefixed index partitions. The runtime half waits on decision D9. The fallback stays named.
4. **Serving is one bucket and one distribution** with each tenant under its own prefix and a small edge function that maps the host name to the tenant. Pages are fresh within the cache lifetime (one hour); an editor can still push one page live now, for that tenant only, never with a wildcard.
5. **Threat Intelligence can move at milestone M5**, after isolation is enforced (M3) and shared serving and site-as-data work (M4). **M7 is the first point at which launching a site is a data change only**, and it is when the design partner's three sites launch, directly on the shared tier (never dedicated first). Earliest realistic M7 is about five weeks out (around 2026-12-11). Public self-serve sign-up is M8, after Stripe in Prospectus.
6. **No new AWS account** (Ryan, 2026-11-13). The shared tier runs in an existing account, recommended the Papyrus production account. It is kept apart from the dedicated sites by separate stacks, its own encryption key, IAM boundaries, reserved capacity and per-stack alarms and budgets. Admin credentials on that account and the account-wide quotas reach both tiers; that is the accepted trade-off. See [Isolation inside an existing account](#isolation-inside-an-existing-account).

## What exists today (verified)

### Isolation

- Five models are fully tenant-scoped: Item, PublishedItem, MediaAsset, PublishedMediaAsset and NewsroomSection carry `tenantId` and tenant-prefixed index values, and a tenant client reads and writes only its own rows (`docs/multi-tenancy.md`). Since #1370 every other tenant-owned model (52 in all) has an **optional** `tenantId` that a tenant client stamps on write, but nothing reads it and no index value is prefixed yet, so knowledge, conversation, assignment, procedure, review, editorial-check, edition, tag, proposal, reader-steering and sign-up rows are still not isolated. The generated inventory (#1481) counts 67 models: 27 have an index that can list one tenant once its values are prefixed, 32 need a new `tenantId` index, 3 are global by design and 5 have no `tenantId` field.
- Every rule grants by Cognito group (`editor`, `admin`, `curator`), never by tenant (`amplify/data/schema.ts`). An editor of one site who could reach another site's API would see everything.
- Six read-only models (PublishedItem and its siblings) allow **guest** reads through AppSync.
- Reference, Message and MessageThread have **realtime subscriptions** on; the topic-steering workspace subscribes to Reference changes. With group rules, every editor would receive every tenant's events.
- Functions learn their tenant from a **build variable**, `PAPYRUS_TENANT_ID`, copied into five functions by `amplify/site-backend.ts` (around line 490), and the schema gives every function access to every model (`functionGrants`). On a shared backend a function would act for whatever tenant its variable names.
- Storage rules give editors write and delete on all of `media/*` and `newsroom/*`; nothing mentions a tenant (`amplify/storage/resource.ts`).
- Six DynamoDB tables outside AppSync have no tenant in their keys: the newsletter table, the title-word index, public-form limits, reader and signup rate counters, and the remote-login tables. Neither does the S3 Vectors knowledge index.
- The projection lease (one projection of a site at a time) is keyed by the **bucket name** (`src/papyrus_content/projection/lease.py`), so on a shared bucket all tenants would queue behind one lock.
- The adoption tools (`content adopt-tenant-data`, `content copy-backend --stamp-tenant`) cover only the five tenant models.

### Built since 2026-11-08 (on develop)

All additive: no dedicated site changes behaviour, and none of it isolates anything yet.

- **Optional `tenantId` on every tenant-owned model** (#1370, PPY-94d609): 52 models, both schema definitions, checked by the schema parity test. UserProfile, UserIdentity and PublicHandleClaim stay global.
- **Tenant, TenantMembership and TenantDomain models** (#1393, PPY-31c45c), in the optional model group `tenancy`. Only the operator group has access until the claims exist; nothing reads or writes them yet.
- **Tenancy mode switch** (#1374, PPY-46635e): `tenancy: { mode: "shared" }` in the site backend config sets `PAPYRUS_TENANCY_MODE=shared` on every function; code asks `is_shared_stack()` / `isSharedStack()`. A site with no setting synthesises the same template as before.
- **Projection output prefix** (#1391, PPY-16d75b): a projection can write under `sites/<tenant>/`, separate from `urls.basePath`, and refuses keys outside its prefix. Dedicated sites write exactly where they did.
- **Generated isolation cases** (#1392, PPY-65e5a9): every cross-tenant case is generated from the schema into a fixture and a feature file, so a new model without a case fails CI. The cases are listed, not yet run against a shared stack.
- **Auth spike, offline half** (#1371 PPY-867f76, #1372 PPY-f4d892; findings in `docs/plans/tenant-claims-spike-1.md` and `-2-findings.md`). Role claims compared with `tenantId` work in the resolvers Amplify generates, with three findings that change the design: (1) the Amplify data client sends the **access token**, so the claims must be on it, which needs the pre-token-generation trigger **version 2** (Amplify's helper wires version 1, so a CDK override) and the Cognito **Essentials** plan; (2) `tenantId`, and any field in a tenant-prefixed key, needs a **field-level lock** (create and read, never update), otherwise an editor can move a row into another tenant; (3) base `list` is a scan with a post-filter, so lists on the shared stack must use **tenant-prefixed index partitions** to return full pages. Also: the Google sign-in flow cannot pass the chosen site to the trigger, so the "current site" must be stored server-side and read by the trigger. Nothing was run against AWS; the runtime half waits on D9.
- **GSI ledger** (#1388, PPY-8f2c4f): CI fails a change that adds more than one index per table per release or passes the limit of 20, and prints the release order pending indexes need.
- **Tenant key inventory** (#1481, PPY-cd5926): `docs/tenant-key-inventory.md`, generated from the schema and checked in CI. It classifies every index partition as tenant-prefixed, corpus-prefixed, record id or global and lists the 32 models that need a `tenantId` index.
- **SiteConfig v1 schema** (#1390, PPY-ee1e02): `src/papyrus_content/site_config/` with a JSON schema, a validator that refuses settings outside the v1 surface (hooks, custom CSS, sizes, URL style, plugins) naming the setting, and a converter to and from `projection.json`.
- **TenantContext builder** (#1482, PPY-cc8a4c): `build_tenant_context` (Python) and `buildTenantContext` (TypeScript) build `{tenantId, roles, mode, operator}` from the AppSync identity, refuse claims naming two tenants and, on a shared stack, any call that cannot name exactly one tenant. Shared test vectors. No handler uses it yet.
- **Cost tags** (#1327, PPY-f98e05): stacks are tagged `anthus:app`, `anthus:account`, `anthus:deployment` and `anthus:cost-key` with the vendored `@anthus/cost-accounting` package and checked in CI; shared resources such as the projection lease table carry `anthus:account=shared`.

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

One artefact, two ways to run it. The **shared stack** is the normal Papyrus backend deployed once in "shared" tenancy mode, as its own CloudFormation stacks inside an existing AWS account (recommended: the Papyrus production account; no new account, Ryan 2026-11-13; see [Isolation inside an existing account](#isolation-inside-an-existing-account)). A **dedicated site** is the same backend with one fixed tenant. The renderer, components, content model and rules are identical; only where configuration comes from, where pages are written and who may use IAM differ.

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

- **Editors and agents.** A person signs in with Google on the one newsroom host and picks a site; the choice is stored server-side as the person's current site, because the Google flow cannot pass it to the token trigger (spike finding). A Cognito pre-token Lambda (trigger version 2, so the claims land on the access token the data client sends) reads their `TenantMembership` row for that site and writes one claim per role (`papyrus_tenant_admin`, `_editor`, `_curator`, `_member`, each holding the tenant id). Switching site re-issues the token. Prospectus says who belongs to an Account; `TenantMembership` says what role they have on a site and is granted only to Account members. The token Lambda reads only the local table, so sign-in never waits on Prospectus. Agents acting for a customer use that customer's signed-in session (remote login), not an IAM role.
- **Functions.** Each function builds its tenant from the caller's claims and uses the tenant-scoped client for every read and write. An IAM call must name the tenant and is allowed only for the platform operator role.
- **Readers.** The reader API takes the tenant from the host the page was served on (looked up in `TenantDomain`), never from the browser's request body.
- **Background work.** Monitors, knowledge runs and scheduled jobs carry an explicit tenant and write an audit line.

### Why claims rather than the alternatives

| Option | Why not (or why) |
| --- | --- |
| One Cognito group per tenant (`alpha-editor`) | Groups appear in every token (a member of many sites gets a huge token), the pool allows 10,000 groups, and Amplify's group rules cannot compare a group with the row's tenant without listing groups on every row. |
| A Lambda authoriser on the API | A function call on every request (cost, latency), and Amplify's model rules then become all-or-nothing, so every row check moves into hand-written resolvers. |
| **Role claims compared with `tenantId`** (recommended) | Amplify supports owner rules that compare a field with a chosen claim. One rule per role gives "right tenant AND right role". The offline half of spike PPY-9f3de0 (#1371, #1372) confirmed it in the generated resolvers, with a field-level lock on `tenantId`, tenant-prefixed index partitions for lists, claims on the access token (trigger version 2, Cognito Essentials), and subscriptions filtered per tenant (they stay off on the shared stack anyway). The runtime half, against a real pool and API, waits on D9. Fallback if it fails: tenant models reached only through custom queries and mutations whose resolvers read the claims. |

### Rolling out the rules without breaking anyone

1. **Stage 1, additive** (PPY-06ae68): add the tenant rules beside the group rules, with the field-level lock on `tenantId` and on every field in a tenant-prefixed key. Rules are OR-ed, so nothing changes yet and nothing is isolated yet.
2. **Backfill**: every row gets its tenant and prefixed keys (PPY-8f9462).
3. **Stage 2, breaking, shared stack only** (PPY-bdc4ee): stop generating the global group rules. Now only claims grant access. **Gated** (below).
4. **Stage 3, breaking, shared stack only** (PPY-b99fc0): `tenantId` becomes required. **Gated** (below).
5. **Dedicated sites** adopt their fixed tenant one at a time (PPY-13fbea), then drop the group rules too, so both tiers end on one rule set.

**The gate for the breaking steps** (Ryan, 2026-11-13). Stage 2, stage 3 and switching the shared stack's sign-in over to the role claims are approved in principle, as gated steps only. Each runs only when all three hold:

1. the cross-tenant isolation suite (PPY-29f730) has passed on the staging shared stack;
2. the first security review (gate 1, PPY-3ff465) has passed;
3. Ryan has said go for that step, at the time it is about to run.

An agent may prepare each step (the change, its release notes, its rollback) but never runs it without the third condition. Passing the gate for one step does not open it for the next.

### Proving isolation

A mandatory adversarial suite (PPY-29f730), generated from the schema so a new model or function without a case fails the build (the generator is merged, #1392; running the cases against a shared stack is not). It tries every model operation across tenants, every custom mutation with foreign ids, subscriptions, storage, search (the vector index and the title-word table), snapshot files, the edge (host spoofing, path tricks), the reader API and exports. It gates every release to the shared stack (PPY-f7ce77). An internal security review before isolation is claimed and an external one before the first outside tenants, the design partner's sites at M7 (PPY-3ff465, D22).

## Isolation inside an existing account

Ryan (2026-11-13): no new AWS account. We are at our limit on accounts and changes to that limit take days. So the shared tier lives in an account we already have.

**Recommended: the Papyrus production account.** The Papyrus sites, their DNS zones (`apyr.us`, `anth.us`, `pilobol.us`), the stack pipeline and Threat Intelligence's current backend already live there, so the wildcard records for `*.p.apyr.us`, TI's custom domain and TI's copy into the shared stack all stay inside one account, and no cross-account trust, SSO, SES or DNS delegation has to be set up. Which account to use is a **confirmation for Ryan** before the shared stack is first created. (No account id is written in this repository; account names only.)

Tenant isolation (rules, claims, prefixes, the suite) is the same in any account. What changes is how the shared tier is kept apart from the **dedicated sites** that share the account. Five layers do that.

### 1. Separate stacks, made only by the pipeline

- The shared production stack and the shared staging stack are separate CloudFormation stacks with their own name prefixes, for example `papyrus-shared-*` and `papyrus-shared-staging-*`. No dedicated site's stack shares a name prefix with them.
- Staging also lives in an existing account. Recommended: the same account, with the distinct staging prefix, unless an existing Papyrus staging account exists. **Not verified**: no Papyrus staging account is named in this repository.
- Both are created and changed only by the release pipeline from templates in Git, through a change set the pipeline checks (the `infra/pipeline` deployer and its allowed-changes list). Nothing is created by hand or by an ad hoc CLI call, including the deploy roles.

### 2. One customer-managed KMS key per shared stack

- Each shared stack (production and staging) has its own customer-managed KMS key. It encrypts that stack's DynamoDB tables, its S3 bucket, its SSM SecureString parameters (including the later bring-your-own Google client secrets) and its CloudWatch log groups.
- The key policy grants use of the key only to that stack's own roles and the platform operator role. A dedicated site's roles therefore cannot decrypt shared-tier data even if an IAM policy were too broad, and the shared stack's roles get no grant on any dedicated site's key.
- Key administration (policy changes, scheduling deletion) is limited to the pipeline's CloudFormation role. Deletion has the longest waiting period.

### 3. IAM boundaries

- Every role the shared stack creates carries a **permissions boundary** that allows actions only on resources named with the shared stack's prefix or tagged `anthus:deployment=shared` (the exact tag key and value are fixed when the template is written). A grant that slips past review still cannot reach a dedicated site's tables, bucket or functions.
- Every dedicated site's roles get an explicit **deny** on shared-stack resources (by name prefix and tag), added through the app-shell and site-backend templates, so the reverse is also closed.
- The pipeline's deploy role for the shared stack may create change sets only on stacks with the shared prefix. The existing per-site deploy roles are not widened.
- The **platform operator role** is the only IAM path to tenant data. Every IAM call on the shared stack must name a tenant (TenantContext refuses one that does not), and its use is audited through CloudTrail and the append-only audit trail.

### 4. Account-wide quotas are now shared and must be budgeted

These quotas are per account and per Region, so the shared tier and the dedicated sites draw from one pool. Each needs a share agreed before launch. Limits that can adapt are learned from traffic (no arbitrary fixed numbers); the fixed ones are AWS quotas we either fit inside or ask to raise. **Current values were not checked** (no AWS reads for this note).

| Quota | Shared tier adds | How it is handled |
| --- | --- | --- |
| Lambda concurrent executions | grows with tenant traffic | Reserved concurrency on each shared function, sized from measured staging and production traffic and revised from data, so the shared tier can neither starve the dedicated sites nor be starved by them. Unreserved headroom stays for the dedicated sites. |
| AppSync request rate | one API, grows with tenants | The rate is per API, so the dedicated sites' APIs are unaffected; the shared API's quota is checked and raised before launch if measured traffic needs it. Per-tenant slowing learned from each tenant's own traffic (PPY-f40a02). |
| CloudFront distributions and functions | fixed: one distribution per shared stack plus one edge function and one KeyValueStore | Two distributions (production and staging) against the account limit. Custom domains are alternate names on the shared distribution, so they grow the per-distribution name and certificate limits, not the distribution count (or the multi-tenant distribution model, spike PPY-3b3cc3). |
| ACM certificates | one wildcard per shared stack, plus one per custom domain | Grows with custom domains. The account's certificate quota is checked before custom domains open to every plan. |
| Cognito user pools | fixed: one per shared stack | Two pools. The pool's own limits (app clients, identity providers, 100 callback URLs per client) are what the design is shaped around. |
| S3 buckets | fixed: one or two per shared stack | Tenants are prefixes, never buckets. |
| DynamoDB tables and on-demand throughput | fixed table count (one per model, about 70 per stack); throughput grows with tenants | Table count against the account limit for two stacks. On-demand throughput limits are per table; the account-wide throughput limit is checked. |
| CloudFormation stacks | fixed: a handful per shared stack (Amplify nests stacks) | Counted against the account's stack limit alongside every dedicated site. |
| KMS requests | grows with tenant traffic | Two keys' requests count against the account's per-Region request rate; table and bucket keys are configured to cache data keys where the service allows (S3 bucket keys). |

### 5. Alarms, budgets and cost by tag

- **Budgets per stack.** AWS Budgets filtered on the cost-allocation tags from #1327 (`anthus:app`, `anthus:account`, `anthus:deployment`), one budget for the shared production stack and one for staging, each alerting the operator. The tags must be activated as cost-allocation tags in billing (not verified).
- **Alarms per shared stack.** CloudWatch alarms on function errors, throttles and concurrency against the reserved share, AppSync errors and throttles, DynamoDB throttles, the projection dead-letter queue and the edge's purge count. Separate from any dedicated site's alarms.
- **Cost by tag instead of by account.** Shared resources are tagged `anthus:account=shared` and Prospectus splits their cost by each tenant's reported usage, as already planned (kanbus-f45f7f). A separate account would have given a clean line on the bill; tags give the same line in Cost Explorer once activated.

### Blast radius: a separate account compared with the shared existing account

| Failure or compromise | Reaches, with a separate account | Reaches, inside the existing account | Mitigation |
| --- | --- | --- | --- |
| A shared-stack role is compromised | the shared tier only | the shared tier only, if the boundary and key policy hold; without them, dedicated sites too | Permissions boundary, the shared KMS key policy, denies on dedicated resources, least-privilege roles, the isolation suite. |
| A dedicated site's role is compromised | that site only | that site, and shared-tier data only if both the deny and the key policy fail | Explicit deny on shared resources; shared data encrypted with a key the site's roles cannot use. |
| A bad shared release | every shared tenant | every shared tenant; dedicated sites only through shared quotas (for example a concurrency runaway) | Staging stack first, release gate, reserved concurrency, rollback runbook. |
| A runaway tenant (load or spend) | the shared tier | the shared tier, and the dedicated sites through shared account quotas | Learned per-tenant slowing, the weekly AI budget stop (D19), reserved concurrency in both directions, per-stack alarms and budgets. |
| An account-wide quota is exhausted | the tier that exhausted it | **both tiers** | Reserved concurrency, quota checks before launch, alarms at a share of each quota, raise requests made early. |
| An operator mistake with admin credentials | one account's tier | **both tiers** | Changes only through the pipeline and change sets; admin use rare, audited and short-lived; Retain policies on tables, buckets and zones; point-in-time recovery on. |
| Account suspension or a billing problem | one tier | **both tiers**, plus the DNS zones in the account | Budgets and alerts; a paid-up billing setup; no mitigation inside the account for a suspension. |

The trade-off: admin credentials on the account reach both tiers, and the account-wide quotas are shared. A separate account would have contained both. Ryan has chosen to accept that rather than wait on a new account. The layers above contain every role-level failure; they do not contain an account-level one.

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
- **Freshness.** Pages are fresh within the cache lifetime (one hour) with no purge on save. `update-live` and refresh still purge exact paths for that tenant, capped at 25 per call, metered to the tenant. The publish path never sends `/*` on the shared distribution. The 1,000 free paths a month belong to the AWS account, which the shared tier now shares with the dedicated sites in it, so no tenant is promised them.
- **Fair projection.** The lease is per tenant; bulk work (re-renders, snapshots, re-projection after a release) goes through one queue with the tenant as the message group, so one tenant's big job cannot hold everyone up.
- **Cost per tenant** is measured on staging before pricing (PPY-04ce84): storage, requests and bytes served, edge function and KeyValueStore reads, projection time and writes, API requests, model spend, purged paths and email.

### Public Suffix List entry for `p.apyr.us` (D12, decided)

Once `p.apyr.us` is on the Public Suffix List, browsers treat each `<site>.p.apyr.us` as its own site: one tenant's pages cannot set or read cookies for another tenant's subdomain or for `p.apyr.us` itself. Review usually takes weeks, so it is submitted early, off the critical path. Steps, checked against the list's guidelines (github.com/publicsuffix/list/wiki/Guidelines, read 2026-11-13):

1. Check that `apyr.us` has at least two years of registration left and keep it renewed with more than a year left; the list removes entries whose registration runs low.
2. Open a pull request to `github.com/publicsuffix/list` adding `p.apyr.us` in the PRIVATE section (between `===BEGIN PRIVATE DOMAINS===` and `===END PRIVATE DOMAINS===`), placed by company name, under a header of the form `// Anthus : https://anth.us/` and `// Submitted by <owner's name> <owner's contact address>`. The submitter must be the domain owner's authorised representative (Ryan), with an address at the owner that he controls; the address goes only in the pull request, never in this repository. The description says why (independent customer sites under one name), gives an example (`alpha.p.apyr.us` and `beta.p.apyr.us` are separate sites), the number of names (one), that it serves outside customers, and the registration commitment. `make test` passes before it is opened.
3. Add a TXT record `_psl.p.apyr.us` whose value is the pull request's URL, through the DNS template in Git (applied by the pipeline, never by hand), and keep it for as long as the entry exists; a missing record can get the entry removed.
4. Wait for review. The guidelines promise no review time. They say small or private projects are likely to be declined, so the description should show the shared tier serves outside customers.

Impact on the design: nothing on the shared tier may rely on a cookie scoped to `p.apyr.us`. The newsroom on `newsroom.p.apyr.us` keeps its session on its own host; the reader pages and the reader API keep any state on the tenant's own host. Custom domains are unaffected.

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

Papyrus reports usage to Prospectus in Prospectus's own item kinds (PPY-3fd951): model tokens per model, images, web searches, function GB-seconds, Batch vCPU-seconds, API requests, estimated DynamoDB units, S3 writes, purged paths, emails; daily, storage per tenant prefix and requests and bytes per host. Model work checks the tenant's Account quota first and stops cleanly when the weekly AI budget is used (PPY-889ab5; D19, decided): reading, editing and serving continue, and paid overage comes later as an opt-in (PPY-8a3c6a). Shared resources are tagged `anthus:account=shared` and Prospectus splits their cost by the reported usage. Noisy neighbours are slowed by limits learned from each tenant's own traffic, not fixed caps; because the shared tier shares an account with the dedicated sites, its functions also get reserved concurrency (see [quotas](#4-account-wide-quotas-are-now-shared-and-must-be-budgeted)).

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
3. The person picks a site (or the hint preselects it); the choice is stored server-side as their current site, since the Google flow gives the token trigger no caller-chosen value. The newsroom server calls **Prospectus `authorize`** with the person's verified identity and the **deployment** (site id) and gets back a yes or no, the capabilities and the billing standing (kanbus-3e5e82). Prospectus checks three things: the token is bound to that deployment (host or audience), the deployment's Account owns it, and the person is a member of that Account.
4. Cognito's pre-token-generation Lambda issues role claims for **that one deployment only**, and only when two things hold: `authorize` approved it, and the person has a `TenantMembership` row for it. The claims are `papyrus_tenant_admin`, `_editor`, `_curator` and `_member`, each holding the tenant id. If billing standing is restricted, it issues read-only claims. Switching site means a new token. The Lambda reads its own table only, so sign-in never waits on Prospectus at token refresh. Membership changes and standing changes arrive by events.
5. Every AppSync call carries that token (the access token, so the trigger is version 2). Each tenant model's rule compares the row's `tenantId` with the role claim (spike PPY-9f3de0, fallback named). `tenantId`, and every field in a tenant-prefixed key, cannot be changed after create (field-level lock). Lists go through tenant-prefixed index keys. No group rule grants anything on the shared stack (PPY-bdc4ee).
6. Every function builds a `TenantContext` from the AppSync identity's claims (PPY-cc8a4c; the builder is merged, #1482, and no handler uses it yet) and uses the tenant-scoped client for every read and write: DynamoDB, S3 under `tenants/<t>/` and `sites/<t>/`, the vector index and the tables outside AppSync. `PAPYRUS_TENANT_ID` is not used on the shared stack.
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
| Isolation | auth spike PPY-9f3de0 (offline half done; runtime half waits on D9) → session claims PPY-0bb0fd → functions take the tenant from the caller PPY-7dc463 → workers PPY-203ce2 → staging shared stack in the existing account PPY-daf673 → isolation suite green on staging PPY-29f730 and gate 1 PPY-3ff465 → **Ryan's go** → group rules removed PPY-bdc4ee (also waits for key prefixes → adoption PPY-8f9462) → **Ryan's go** → tenantId required PPY-b99fc0 → TI rehearsal PPY-e1d26f → TI cut-over PPY-e51189 | about 14 |
| Layout | card and brand pack slices → publication preset PPY-cf7e6e (largest item, about 8) → TI brand-neutral acceptance PPY-7e396d → TI cut-over; preset → starter template PPY-3aa10f → provisioning PPY-70a429 → review PPY-1da916 | about 16 |
| Prospectus | deployment records and shared sign-in (kanbus-271b4a, kanbus-3e5e82) → PPY-966ef5 → provisioning → joint review; lifecycle events (kanbus-6efecd, kanbus-b19d5a) → PPY-6cb44b → PPY-d7274f → deletion PPY-62f10d | about 11 plus Prospectus work and approvals |

```text
M0 spikes ──┬─> M2 additive data + claims ──> M3 isolation (staging shared stack) ──┐
            │                                                                     ├─> M5 TI cut-over ──┐
            ├─> M1 cost fixes + preset ─────────> M4 shared serving + site data ──┘                     ├─> M7 data-only launch
            │                                     └─> M6 metering ──────────────────────────────────────┤
            └─> Prospectus: deployments API, shared sign-in, lifecycle events, review ───────────────────┘
```

**Merged since 2026-11-08** (the first parallel wave): auth spike offline halves PPY-867f76 (#1371) and PPY-f4d892 (#1372); tenancy mode switch PPY-46635e (#1374); tenantId fields PPY-94d609 (#1370); tenant models PPY-31c45c (#1393); key inventory PPY-cd5926 (#1481); suite generator PPY-65e5a9 (#1392); output prefix PPY-16d75b (#1391); SiteConfig schema PPY-ee1e02 (#1390); GSI ledger PPY-8f2c4f (#1388); TenantContext PPY-cc8a4c (#1482); cost tags PPY-f98e05 (#1327). Still open from that wave: the CDN spike PPY-7cd7a2 (its runtime half, PPY-3b3cc3, waits on D9), core cards PPY-ecb656 and the brand pack validator PPY-7bc5b7.

**Waits on D9** (spikes in the personal sandbox account, still open): the runtime halves of the auth spike (PPY-9f3de0) and the CDN spike (PPY-3b3cc3). Everything else on the isolation chain up to the staging stack can proceed without them, but the staging stack should not be built on unproven claims.

**The shared account.** No new account is needed (Ryan, 2026-11-13), which removes "create the shared account" from Ryan's approvals and the new-account setup (SSO, SES, Google OAuth client, DNS delegation) from the risks. It adds three small items before the staging stack: Ryan confirms the account (recommended: the Papyrus production account), the shared-stack templates carry the key, boundary and deny layers, and the quota shares are measured and set.

**Not on the path to M7:** the ordering rule and native tokens (D4), bring-your-own Google client, overage billing, TI's 14-day close (D3), dedicated-site adoption (D13), managed upgrades, the cost model, preview, home templates, onboarding polish and reader features (D6).

**Schedule:** with six Papyrus agents and one Prospectus agent, a release every one to two days and approvals within a day, earliest realistic M7 is about five weeks out (around 2026-12-11; optimistic 2026-12-02; pessimistic late January 2027). The biggest risks to the date: the runtime half of the auth spike waiting on D9 or failing (adds 1 to 2 weeks), Prospectus capacity or approvals, scope creep in the preset, and the three gated go decisions for the breaking steps (each needs Ryan at the time; a day's wait each). Not having to create an account removes the days a new account would have taken.

## Milestone acceptance

Each milestone task on the board lists its Gherkin scenarios (by name and feature file) and acceptance checks. In short:

| Milestone | Key scenarios | Acceptance checks |
| --- | --- | --- |
| M0 Decisions and spikes | "A token for alpha cannot touch beta's Item"; "An index list returns full pages for the caller's tenant"; "Purging alpha's page leaves beta's cached"; "The inventory is current" | yes/no per spike question with evidence; sandbox stacks destroyed; decisions answered |
| M1 Cost fixes and layout | "Cost does not grow with corpus or tenant count"; "A site picks the preset in configuration only"; "The shared suite passes for a second brand" | no whole-table read; TI on the preset with no MoM change; policy checks in both themes |
| M2 Additive data | "A client without a tenant writes exactly as before"; "A member of two sites acts for one at a time"; "A single-tenant backend is copied into a tenant completely" | dedicated sites unchanged; zero tenant-less rows on a Pilobolus copy; one index per table per release |
| M3 Isolation | "A Cognito group alone grants nothing on the shared stack"; "A model with no isolation case fails the build"; "A guest cannot list published rows on the shared stack"; "A dedicated site's role cannot read the shared stack's data" | staging shared stack created by the pipeline as its own stacks in the existing account Ryan confirmed (recommended: the Papyrus production account), with its own KMS key, permissions boundaries and denies; suite green twice on staging; gate 1 signed off; **then, as gated steps, each only after the suite has passed on staging, gate 1 has passed, and Ryan has said go for that step**: group rules removed (PPY-bdc4ee), `tenantId` required (PPY-b99fc0), sign-in switched to the role claims |
| M4 Shared serving | "Each host shows its own tenant"; "A large publish never becomes a wildcard"; "A new site needs no sign-in configuration change"; "A runaway tenant cannot use the dedicated sites' concurrency" | tenant-marker check clean; fixed callback list; no `/*` purge; load test; reserved concurrency and the account quota shares set from measured traffic; per-stack alarms and tag budgets live |
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
3. **Invisible rows after the breaking step**: a row without `tenantId` disappears for its editors. Mitigation: backfill reports must show zero tenant-less rows before stage 2; stage 2 is a rules-only release that can be rolled back, and runs only through the gate (suite green on staging, gate 1 passed, Ryan's go).
4. **Cost multiplies by tenant count**: whole-corpus snapshots, whole-table intake, wildcard purges. Mitigation: PPY-7f1e54, PPY-ee02b8, PPY-d647ee in M1; no wildcard on the shared stack; call-count tests at 50 tenants; load test before TI moves.
5. **Wrong host routing** sends one tenant's host to another's pages. Mitigation: only workflows write the KeyValueStore, with read-back; a synthetic tenant-marker check.
6. **Prospectus is not ready** for self-serve: products per site (each with its own pool, client and compute role, capped at about 40), no provisioning API, no invites by email, no lifecycle events, billing per deployment plan rather than usage, quota live for Babulus only. Mitigation: each gap is a filed issue (PPY-966ef5, PPY-6cb44b, PPY-8a3c6a, PPY-25e0d7); Prospectus has filed each (kanbus-b770c2) and raised them to priority 1 for the partner launch at M7; TI moves onto the shared tier before the partner's sites.
7. **Data-driven provisioning has no human gate**, so a flaw lets anyone who can pay create sites at scale. Mitigation: the provisioning security review (PPY-1da916): entitlement re-read from Prospectus, learned rate limits with an operator stop, input validation and moderation, an audit trail kept outside tenant data, replay keys, one-command takedown.
8. **Noisy neighbours** on the projection, the API's request rate or the account's Lambda concurrency. Mitigation: per-tenant lease, fair queue, limits learned from each tenant's traffic, and reserved concurrency for the shared functions so neither the shared tier nor the dedicated sites can starve the other.
9. **Shared account limits and blast radius.** The shared tier lives in an existing account (no new account, Ryan 2026-11-13), so account-wide quotas are shared with the dedicated sites, and admin credentials, an operator mistake or an account suspension reach both tiers. Mitigation: separate pipeline-made stacks, a KMS key per shared stack, permissions boundaries and denies, reserved concurrency, quota shares checked before launch, per-stack alarms and tag budgets, changes only through change sets ([blast radius](#blast-radius-a-separate-account-compared-with-the-shared-existing-account)). Accepted residual risk: an account-level failure reaches both tiers.
10. **One bad release breaks every tenant.** Mitigation: staging shared stack first, golden renders, browser matrix, release gate, rollback runbook.
11. **Adopting every dedicated site** to a fixed tenant is a long, per-site data migration. Mitigation: one site at a time, Pilobolus first, Anth.us last and only on instruction.
12. **Restoring one tenant's data** is hard because point-in-time restore works per table. Mitigation: a rehearsed runbook (restore into new tables and copy back only that tenant's rows).

## Decisions only Ryan can make

**Already decided (Ryan, 2026-11-07 and 2026-11-08):** the design partner's three sites launch directly on the shared tier at M7, never dedicated first; launching a site is a data change only, through one Prospectus `papyrus` product whose deployments are created by API, with its own security review; billing may change access (read-only 14 days past due, deletion 30 days after cancellation, export throughout); build cost accounting and test it on our sites and the partner's three; one shared Google OAuth client by default, a tenant's own client later; public sites at `<site>.p.apyr.us`; subscriptions off on the shared stack; Google sign-in only, never Cognito password users; usage pricing through Prospectus, no free tier.

**Decided by Ryan on 2026-11-13:**

| # | Decision |
| --- | --- |
| D2 | Yes: one editor sign-in address, `newsroom.p.apyr.us`, then the person picks the site. |
| D7 | Yes: Prospectus is the only creator of site (deployment) records. Papyrus reacts to its event and sweeps for missed ones. |
| D8 | Yes: Prospectus verifies custom-domain ownership; Papyrus handles the certificate, the edge and serving. |
| D10 | **No new AWS account** ("we are at our limit on AWS accounts and it takes days to talk them into changes"). The shared tier lives in an existing account; recommended the Papyrus production account, which Ryan confirms before the first shared stack is created. Design: [Isolation inside an existing account](#isolation-inside-an-existing-account). |
| D12 | Yes: register `p.apyr.us` on the Public Suffix List early; it takes weeks. Steps: [Public Suffix List entry](#public-suffix-list-entry-for-papyrus-d12-decided). |
| D19 | Yes: at the weekly AI budget, model work stops; reading, editing and serving continue. Paid overage later, as an opt-in. |
| Breaking steps | Stage 2 (group rules removed on the shared stack, PPY-bdc4ee), stage 3 (`tenantId` required on the shared stack, PPY-b99fc0) and the sign-in switch-over on the shared stack are approved in principle, as gated steps only: each runs after the isolation suite (PPY-29f730) has passed on staging and gate 1 (PPY-3ff465) has passed, and each still needs Ryan's go before it runs. See [the gate](#rolling-out-the-rules-without-breaking-anyone). |

**Still open, each with my recommended default.** If you do not answer, agents go ahead with the default. None of these defaults assumes a new or separate AWS account.

| # | Question, in plain words | Recommended default |
| --- | --- | --- |
| D3 | Can the partner's sites go live once TI has moved, without waiting for TI's 14 trouble-free days? | Yes. The 14 days still decide when TI's old backend is retired. |
| D4 | Leave the new sizing system (retiring the scaler) and the one ordering rule for every list out of the M7 path? | Yes. The layout ships on today's sizes; both follow after M7. |
| D5 | For the partner, does an operator create its sites in Prospectus and invoice it, rather than waiting for Stripe checkout? | Yes. Self-serve checkout comes at M8. |
| D6 | Do the partner's sites need reader votes and comments, live preview or the guided first-run setup at launch? | No; they follow after M7 unless the partner needs them. Please ask the partner. Same for custom domains (the plan supports them). |
| D9 | May agents run the spikes in the personal sandbox AWS account without asking each time? **Still open after 2026-11-13.** The runtime halves of the auth spike (PPY-9f3de0) and the CDN spike (PPY-3b3cc3) wait on it. | Yes, sandbox only, everything destroyed afterwards. |
| D11 | When a tenant later brings its own Google sign-in client, which system keeps its secret? Both had planned it. | Papyrus's shared stack (the sign-in pool that uses it), as an SSM SecureString; Prospectus records only that the site has its own client. |
| D13 | Keep our dedicated sites off the tenant data migration until after M7? | Yes, one site at a time afterwards, Pilobolus first, Anth.us last and only on your instruction. |
| D14 | Is a tenant one site (an Account may own several), rather than the whole Account? | Yes: tenant = site. |
| D15 | How fresh are shared-tier pages? | Live within an hour; "Update live now" for urgent pages, each purge counted as usage, 25 pages per click. |
| D16 | After adopting their tenant, do dedicated sites drop the old group rules too, so both tiers run one rule set? | Yes, one site at a time. |
| D17 | Analytics on tenant sites: only the tenant's own measurement id? | Yes, never ours without disclosure. |
| D18 | Keep each site's readers separate, so no tenant can link its readers to another's? | Yes (Prospectus already plans per-site reader ids). |
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
- Amplify owner rules with custom claims at runtime, against a real pool and API: index list page sizes, subscription filters, the field-level lock, and the access-token claims through a version 2 trigger on the Essentials plan (offline evidence only, #1371, #1372; the runtime half of PPY-9f3de0 waits on D9). The shared pool's Cognito plan is not chosen yet.
- Amazon SQS fair queues for the projection queue (measured in PPY-994bd0).
- AppSync's per-API request rate quota for a shared API.
- **The current values of every account-wide quota** in the account that will hold the shared tier, and how much of each the dedicated sites already use: Lambda concurrent executions, CloudFront distributions and functions, ACM certificates, Cognito user pools, S3 buckets, DynamoDB tables and account throughput, CloudFormation stacks, KMS request rate. Nothing was read from AWS for this note.
- Whether a Papyrus staging account exists (none is named in this repository), so the recommendation is the same account with a staging stack prefix.
- Whether the cost-allocation tags from #1327 are activated in billing, which tag-filtered budgets need.
- Whether the `apyr.us` zone, or a `p.apyr.us` zone, is already managed by a template in Git; if it is not, it is adopted by import before the `_psl` record is added. Whether `apyr.us` has two years of registration left, and whether the Public Suffix List reviewers accept the entry.
- Data volumes of TI's current backend.
- Cognito limits for several Google clients in one pool, and the OIDC route for a tenant's own Google client (spike PPY-8eca5b).
- Whether Prospectus will publish the Python usage sender (kanbus-40dc2a promises one; it is TypeScript only today), or Papyrus writes a twin against the same message format.
- Whether Prospectus will publish a `deployment.changed` event and a changed-since list route (asked on PPY-966ef5).

## The plan on the board

Initiative PPY-25ffa3; critical-path plan PPY-e38a2d (dispatch list in its first comment); milestones epic PPY-6a6357 (M0 to M8, one task each, each with Gherkin scenario names and acceptance checks). Workstreams: isolation PPY-e0c34a; data model PPY-15945e; serving PPY-d63ce1; provisioning and lifecycle PPY-cada52; metering and cost control PPY-e0fd12; site as data PPY-f8ec52 (with PPY-31efef and PPY-2a44b2); Threat Intelligence PPY-fe8bc6 and the dedicated tier PPY-4f5fb1; reader features PPY-149b82; governance PPY-84abde and docs PPY-02227e.
