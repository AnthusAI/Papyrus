# Multi-tenancy

One backend can serve several publications. A tenant is one publication's account; its id is lowercase letters, digits and hyphens. Set it with `--tenant <id>` on a command, or `PAPYRUS_TENANT_ID` for the whole shell. A command with no tenant behaves exactly as a single-tenant backend always has and writes nothing tenant-shaped.

The key helpers live in `papyrus_content.tenancy`; `PapyrusGraphQLAuthoringClient(tenant_id=...)` applies them at the client boundary so callers never build tenant keys themselves.

## What the tenant models carry

Item, PublishedItem, MediaAsset, PublishedMediaAsset and NewsroomSection rows get a `tenantId`. The index values that would be global (`typeStatus`, `sectionStatus`, slug lookups) are prefixed with `<tenant>#`, media `storagePath` moves under `media/<tenant>/`, and a tenant client lists, reads, updates and deletes only its own rows.

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
- Uploaded image objects go under `media/<tenant>/...` in the bucket.
- "Not in source" and edited-in-the-CMS checks only see the tenant's rows.

`newsroom import-sections --tenant <id>` seeds a tenant's Sections from the Section yml.

## Site cyclotron

`references decide-site-sections` and `references prove-site-sections` take `--tenant <id>`. With a tenant the Section list is that tenant's NewsroomSection rows (the yml seed stays the source without a tenant), and the cyclotron is the tenant's own: id `<cyclotronId>-<tenant>`, local store `<localPath>-<tenant>`, S3 prefix `<s3Prefix>-<tenant>`, and so the `cyclotron.site` Assignment, the `site_decision_is` classifier keys and the usage and agreement records are all tenant-scoped. The steering config (decision model, optimizer, review program, `approvedProofPath`) stays shared. See [cyclotron-priming.md](cyclotron-priming.md).

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
