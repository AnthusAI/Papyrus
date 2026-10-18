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
