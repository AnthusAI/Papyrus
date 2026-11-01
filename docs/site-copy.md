# Copying one site's backend into another (`papyrus ops site copy`)

Status: Beta. Built for moving the read.p.apyr.us publication (site id `p-apyr-us`) to Machines on Machines (site id and corpus key `machines-on-machines`, domain machines-on-machines.anth.us), whose backend is new. Decision (Ryan, 2026-11-01): a new backend plus a copy, with the sections kept as they are.

The command reads each model's DynamoDB table in the source backend and writes the records to the same model's table in the target backend, and copies the media objects between the two buckets. It does not use AppSync, so it needs no sign-in and does not go through resolvers. It never deletes anything.

```
papyrus ops site copy \
  --from-api 36xh4ckhhvfyrlxxbltoy246ea --to-api <new api id> \
  --corpus-key-map p-apyr-us=machines-on-machines \
  --from-media-bucket <source bucket> --to-media-bucket <target bucket> \
  [--models Item,NewsroomSection] [--media-prefixes newsroom/,corpora/] [--skip-media-prefix cyclotrons/ ...] \
  [--owner-map owners.json] [--keep-unmapped-owners] \
  [--region us-east-1] [--from-profile P] [--to-profile P] \
  [--apply | --dry-run] [--verify] [--json]
```

- **Dry run is the default.** Without `--apply` nothing is written. `--apply` with `--dry-run` is refused. (This differs from most `papyrus` commands, which write by default.)
- With no `--to-api` and no `--to-media-bucket` the command only reads the source and counts, so it is safe to run against production.
- **Tables** are found by AppSync API id: `<Model>-<apiId>-NONE`. A model in the source with no table in the target, or a different key schema, is an error. Nothing is written when the dry-run pass finds any refusal or error.
- **Idempotent and resumable.** Every run compares each rewritten source record with the target record of the same id. Equal content is skipped. A target record that differs is overwritten only when the source `updatedAt` is later; otherwise it is kept and counted as `kept-target` (the new site's own edit wins). A crashed run is continued by running it again. Objects already in the target with the same size are skipped.
- The source is live (monitors keep writing), so counts grow between runs. Run again to catch up, then `--verify`.

## What is preserved

Records move as DynamoDB typed JSON, so every attribute, `createdAt`, `updatedAt` and `__typename` is identical. Only the rewrites below change a value.

## Rewrite rules

The old key is matched as a whole token (not inside a longer word) and replaced in every string inside the listed top-level field.

| Rule | Where |
| --- | --- |
| `corpus-key` | Assignment: `id`, `corpusId`, `queueKey`, `queueStatusKey`, `title`. AssignmentEvent: `id`, `assignmentId`, `queueKey`. Item: `id`, `lineageId`, `sectionStatus`, `tenantId`, `tenantSlug`, `typeStatus`. PublishedItem: `tenantId`, `tenantSlug`, `sectionStatus`, `typeStatus`. MediaAsset and PublishedMediaAsset: `tenantId`, `storagePath`. KnowledgeRawPayload: `id`, `ownerId`. ModelAttachment: `id`, `ownerId`, `ownerLineageId`, `storagePath`. NewsroomSection: `id`, `tenantId`. Reference: `curationStatusReason`, `discoveredByMonitorId`. SemanticRelation: `classifierId` (the key Papyrus looks relations up by). Papyrus's own `publicationId` field on any model. |
| `bucket-name` | The source media bucket name, replaced by the target bucket name, in every string of every record. |
| `amplify-app-id` | The Amplify app id inside the bucket name (`amplify-<appId>-...`), replaced by the target's, in every string of every record. |
| media keys | Objects under `cyclotrons/` are skipped (see Media). An S3 key that contains the old key as a token is renamed the same way (for example `newsroom/payloads/assignmentevent/...-p-apyr-us-relevance-.../`). All other keys keep their name. |
| `owner-map` | See below. |

Anything else that mentions the old key is not rewritten. It is listed in the dry run as `mention left unchanged <Model.field>`. If the field looks like an id (`id`, `*Id`, `*Ids`, `*LineageId`, `*Key`) the run is refused instead, because the id cannot be mapped.

Not rewritten on purpose, agreed with the Cyclotron session: the SemanticRelation `metadata` blob (classifier id, cyclotron id, `provenance` with `accountId`, `runId`, binding and `bindingRevision`, `publicationId`), which stays byte-identical because it records that the decisions came from the `p-apyr-us-relevance` classifier in the shared-source relevance cyclotron; the same ids anywhere else a Cyclotron response is echoed (those four keys are skipped at any depth in rewritten fields); and the priming list id `prime-p-apyr-us` wherever it appears. Also: `p.apyr.us` URLs and email addresses inside Message history; the legacy email bucket named in Message metadata (a different bucket); 

### Reference ids never change

The shared Cyclotron keys its training on Reference ids. In the real source the Reference ids embed the shared `ai-ml-research` corpus, not `p-apyr-us`, so they copy unchanged. If a Reference id, or a Reference id inside a rewritten field, embeds the old key, the whole run stops and reports it; nothing is written.

## Owners

Access is group-based in this backend (Cognito groups `editor` and `admin`), not per row. The owner-like fields (`owner`, `*Sub`, and `createdBy`, `updatedBy`, `versionCreatedBy`, `actorSub`, `raisedBy`, `responseOwner` and the other `*By` fields) hold three kinds of value, and the dry run counts each per field:

- **service name** (for example `papyrus-cli`, `biblicus-import`): kept.
- **email**: kept (Google sign-in uses the same address in the new pool). Addresses are counted, never printed.
- **Cognito sub** (`<uuid>` or `<uuid>::<username>`): the new site has a new user pool, so the sub differs. With `--owner-map owners.json` (a JSON object, old value to new value; a bare sub key also matches the sub part of `sub::username`) the value is replaced. A sub with no entry is listed as `UNMAPPED owner` and the run is refused. `--keep-unmapped-owners` keeps the old value and still lists it.

Proposal: build the map after the editors have signed in once on the new site, by joining the source `UserIdentity` rows (`cognitoSub` to email) with the new pool's users by email. The identity models are copied like any other model, so their subs go through the same map. In the p-apyr-us source today there are no sub-shaped values and no UserProfile, UserIdentity or UserRoleAssignment rows, so no map is needed. Editors are added to the new pool's `editor`/`admin` groups with `papyrus` role grants, not copied.

## Media

`--from-media-bucket` and `--to-media-bucket` copy every object (or only `--media-prefixes`) with a server-side copy, renaming the keys above. The credentials that run the copy need read on the source bucket and write on the target. The dry run also counts row `storagePath` values that point at no object in the source bucket; these are missing in the source too and are left as they are.

`--skip-media-prefix P` (repeatable) leaves objects whose source key starts with `P` out of the copy; passing it replaces the default `cyclotrons/`, and `--skip-media-prefix none` skips nothing. The default exists because the new site does not use embedded mode, so the Cyclotron `state.tar.gz` is not copied. The dry run reports the skipped object count and bytes, and `--verify` leaves skipped keys out.

## Verify

`--verify` is read only. For each model it applies the same rewrites to the source, then compares the record count and a content hash with the target (all target records), and lists missing, extra and different ids. For media it compares keys and sizes. `--apply --verify` verifies after writing. A new site's own records show as `extra`; a source that changed since the copy shows as `missing` or `different`. Exit status is 1 on any mismatch.

## Not covered

S3 object contents are copied as they are. Ids derived from a hash of the old key are not recomputed. Cognito, Amplify, DNS and CloudFront for the new site are separate steps ([starting a site](../README.md#start-a-new-papyrus-site)).
