# Newsroom Worker Bootstrap

This guide explains how a local Mac, EC2 instance, or other worker becomes ready
to run Papyrus/Biblicus analysis assignments.

## Operating Model

Papyrus analysis uses three related stores. They are not interchangeable:

- The local Biblicus corpus working copy is where Biblicus commands execute.
- S3 `corpora/*` prefixes are durable shared corpus storage for workers.
- Papyrus GraphQL is the operational workflow and index layer for references,
  assignments, curation, summaries, and imported analysis outputs.

S3 sync alone does not make references visible in the Newsroom. GraphQL
registration alone does not guarantee a worker has local source files. A worker
is ready for analysis only when the local corpus, S3 corpus prefix, and GraphQL
reference state agree, and accepted references have extracted text attachments.

## New Worker Setup

1. Clone Papyrus and Biblicus on the worker.
2. Configure `AWS_PROFILE`, `AWS_REGION`, and `PAPYRUS_GRAPHQL_ENDPOINT`.
3. For sandbox work, generate a run-local steering config whose `s3Prefix`
   values point at the sandbox bucket from `amplify_outputs.json`:

   ```bash
   poetry run papyrus ops categories sandbox-steering-config \
     --config corpora/papyrus-steering.yml \
     --output .papyrus-runs/<run-id>/sandbox-steering.yml
   ```

4. Inspect worker readiness:

   ```bash
   poetry run papyrus ops corpora worker-bootstrap \
     --config <steering.yml> \
     --json
   ```

5. Pull corpus files from S3 into the local Biblicus working copy:

   ```bash
   poetry run papyrus ops corpora sync-from-cloud \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --dry-run

   poetry run papyrus ops corpora sync-from-cloud \
     --config <steering.yml> \
     --corpus-key <corpus-key> \

   ```

6. Recheck readiness before claiming analysis work:

   ```bash
   poetry run papyrus ops corpora status \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --json
   ```

Only after this should the worker claim or execute `analysis.reindex`
assignments.

`analysis run-now` and `analysis execute-assignment` also pull from S3
automatically when the local `metadata/catalog.json` is missing or does not
match the configured `s3Prefix` catalog. That step uses the same semantics as
`corpora sync-from-cloud` (no `--delete`, `analysis/` excluded unless
`--include-analysis` is passed). Use `--skip-sync-from-cloud` to disable the
pull or `--sync-from-cloud` to force it even when catalogs already match.

## Uploading New Local Corpus Material

When new source material is added locally, push the corpus accession to S3
before registering or analyzing it:

```bash
poetry run papyrus ops corpora sync-to-cloud \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --dry-run

poetry run papyrus ops corpora sync-to-cloud \
  --config <steering.yml> \
  --corpus-key <corpus-key> \

```

Then register the catalog into GraphQL:

```bash
poetry run papyrus references prepare-catalog \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --catalog corpora/<corpus-key>/metadata/catalog.json \
  --output .papyrus-runs/<run-id>/<corpus-key>-prepared-catalog.json

poetry run papyrus references create-from-catalog \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --catalog .papyrus-runs/<run-id>/<corpus-key>-prepared-catalog.json \
  --status pending \

```

After curation, run source readiness and extraction commands until accepted
references are text-ready, then export the accepted-only analysis manifest.

## Command Semantics

`corpora status` compares local catalog, S3 catalog, GraphQL references,
reference attachments, and import runs. It reports readiness issues such as:

- `wrong_bucket_for_endpoint`
- `missing_local_catalog`
- `missing_s3_catalog`
- `local_not_synced_to_s3`
- `s3_not_registered_in_graphql`
- `accepted_manifest_not_ready`
- `missing_extracted_text`

`corpora sync-from-cloud` runs `aws s3 sync s3://... corpora/<corpus-key>/`.
It does not delete local files by default.

`corpora sync-to-cloud` runs `aws s3 sync corpora/<corpus-key>/ s3://...`.
It excludes `.DS_Store` and generated `analysis/` outputs by default. Use
`--include-analysis` only for import-only rehearsals or artifact debugging. Use
`--delete` only when intentionally reconciling a complete prefix.

Both sync commands refuse to run when the configured S3 bucket does not match
the active `amplify_outputs.json` bucket, unless `--force` is supplied. For
sandbox work, prefer generating a sandbox steering config instead of forcing.

## Analysis Readiness

An accepted-only analysis run requires:

- local corpus files available to Biblicus;
- matching S3 corpus catalog;
- GraphQL `Reference` rows registered for the relevant source materials;
- accepted current references selected by curation;
- `ReferenceAttachment.role = "extracted_text"` rows for accepted references;
- an `analysis.reindex` assignment or immediate assignment-backed run.

If `corpora status` reports `s3_not_registered_in_graphql`, run
`references prepare-catalog` and `references create-from-catalog`. If it reports
`missing_extracted_text`, run `references process-status`,
`references process-extract-text-now`, and `references process-attach-extracted-text`.
