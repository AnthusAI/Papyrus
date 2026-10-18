---
name: publication-bootstrap
description: Use this skill when creating or rehearsing a new Papyrus publication from a pile of source files, setting up corpus accession structure, bootstrapping references, tuning topic-model granularity, or creating analysis/re-index assignments from scratch.
---

# Publication Bootstrap Skill

Use this skill when the task is to start a new Papyrus publication from source
materials rather than operate an already-indexed publication.

The canonical guide is
[`docs/new-publication-from-corpus.md`](../../docs/new-publication-from-corpus.md).
Worker setup and cloud-to-local corpus synchronization are documented in
[`docs/newsroom-worker-bootstrap.md`](../../docs/newsroom-worker-bootstrap.md).
Read that guide first, then use the repo-local skills below for the exact
sub-workflow:

- `skills/reference-intake/SKILL.md` for registering source materials as
  `Reference` prospects and enforcing evidence eligibility.
- `skills/category-steering/SKILL.md` for steering config, S3 corpus rules,
  accepted taxonomy imports, analysis profiles, and re-index assignments.
- `skills/newsroom-research-workflow/SKILL.md` when the source materials came
  from research packet `proposedReferences`.

## Operating Boundary

Papyrus owns publication configuration, GraphQL-visible reference metadata,
curation workflow, assignments, accepted taxonomy state, semantic steering, and
operator-visible re-index plans. Filesystem folders and catalogs are adapters;
after registration, GraphQL is the operational source of truth.

Biblicus owns corpus ingestion, source extraction, topic modeling, classifier
training, projection, graph extraction, generated artifacts, and repeatable
analysis execution. Do not edit `$BIBLICUS_WORKDIR` source from
Papyrus. If a bootstrap step needs a new Biblicus feature, document the needed
contract and hand it to the Biblicus agent.

## Required Inputs

Before mutating data, identify:

- publication or deployment target;
- AWS profile/account and S3 bucket;
- steering config path;
- corpus key;
- local corpus path;
- whether the run is a sandbox rehearsal or production operation;
- source-material layout;
- catalog path;
- initial curation status policy;
- analysis profile keys to test.

For Papyrus local sandbox work, prefer the local account instructions in
`AGENTS.local.md` and verify them with `aws sts get-caller-identity` before
running `npm run sandbox` or syncing S3.

## Source Material Structure

Accept a loose file pile only as a staging input. Convert it into a corpus
accession before registration or analysis.

Canonical accession layout:

```text
corpora/<corpus-key>/
  metadata/
    config.json
    catalog.json
  imports/
    <item-id>--<encoded-source-uri>--<slug>.<ext>
    <item-id>--<encoded-source-uri>--<slug>.<ext>.biblicus.yml
```

Use `imports/` for every source material type, including PDFs. Existing corpora
may still contain root-level paper files, but treat that as legacy staging. New
bootstrap work should normalize those files into accession entries instead of
teaching Papyrus agents two equal intake shapes.

Every source material needs a stable item id and provenance. Sidecars should
carry title, authors, media type, source URI, dates, tags, abstract or summary,
and `ingestion_rationale` when available. `metadata/catalog.json` is the
Papyrus-visible registration contract.

## Bootstrap Steps

1. Normalize the file pile into a corpus accession with stable ids, sidecars,
   and `metadata/catalog.json`.
2. Add or select a steering config that defines the publication corpus set.
3. For sandbox rehearsals, generate a run-local steering config whose
   `s3Prefix` values point at the sandbox bucket from `amplify_outputs.json`.
4. Sync source accession data to or from the target private S3
   `corpora/<corpus-key>/` prefix with `corpora sync-to-cloud` or
   `corpora sync-from-cloud` after reviewing the dry run.
5. Materialize corpus config and relation types in Papyrus.
6. Prepare catalogs into the run directory when item-level rationales are
   missing. Do not rewrite source catalogs for a rehearsal.
7. Register the catalog into GraphQL. The registration must create a
   `KnowledgeImportRun`, a sanitized `KnowledgeRawPayload`, one `Reference` per
   source material, attachments, rationale messages, semantic links, and one
   open `curation.reference-intake` assignment per pending reference.
8. Curate an initial accepted evidence set.
9. Export accepted-only analysis and scope-training manifests.
10. Preview analysis command plans with `analysis reindex-plan`.
11. Create `analysis.reindex` assignments with `analysis create-reindex-assignment`.
12. Claim and execute those assignments explicitly in later worker/operator
    steps; assignment creation must not execute Biblicus.

## Commands

Materialize config:

```bash
poetry run papyrus ops categories sandbox-steering-config \
  --config corpora/papyrus-steering.yml \
  --output .papyrus-runs/<run-id>/sandbox-steering.yml

poetry run papyrus ops corpora worker-bootstrap \
  --config .papyrus-runs/<run-id>/sandbox-steering.yml \
  --json

poetry run papyrus references prepare-catalog \
  --config .papyrus-runs/<run-id>/sandbox-steering.yml \
  --corpus-key <corpus-key> \
  --catalog corpora/<corpus-key>/metadata/catalog.json \
  --output .papyrus-runs/<run-id>/<corpus-key>-prepared-catalog.json

poetry run papyrus ops categories import-config --config <steering.yml>
poetry run papyrus knowledge concepts import-types --config corpora/papyrus-semantic-relation-types.yml
```

Register source materials:

```bash
poetry run papyrus references create-from-catalog \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --catalog .papyrus-runs/<run-id>/<corpus-key>-prepared-catalog.json \
  --status pending \

```

Export accepted-only inputs:

```bash
poetry run papyrus references export-analysis-manifest \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --output .papyrus-runs/<run-id>/accepted-reference-manifest.json

poetry run papyrus references export-scope-training \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --output .papyrus-runs/<run-id>/scope-training.json
```

Preview and create re-index work:

```bash
poetry run papyrus analysis reindex-plan \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile global-topic-granularity \
  --corpus-key <corpus-key> \
  --override targetTopicRange=10:20

poetry run papyrus analysis create-reindex-assignment \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile global-topic-granularity \
  --corpus-key <corpus-key> \
  --override targetTopicRange=10:20 \

```

Execute from claimed assignment metadata:

```bash
poetry run papyrus analysis execute-assignment \
  --assignment <analysis-assignment-id>
```

Immediate assignment-backed run (create, claim, execute, complete):

```bash
poetry run papyrus analysis run-now \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile global-topic-granularity \
  --corpus-key <corpus-key> \
  --override targetTopicRange=10:20
```

Queue worker mode for batch processing:

```bash
poetry run papyrus assignments process-queue \
  --type analysis.reindex \
  --status open \
  --max-count 10 \
  --stop-on-error false
```

Claim exclusive analysis work before execution:

```bash
poetry run papyrus assignments claim \
  --assignment <assignment-id> \
  --assignee-key "procedure-run:<run-id>" \
  --claim-ttl-seconds 21600
```

## Topic Granularity And Labels

Use analysis profiles for parameter control. Do not hard-code BERTopic,
classifier, projection, or graph parameters in Papyrus application logic.

Start with `global-topic-granularity` to explore top-level topic count and
granularity. Use `canonical-topic-classifier` after enough authoritative labels
exist to seed semi-supervised training. Use scoped child-topic discovery after
the top-level category anchors and operational sections exist.

Generated classifications are predictions. Approved classifications should
become `authoritative_label` relations. Rejected generated `classified_as`
predictions should be deleted without storing separate rejection metadata.

When expected top-level topics are missing or unclear, sculpt a draft category
set instead of trying to tune BERTopic into the exact desired taxonomy:

```bash
poetry run papyrus knowledge topics draft-create \
  --from-category-set <current-category-set-id> \
  --title "Initial topic sculpting pass" \


poetry run papyrus knowledge topics draft-add-topic \
  --category-set <draft-category-set-id> \
  --display-name "<expected topic>" \
  --short-title "<one-or-two-word label>" \
  --subtitle "<short description>" \


poetry run papyrus references label \
  --reference <accepted-reference-id-or-item-id> \
  --category <category-key-or-lineage-id> \
  --category-set <draft-category-set-id> \
  --note "Why this accepted reference is a good seed for the topic." \

```

Export a classifier seed manifest from authoritative labels, not from mixed
pending/rejected material:

```bash
poetry run papyrus knowledge topics export-classifier-seed-manifest \
  --config <steering.yml> \
  --category-set <draft-category-set-id> \
  --corpus-key <corpus-key> \
  --output .papyrus-runs/<run-id>/seed-manifest.json
```

Use that manifest in `canonical-topic-classifier` retraining:

```bash
poetry run papyrus analysis preview-reindex \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile canonical-topic-classifier \
  --corpus-key <corpus-key> \
  --override seedManifestPath=.papyrus-runs/<run-id>/seed-manifest.json
```

Promote the draft only after it should become the accepted basis for desks,
assignment context, and publication sections.

## Verification

For a successful bootstrap rehearsal, verify:

- sandbox or target account is the intended AWS account;
- source accession files exist in the expected S3 prefix;
- `Reference` rows exist for registered catalog entries;
- a `KnowledgeImportRun` exists for the registration batch;
- every pending reference has exactly one open `curation.reference-intake`
  assignment linked by `requests_work_on`;
- only accepted current references appear in exported analysis manifests;
- `analysis.reindex` assignments preserve profile key, corpus key, mode,
  overrides, command plan, and destructive preview;
- no `Item`, `EditionItem`, `classified_as`, or `uses_evidence` rows are
  created by catalog registration;
- generated analysis outputs can be deleted and rebuilt without deleting source
  accession files.

## Maintenance Cleanup

When rehearsing destructive sandbox rebuilds, GraphQL payload rows and S3
payload objects must be kept together. Use:

```bash
poetry run papyrus ops content delete all --yes --delete-attachments
```

to reset GraphQL records and delete associated `newsroom/payloads/` objects.
If a previous reset deleted rows but left S3 payloads behind, run a dry-run
first, then apply:

```bash
poetry run papyrus sections prune-attachments
poetry run papyrus sections prune-attachments
```

This cleanup is only for operational payload attachments. Do not use it for
`corpora/` source accession material.
