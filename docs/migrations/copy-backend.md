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
  [--s3-prefixes media/,newsroom/ | none] [--s3-keys corpora/a.yml,corpora/b.yml] \
  [--key-field-defaults Model.field=value,...] \
  [--manifest-dir <dir>] [--json] [--apply] \
  [--source-profile <aws-profile>] [--target-profile <aws-profile>] \
  [--expect-source-account <id>] [--expect-target-account <id>] \
  [--s3-transfer auto|server-side|stream] [--s3-workers <N>]
```

* Dry run is the default and performs only reads (introspection, list queries, S3 list). `--apply` writes. This differs on purpose from `import-markus`, which writes by default.
* `stack:<name>` reads `awsAppsyncApiEndpoint`, `bucketName` and `storageRegion` from the CloudFormation stack outputs. A file needs `data.url` and `storage.bucket_name`.
* Auth is the caller's AWS credential chain, SigV4 (`AWS_PROFILE=legacy`), for both sides unless a profile option is given (see Cross-account copy). The source is opened read-only.
* Default models: NewsroomSection, Tag, Edition, Item, MediaAsset, EditionItem, ItemTag and the five Published* models. Default S3 prefix: `media/`. Everything else is printed in the plan as `skip` with its counts; nothing is excluded silently. `--models all` selects every model except identity models.
* `--s3-keys k1,k2` selects exact object keys (no trailing slash is added, so `corpora/papyrus-steering.yml` selects that one object and nothing like `corpora/papyrus-steering.yml.bak`). It combines with `--s3-prefixes`. The `media/` default applies only when neither option is given, so `--s3-keys` alone copies only those keys. A key missing in the source is a plan error (exit code 1).
* Identity models (UserProfile, UserIdentity, UserRoleAssignment) are refused even if named: people re-sign-in.

## Behaviour

* Rows are matched by key (`id`), copied with all fields the target accepts, so ids, slugs, `type`, `versionNumber`, `publishedAt` and `editorial` JSON are preserved. Rows are copied by model, never filtered by `type`, so `videoml` rows carry over.
* Idempotent: a row is unchanged when every non-null source field equals the target field after JSON normalization (AWSJSON strings are parsed and key order is ignored; PPY-16a680). Fields that are null in the source (for example `bodyIr` when the old backend lacks it) never overwrite target values, so convert-bodies output survives a re-run. `createdAt` and `updatedAt` are excluded from comparison.
* Composite index sort keys (PPY-2b8771): AppSync rejects a create when a field of a composite secondary-index sort key is null (for example `Message.responseStatus` in `messagesByResponseTargetStatusCreatedAt`, sort keys `responseStatus`, `createdAt`). The tool reads these fields from the target's introspected index query types (`<Index>CompositeKeyConditionInput`). When a row to be created has one of them null, it gets a default for that field; nothing else changes (bodies, timestamps, ids, and the other null fields such as `responseTarget` stay as in the source). Built-in default: `Message.responseStatus=COMPLETED`, which is what the app itself writes for messages that need no response (category-action writes `responseTarget=none`, `responseStatus=COMPLETED`; the console responder only acts on `PENDING` rows for its own target, so these rows are never queued). Override or add with `--key-field-defaults Message.responseStatus=ARCHIVED,Model.field=value`. A null composite sort-key field with no default is listed as an invalid row (`null-composite-sort-key:<field>`) and `--apply` writes nothing. Defaults apply only to rows the target lacks; existing target rows are never touched by them. The plan table notes `N rows get key defaults: field=value` per model, and the JSON has `keyFieldDefaults` (`count`, `fields`) per model, in the dry run and in the apply summary.
* Validation before any write: required target fields that are missing, enum values the target rejects and invalid JSON are listed per row. If any row is invalid, `--apply` writes nothing.
* S3: objects are copied (server-side by default, see `--s3-transfer`) with the same key, only when missing or different (size differs, or both ETags are plain MD5 and differ; multipart ETags are not comparable and size decides).
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

## Cross-account copy (PPY-66408d)

By default both sides use one credential chain. For two AWS accounts, give each side its own profile:

* `--source-profile NAME` / `--target-profile NAME`: each side builds its own boto3 session. That session signs the side's AppSync calls (SigV4), resolves its `stack:` location in CloudFormation and builds its S3 client. Absent options keep today's ambient chain and server-side copy, and the plan is unchanged apart from `sourceAccount` and `targetAccount` being null.
* `--expect-source-account ID` / `--expect-target-account ID`: `sts get-caller-identity` of that side must match, otherwise the command stops before any other read or write. The plan JSON (`sourceAccount`, `targetAccount`) and the printed table show both account ids whenever a profile or an expected account is given.
* `--s3-transfer auto|server-side|stream`: `auto` (default) is `server-side` (`CopyObject` with the target client, needs read access to the source bucket) when neither profile is given, else `stream`. Stream mode does `head_object` and `get_object` (with `If-Match` on the source ETag) on the source session and uploads with the target session. Nothing is written to local disk.
* `--s3-workers N` (default 1, as before): N objects are copied in parallel. Each failed key is reported as an error in the plan (exit code 1); the other keys are still copied. Progress (`done/total objects, MB`) goes to stderr every 15 seconds and never prints keys or contents.
* The source is read-only by construction: its S3 client only allows list, head and get calls (anything else raises), and the source AppSync backend refuses writes.

### Fidelity of a stream copy

* Preserved: key, size, `ContentType`, `CacheControl`, `ContentDisposition`, `ContentEncoding`, `ContentLanguage` and user `Metadata`. Not preserved: tags, ACLs, `Expires`, storage class, website redirects; the target bucket's default encryption applies.
* ETag, plain-MD5 source (no `-`): one `put_object`; the returned ETag must equal the source ETag, else the key is reported as an error. Such an object is held in memory whole; a plain object larger than the memory budget (256 MiB) is uploaded in 8 MiB parts and then cannot reproduce its ETag (see below).
* ETag, multipart source: the source part size is read with `head_object(PartNumber=1)` and the upload uses the same part size (8 MiB when unknown), so a source uploaded with uniform parts (all 116 multipart objects of the old p.apyr.us media bucket are 8 MiB-part uploads) gets the identical ETag. When the ETag still differs (non-uniform source parts, or a large plain object), the copy is kept after the target size is checked against the source size, and the plan lists a warning per key: for those keys the guarantee is size equality only, not a checksum.
* Memory is bounded: all workers together hold at most 256 MiB (one part, at most 8 MiB for 8 MiB-part sources, per worker for multipart objects).
* Resume and idempotency: a re-run plans only keys that are missing in the target or differ in size (or in ETag, when both ETags are plain MD5); finished keys are skipped. A failed multipart upload is aborted so no partial object appears.

### p.apyr.us runbook (legacy 335163751677 to papyrus-production 712236451410)

Dry run, read-only (nothing is written; both accounts are asserted first):

```bash
S=stack:amplify-dbsyytcm9drqa-main-branch-cb38ada667
T=stack:amplify-ds6yswxui41yi-main-branch-23e5d23a59
papyrus ops content copy-backend --source-outputs $S --target-outputs $T \
  --source-profile legacy --target-profile papyrus-production \
  --expect-source-account 335163751677 --expect-target-account 712236451410 \
  --models KnowledgeCorpus,CategorySet,Category,CategoryKeyword,NewsroomSection,ProcedureDefinition,ProcedureVersion,ProcedureRun,KnowledgeArtifact,KnowledgeImportRun,Reference,ReferenceAttachment,SemanticRelationType,SemanticNode,SemanticRelation,Assignment,AssignmentEvent,MessageThread,Message \
  --s3-prefixes corpora/AI-ML-history/,corpora/AI-ML-journalism/,corpora/AI-ML-research/,corpora/ai-ml-history/,corpora/ai-ml-journalism/,corpora/ai-ml-research/,corpora/knowledge-index/,newsroom/,media/,inbound-email-archived/ \
  --manifest-dir <scratch>/dry --json > plan.json
```

Apply rows first (add `--apply --s3-prefixes none --manifest-dir <scratch>/apply`), then objects (a second run with the ten prefixes plus `--s3-transfer stream --s3-workers 16 --apply`; the rows are then planned as unchanged). Run under `caffeinate`; the run is idempotent after an SSO expiry.
