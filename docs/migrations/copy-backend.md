# Copying content between two Papyrus backends (`copy-backend`)

`papyrus ops content copy-backend` copies model rows (AppSync) and S3 objects
from a source Papyrus backend to a target Papyrus backend. It is generic: models,
keys and writable fields come from AppSync introspection of both schemas, so it
works for any Papyrus data schema. It was built for Threat Intelligence
(Phase 4, P4-08/P4-09) and is reused by p.apyr.us (Phase 5, PPY-e20cab, with its
22 non-empty tables, S3 prefixes and S3 Vectors index; the vector index is not
copied by this tool and needs a rebuild or its own step).

## Interface

```bash
papyrus ops content copy-backend \
  --source-outputs <amplify_outputs.json | stack:<cloudformation-stack>> \
  --target-outputs <amplify_outputs.json | stack:<cloudformation-stack>> \
  [--models Item,PublishedItem,... | all] \
  [--s3-prefixes media/,newsroom/ | none] \
  [--manifest-dir <dir>] [--json] [--apply]
```

* Dry run is the default and performs only reads (introspection, list queries, S3 list). `--apply` writes. This differs on purpose from `import-markus`, which writes by default.
* `stack:<name>` reads `awsAppsyncApiEndpoint`, `bucketName` and `storageRegion` from the CloudFormation stack outputs. A file needs `data.url` and `storage.bucket_name`.
* Auth is the caller's AWS credential chain, SigV4 (`AWS_PROFILE=legacy`). The source is opened read-only.
* Default models: NewsroomSection, Tag, Edition, Item, MediaAsset, EditionItem, ItemTag and the five Published* models. Default S3 prefix: `media/`. Everything else is printed in the plan as `skip` with its counts; nothing is excluded silently. `--models all` selects every model except identity models.
* Identity models (UserProfile, UserIdentity, UserRoleAssignment) are refused even if named: people re-sign-in.

## Behaviour

* Rows are matched by key (`id`), copied with all fields the target accepts, so ids, slugs, `type`, `versionNumber`, `publishedAt` and `editorial` JSON are preserved. Rows are copied by model, never filtered by `type`, so `videoml` rows carry over.
* Idempotent: a row is unchanged when every non-null source field equals the target field after JSON normalization (AWSJSON strings are parsed and key order is ignored; PPY-16a680). Fields that are null in the source (for example `bodyIr` when the old backend lacks it) never overwrite target values, so convert-bodies output survives a re-run. `createdAt` and `updatedAt` are excluded from comparison.
* Validation before any write: required target fields that are missing, enum values the target rejects and invalid JSON are listed per row. If any row is invalid, `--apply` writes nothing.
* S3: objects are copied server-side with the same key, only when missing or different (size differs, or both ETags are plain MD5 and differ; multipart ETags are not comparable and size decides).
* Never deletes rows or objects in the target. Target-only rows and objects are counted and kept.
* `--manifest-dir` writes `source/` and `target/` directories in the P4-01 baseline layout: `models/counts.json`, `models/content-manifest.json` (per-row sha256 of the shared, normalized fields, excluding createdAt/updatedAt), `s3/media-manifest.json`, `s3/keys.json` (key and size only, for diffing across buckets) and `s3/prefix-summary.json`. After `--apply` the manifests come from a fresh read. These hashes are over GraphQL-normalized fields, so they are comparable between the two sides of this tool, not with the raw DynamoDB hashes of the P4-01 baseline (compare ids and counts with the baseline).

## Known limits

* `createdAt` is not an input field in AppSync for most models; the target gets the copy time. `updatedAt` is preserved only on models that declare it as a field (Item, PublishedItem). Business timestamps (`publishedAt`, `versionCreatedAt`, `editionDate`) are normal fields and are preserved.
* A schema difference is reported, not fatal: source fields the target lacks are listed per model; target fields the source lacks stay empty.
* Run it from a machine with SSO credentials. If `botocore` reports an expired SSO token while the AWS CLI works, export credentials first: `eval "$(aws configure export-credentials --profile legacy --format env)"`.

## Runbook

1. Dry run, review the plan table with Ryan, keep the JSON: `... copy-backend --source-outputs stack:<old> --target-outputs stack:<new> --json > plan.json`.
2. Freeze edits on the source CMS.
3. `--apply --manifest-dir <dir>`; run it again and expect zero create/update/copy.
4. Convert bodies on the target, then diff `source/` and `target/` manifests.
