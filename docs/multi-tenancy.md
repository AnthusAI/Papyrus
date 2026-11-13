# Multi-tenancy

One backend can serve several publications. A tenant is one publication's account; its id is lowercase letters, digits and hyphens. Set it with `--tenant <id>` on a command, or `PAPYRUS_TENANT_ID` for the whole shell (a signed-in CLI otherwise uses the tenant its site publishes, below). A command with no tenant behaves exactly as a single-tenant backend always has and writes nothing tenant-shaped.

A signed-in editor does not set the tenant by hand: the site publishes its own tenant id in `/.well-known/papyrus-site.json` (its `PAPYRUS_TENANT_ID` build variable; the sign-in file `papyrus-cli.json` is strict and never carries it), and the CLI uses it for the signed-in site that owns the endpoint. The order is `--tenant`, then `PAPYRUS_TENANT_ID`, then the site's. This is scoping, not authorization: the backend still decides what the session may do. It applies to the signed-in lane only (an operator on `PAPYRUS_GRAPHQL_AUTH=iam` sets the tenant as before), and `content adopt-tenant-data`, which must read every row, ignores it. Details: [CLI login](cli-login.md#the-site-file-tenant-and-version).

The key helpers live in `papyrus_content.tenancy`; `PapyrusGraphQLAuthoringClient(tenant_id=...)` applies them at the client boundary so callers never build tenant keys themselves.

## Tenancy mode

A backend is either `dedicated` (one stack per site, the default and what every site is today) or `shared` (one stack serving several tenants). Set it in the site backend config: `tenancy: { mode: "shared" }`. A site with no `tenancy` setting synthesises exactly the template it always did: `dedicated` adds nothing to any function, and an unset `PAPYRUS_TENANCY_MODE` means dedicated.

On `shared`, `amplify/site-backend.ts` sets `PAPYRUS_TENANCY_MODE=shared` on every function. Code never reads the variable itself; it asks `papyrus_content.tenancy.is_shared_stack()` in Python or `isSharedStack()` in `lib/tenant-keys.ts`. `scripts/test-tenancy-mode.ts` fails if any other file names the variable. `rulesForTenancyMode` in `amplify/data/schema.ts` is the helper the shared stack will use to vary access rules by mode; nothing uses it yet. Tests: `npm run test:tenancy-mode`.

## Tenant context in functions

A function builds the tenant it acts for once, with `build_tenant_context(identity, explicit_tenant=None)` in `papyrus_content.tenant_context` or `buildTenantContext(identity, { explicitTenant })` in `amplify/functions/shared/tenant-context.ts`, from the AppSync event's `identity`. It returns `{tenantId, roles, mode, operator}`. A signed-in caller's roles are the ones whose claim (`papyrus_tenant_admin`, `_editor`, `_curator`, `_member`) holds the tenant; claims naming two tenants are refused. An IAM caller (`operator` true) names its tenant explicitly. On a shared stack a call that cannot name exactly one tenant is refused before anything is read; on a dedicated stack the tenant is the fixed `PAPYRUS_TENANT_ID` (none when unset, as today) and a claim or explicit tenant that differs is refused. Every refusal is one typed error (`TenantContextRefusal`) with a `reason` code. The tenant never comes from the request body. Both builders read `features_backend/fixtures/tenant-context/vectors.json`. No handler uses it yet. Tests: `npm run test:tenant-context`.

## What the tenant models carry

Item, PublishedItem, MediaAsset, PublishedMediaAsset and NewsroomSection rows get a `tenantId`. The index values that would be global (`typeStatus`, `sectionStatus`, slug lookups) are prefixed with `<tenant>#`, media rows are listed, read, updated and deleted by their own tenant only (see [story pictures](#story-pictures-and-the-one-key-rule) for the key), and a tenant client lists, reads, updates and deletes only its own rows.

The generated [tenant key inventory](tenant-key-inventory.md) lists every model's indexes, whether each partition value is tenant-prefixed, corpus-prefixed, a record id or global, and which tables have no index that can list one tenant's rows; CI fails when it is stale or a new index is unclassified.

## Listing one tenant's rows

Export, deletion and usage need every row one tenant owns without reading a whole table (PPY-1ce06f). Every table that carries `tenantId` has a way to do it:

- An index whose partition is a status, a kind or a constant lists a tenant once that value carries the tenant prefix (the key-prefix step of the plan).
- References, and the other rows with a required `corpusId`, are listed corpus by corpus: a tenant's corpora are its own KnowledgeCorpus rows, and corpus ids are unique to a tenant. Reference gets no index of its own for this.
- The 30 tables where no index reaches every row have one sparse index partitioned on `tenantId` and sorted by `id`, named `list<Models>ByTenant` (for example `listReaderVotesByTenant`). Item and PublishedItem are among them: their tenant-prefixed indexes sort on `publishedAt` and so leave unpublished rows out, and `headStageKey` is on head rows only.

`PapyrusGraphQLAuthoringClient.list_tenant_rows(model, fields)` reads a tenant's rows of one of those tables through its `tenantId` index: one Query, followed page by page, never a Scan. The index query fields are declared once in `papyrus_content.tenancy.TENANT_LISTING_QUERIES`, and a test checks that map against the schemas. A sparse index holds only rows that carry a `tenantId`, so a tenant's list is complete only after the tenantId backfill (PPY-8f9462) has stamped every row.

The 30 indexes ship in one release, one per table (the GSI ledger, `features_backend/gsi-ledger.feature`, refuses a second new index on a table, and reads every plugin's and function's schema as well as the core one). A dedicated site creates them on its existing tables when it takes that release. Spec: `features_backend/tenant-listing-index.feature`.

## Tenant, membership and domain records

Three models hold the tenants themselves (PPY-31c45c). They are new tables, each created with all its indexes in one deploy, and they sit in the optional model group `tenancy` (`OPTIONAL_MODEL_GROUPS`), so a dedicated site can leave them out of a first deploy with `excludeModelGroups: ["tenancy"]`. Nothing reads or writes them yet.

| Model | Id | Fields | Indexes |
| --- | --- | --- | --- |
| `Tenant` | the site id (`validate_tenant_id`) | `accountId` (the Prospectus Account), `displayName`, `state` (`active`, `past_due`, `suspended`, `deleted_pending`, `deleted`), `stateKey` (`state#<state>`), `plan`, `entitlements`, `createdAt`, `stateChangedAt` | `accountId`, `stateKey` |
| `TenantMembership` | `<tenant>#<userSub>` | `tenantId`, `userSub`, `userProfileId` (the stable person key; one person can have two subs), `role` (`admin`, `editor`, `curator`, `member`), `status`, `grantedBy`, `grantedAt` | `userSub` (the token Lambda), `tenantId` |
| `TenantDomain` | the lowercase hostname | `tenantId`, `kind` (`subdomain`, `custom`), `status` (`pending_dns`, `pending_certificate`, `active`, `failed`, `removed`), `verification`, `certificateRef` | `tenantId` |

Because a domain's id is its hostname, a hostname can belong to one tenant only: a second create fails on the key. `papyrus_content.tenant_records` holds the key shapes and the two lookups callers must share (`list_memberships_for_user` is one query on the `userSub` index, never a scan; `claim_domain` refuses a hostname already held).

Access: the `admin` group (the platform operator) has full access; a tenant's admin may read its own rows through the `papyrus_tenant_admin` claim (`ownerDefinedIn("id")` on Tenant, `ownerDefinedIn("tenantId")` on the others). The claim is not issued yet (PPY-0bb0fd), so today only the operator group has any access. The claim rule is read-only, so it needs no field lock on `tenantId`. The tenant-claims and provisioning functions use IAM grants, which their own tasks add. The `userSub` index partition is a person, not a tenant: only the token Lambda (IAM) queries it.

## NewsroomSection ids

A Section row's primary `id` used to be the bare Section key (`mission`), so two tenants with the same key collided on one row. With a tenant the **stored** id is `<tenant>#<section key>` (for example `alpha#mission`). `#` is the separator already used in index keys; a Section row id is never used inside an index key (Assignments and References carry the bare key in their own `section` fields), so it is safe here.

The scoping happens in the client and callers keep working with bare keys:

- `get_record`, `get_records_by_id`, `upsert`, `update_record`, `create_record` and `delete_record` take the bare key and scope it.
- `list_records` and `get_record` return the row with `id` set to the bare key and the stored id in `storedId`, so `Reference.section`, `Assignment.sectionId` and edition planning see `mission`, not `alpha#mission`.
- `storedId` is dropped when a row is written back.
- Without a tenant, ids are untouched.

Copying a single-tenant backend with `--stamp-tenant` scopes the copied Section ids the same way.

## Markus import

`content import-markus --tenant <id>` builds a tenant client and makes everything it writes the tenant's own:

- Item ids become `<tenant>.item-<section>-<slug>` (`.` cannot appear in a tenant id, so the form is unambiguous and URL safe), and media row ids follow from them, so two tenants importing the same slug never share a row.
- Slugs are stamped into `tenantSlug`, and the slug and media lookups the importer uses are the tenant's.
- Uploaded image objects go under `media/<tenant>/...` in the bucket. (This is the one writer that still does; see [story pictures](#story-pictures-and-the-one-key-rule). A site that makes renditions from these objects needs the repair below.)
- "Not in source" and edited-in-the-CMS checks only see the tenant's rows.

`newsroom import-sections --tenant <id>` seeds a tenant's Sections from the Section yml.

## Site cyclotron

`references decide-site-sections` and `references prove-site-sections` take `--tenant <id>`. With a tenant the Section list is that tenant's NewsroomSection rows (the yml seed stays the source without a tenant), and the cyclotron is the tenant's own: id `<cyclotronId>-<tenant>`, local store `<localPath>-<tenant>`, S3 prefix `<s3Prefix>-<tenant>`, and so the `cyclotron.site` Assignment, the `site_decision_is` classifier keys and the usage and agreement records are all tenant-scoped. The steering config (decision model, optimizer, review program, `approvedProofPath`) stays shared. See [cyclotron-priming.md](cyclotron-priming.md).

## Story pictures and the one-key rule

A story picture has one address, its `srcPath` (`assets/<slug>/<file>`). The saved text says it, the `MediaAsset` row records it, and the site's renditions are made and looked up under it. Its object is therefore always `media/<srcPath>`, for every tenant: the newsroom editor writes it, `stories save-version --images` writes it, the renditions function (which takes the source from the key by dropping `media/`) reads it, and the projector asks for the renditions of that source. `papyrus_content.renditions.media_key_for_source` is the single function that makes the key.

Why there is no tenant folder in the key: the folder was added so that two tenants importing files of the same relative name (`import-markus`, `copy-backend --stamp-tenant`) could not overwrite each other in a shared bucket, and it was never an access boundary. The storage rules (`amplify/storage/resource.ts`) give the `editor` and `admin` groups read and write on all of `media/*` and guests read, and nothing in them mentions a tenant; the identity pool cannot tell one tenant's folder from another's. What keeps tenants apart is the row (`tenantId` and the tenant-scoped indexes, enforced by the tenant client) and, in the standard site, the backend itself: one backend, one site bucket and one renditions function per site, so there is one `srcPath` namespace per bucket. The renditions are read by `srcPath` alone, so a folder in the key cannot be reflected in the renditions without a second mapping. The `srcPath` of a saved story picture already carries the story's slug, which is unique within a tenant, so two tenants in one bucket collide only if they have the same slug and file name. That residual risk exists only for a backend that serves several publications from one bucket, which the standard site does not; this rule removes no access protection (there was none by key) and no row isolation.

Before this rule `stories save-version --images` stored tenant pictures at `media/<tenant>/assets/...` (PPY-a96347). Their renditions were made under the tenant folder, the projector looked for none, and a publish failed with missing renditions; the command the error suggested pointed at an object that did not exist. Existing objects are not moved by a deploy. `papyrus stories repair-image-paths --story <lineage> [--write]` copies a story's pictures to `media/<srcPath>` inside the bucket (no new upload) and points its rows at them; see [story-reporting.md](story-reporting.md#saving-a-draft-with-its-pictures). `papyrus ops content renditions --source <srcPath>` signed in asks the site's image function to make renditions again, and names the old tenant key if that is where the object is.

The write path used to undo that rule for the rows: the tenant stamp rewrote every `MediaAsset` and `PublishedMediaAsset` `storagePath` to `media/<tenant>/<srcPath>` while the object sat at `media/<srcPath>`, so the console preview signed a key with no object (PPY-5978b4). The stamp no longer touches `storagePath`. `stories repair-image-paths` also re-points rows (media and published media) whose object is already at `media/<srcPath>`, copying and deleting nothing; the dry run lists each row.

`content import-markus --tenant` and `content copy-backend --stamp-tenant` still place objects under `media/<tenant>/...` and keep their `storagePath` rows to match; a site that makes renditions from those objects needs the same repair per story (the command works from the rows, not from how they were saved).

## Adopting data written before tenant scoping

Rows written before tenants existed carry no `tenantId`, and Section rows sit under bare ids. A tenant client cannot see or write them, so they must be adopted once into the tenant that owns them (for the production publication, `p-apyr-us`).

`content adopt-tenant-data --tenant <id> [--apply] [--json]` does it. It is a dry run unless `--apply` is given, and it refuses to run when `--tenant` is missing or `PAPYRUS_TENANT_ID` is set, because it must read every row.

Run it from an operator machine that has AWS credentials for the backend (a person, not CI), dry run first:

    papyrus content adopt-tenant-data --tenant p-apyr-us

The dry run prints, for Section, Item, PublishedItem, MediaAsset and PublishedMediaAsset, how many rows it would adopt, re-id, find already adopted, leave because they belong to another tenant, or leave because of a conflict, with a few sample ids. Read the other-tenant and conflict lines before applying; those rows are never written. Then run the same command with `--apply`. Running it again changes nothing.

What it does:

- Stamps `tenantId` and the tenant-prefixed `typeStatus`, `sectionStatus` and `tenantSlug` on Item, PublishedItem, MediaAsset and PublishedMediaAsset rows that have none.
- For each bare NewsroomSection row, whether or not it had a `tenantId`, creates `<tenant>#<key>` with the same fields and then deletes the bare row.

What it will not do:

- It does not change Item, PublishedItem or media record ids, since other records reference them.
- It does not change any `storagePath` and moves no S3 objects. Adopted media keep their old paths until a `content import-markus --tenant` run re-uploads them under `media/<tenant>/`.
- It does not touch rows that belong to a different tenant, and it leaves a bare Section alone when `<tenant>#<key>` already exists (a conflict to settle by hand).
- It does not rebuild the reader; trigger a rebuild afterwards if needed.

`content import-markus --tenant <id>` also adopts on its own: when `<tenant>.item-<section>-<slug>` is absent but the legacy `item-<section>-<slug>` exists and either belongs to the tenant or has no tenantId and the same slug, the import reuses the legacy id (media ids follow from it) and stamps that item, its media and its published rows as the tenant's, so no duplicate item or slug collision appears.


## Machines on Machines and other backends copied with a tenant

A backend copied from a tenant site keeps the tenant on its sections and stories, and the editorial check refuses a record whose tenant is not the client's. Two settings make the backend consistent with its data: the router publication's `tenantId` (see [monitoring in the cloud](monitoring-cloud.md)) and, for the backend's own Lambdas (create a story from a Reference, edit a story, the assignment and category actions, and the editorial-checks function, which refuses an editorial context whose tenant differs from its own), the build variable `PAPYRUS_TENANT_ID` on the site, which `amplify/site-backend.ts` passes to those Lambdas. Rows that carry no tenant (for example the doctrine Items) are invisible to a tenant client until `content adopt-tenant-data --tenant <id>` has adopted them (dry run first).

### Single-publication backends and Reference intake

The wiki commands (`knowledge wiki sync`, `knowledge wiki publish`) and the cloud knowledge run write under the publication's tenant like every other command. The cloud run takes it from `PAPYRUS_TENANT_ID` in the site's `knowledgeRun` `environment` (`infra/site.json`). A command with no tenant refuses to write when the backend's Items already belong to a tenant (rows written without the stamp are invisible to the tenant's renders), and names the tenant to pass.

Reference intake (`papyrus references create-from-catalog --status pending`, the email-candidate import) refuses a backend that carries a tenant, because knowledge data (References, corpora) has no tenant isolation. A backend copied from a tenant site that holds one publication only does not share that data, so it declares so: add `"PAPYRUS_SINGLE_PUBLICATION_BACKEND": "true"` to `cms.environment` in the site's `infra/site.json`. `amplify/site-backend.ts` passes it to the content-actions Lambda only when `PAPYRUS_TENANT_ID` is also set and the value is exactly `true`. A token that carries a tenant is refused regardless. **If a second publication is ever added to that backend, remove the declaration first** (in the same change), or the second publication's editors could write into the first one's corpus. Details: [user-session intake](reference-intake/user-session-intake.md#publication-and-actor-boundary).
