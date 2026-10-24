# Starting A Publication From A File Corpus

This guide describes the repeatable bootstrap path for creating a new Papyrus
publication when the starting point is a folder of source materials rather than
an existing topic model, graph, or edition plan.

Papyrus should treat this as a newsroom buildout, not a one-off import. The
goal is to turn source material into visible `Reference` prospects, curate an
accepted evidence set, use Biblicus to discover and tune taxonomy/graph
artifacts, and then import the accepted steering state back into Papyrus.
Use `reference processing` as the umbrella term for this end-to-end source
workflow.

For worker setup and cloud-to-local corpus synchronization, also read
[`docs/newsroom-worker-bootstrap.md`](newsroom-worker-bootstrap.md). S3 corpus
sync, local Biblicus execution, and GraphQL registration are separate steps.

## Vocabulary

Use these terms consistently:

- `source material`: the original file or fetched page.
- `reference processing`: the full workflow from sparse seed (`DOI`/URL/minimal
  metadata) to usable knowledge reference.
- `process reference`: run registration, source resolution/acquisition, text
  extraction, and graph expansion.
- `register reference`: create the initial sparse `Reference` row.
- `corpus accession`: the durable local/S3 record of a source material plus
  sidecar metadata.
- `reference prospect`: a GraphQL-visible `Reference` with
  `curationStatus = "pending"`.
- `accepted reference`: a current `Reference` with
  `curationStatus = "accepted"`, eligible for evidence, analysis, graph work,
  section memory, context packs, and publication planning.
- `rejected reference`: retained curation memory. Only `out_of_scope` and
  `policy_exclusion` rejections become negative scope-training examples.
- `archived reference`: inactive retained record.
- `evidence set`: accepted current references only.
- `scope training set`: accepted positives plus structured editorial-scope
  negatives.
- `generated classification`: a Biblicus prediction linking a reference to a
  topic.
- `authoritative label`: an editor-approved topic label used as supervised
  steering.

Reserved meanings:

- `ingest`: Biblicus corpus-storage operation.
- `import`: config/artifact/type/projection import into Papyrus.
- `curate`: editorial decision workflow only.

## Canonical Corpus Accession

Papyrus should have one canonical intake shape: a corpus accession. A loose file
pile, a folder of root-level PDFs, a downloaded web crawl, or a manually curated
set of documents are all staging inputs. Before GraphQL intake or analysis,
normalize them into the same accession contract.

Canonical shape:

```text
corpora/<corpus-key>/
  metadata/
    config.json
    catalog.json
  imports/
    <item-id>--<encoded-source-uri>--<slug>.<ext>
    <item-id>--<encoded-source-uri>--<slug>.<ext>.biblicus.yml
```

`imports/` is the canonical home for source materials, including PDFs. If an
older or ad hoc corpus has root-level files such as `<slug>.pdf`, treat that as
a staging layout and run a normalization step that assigns stable item ids,
moves or maps those files into accession entries, and emits
`metadata/catalog.json`. Compatibility readers may support root-level files for
existing corpora, but new publication bootstrap work should not create a second
shape.

The sidecar is recommended for every source entry because it keeps source
metadata close to the material. A sidecar should use stable, boring fields:

```yaml
title: Example Source Material
authors:
  - First Author
media_type: application/pdf
abstract: Brief summary of what this source covers.
biblicus:
  id: stable-item-id
  source: https://example.com/source
dates:
  published_at: "2026-01-15"
  retrieved_at: "2026-05-18T12:00:00Z"
tags:
  - publication-topic
curation:
  corpus_role: source-material
  proposed_topic_uid: optional-initial-topic-suggestion
ingestion_rationale: >
  Briefly explain what this source is, how it relates to the current research
  focus, and why it belongs within the publication mission.
```

`metadata/catalog.json` is the adapter contract into the Papyrus data model. It
should contain one entry per source material with `id`, `relpath`, checksum,
media type, title, source URI, dates, tags, and sanitized metadata. Registration
turns that catalog into GraphQL workflow records: a `KnowledgeImportRun`,
sanitized `KnowledgeRawPayload`, `Reference`, `ReferenceAttachment`,
`Message`, `Assignment`, and `SemanticRelation` records as appropriate.
Papyrus may store provenance and workflow metadata; it must not copy source
text, PDF contents, transcripts, or extraction payloads into GraphQL.

URL-only registration is allowed for curation visibility, but it is not a
corpus accession. A `Reference` with `sourceUri` and no `storagePath` is a
reviewable prospect, not an extraction-ready source. Before text extraction,
create a `reference.corpus-accession` assignment to materialize the source into
the configured Biblicus corpus. Text availability is then represented by a
`ReferenceAttachment` with `role = "extracted_text"` pointing at the corpus
artifact `corpora/<corpus>/extracted/pipeline/<snapshot-id>/text/<item-id>.txt`.
Papyrus records the selected Biblicus snapshot path and metadata; it does not
duplicate extracted text into a second canonical location.

## Bootstrap Procedure

1. Define the publication and corpus set in a steering config. Use
   `corpora/papyrus-steering.yml` as the contract shape, but create a
   publication-specific config rather than hard-coding a corpus key into code.

2. Stage source materials locally under `corpora/<corpus-key>/`. If the starting
   pile is flat, root-level, or otherwise ad hoc, first normalize it into the
   canonical accession: `imports/`, stable item ids, sidecars, and
   `metadata/catalog.json`.

3. Sync the corpus accession to the Amplify Storage bucket under
   `corpora/<corpus-key>/`. For a scratch rebuild rehearsal, do not copy old
   generated `analysis/` output unless the test is specifically import-only.

   ```bash
   poetry run papyrus ops corpora sync-to-cloud \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --dryrun
   ```

4. Materialize configured corpora and semantic relation types in Papyrus.

   ```bash
   poetry run papyrus ops categories sandbox-steering-config \
     --config corpora/papyrus-steering.yml \
     --output .papyrus-runs/<run-id>/sandbox-steering.yml

   poetry run papyrus ops categories import-config --config <steering.yml>
   poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml
   poetry run papyrus knowledge concepts import-types --config corpora/papyrus-semantic-relation-types.yml
   ```

5. Register source materials into the GraphQL workflow. This creates a
   `KnowledgeImportRun` for the batch. Each source material becomes a
   `Reference`; pending references also get one open
   `curation.reference-intake` assignment linked by `requests_work_on`.

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

6. Curate the initial evidence set. Pending and rejected references remain
   visible for review and scope memory, but only current accepted references can
   feed topic modeling, graph analysis, section memory, context packs, assignment
   evidence, or edition planning.

7. Ensure accepted references have source material and text artifacts. Use
   `process-status` to find URL-only or unextracted references, accession the
   sources, run Biblicus extraction through `reference.text-extraction`, and
   register extracted text attachments. Accession and extraction are separate:
   the first creates or updates corpus source files, and the second creates
   Biblicus extraction snapshots that GraphQL references by path. In
   `process-status`, `snapshot_extracted` means Biblicus text exists but no
   `extracted_text` attachment records the selected snapshot yet; `text_ready`
   means a snapshot-backed attachment exists.

   ```bash
   poetry run papyrus references process-status \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --status all

   poetry run papyrus references process-create-accession-assignments \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --status pending \


   poetry run papyrus references process-accession-now \
     --reference <reference-id> \
     --assignee-key <worker-run-id>

   poetry run papyrus references process-extract-text-now \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --assignee-key <worker-run-id>

   poetry run papyrus references process-attach-extracted-text \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --max-count 10 \

   ```

8. Export the accepted-only analysis manifest for Biblicus.

   ```bash
   poetry run papyrus references export-analysis-manifest \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --output .papyrus-runs/<run-id>/accepted-reference-manifest.json
   ```

9. Run Biblicus extraction and topic-modeling from that accepted-only manifest.
   Papyrus records the intent as `analysis.reindex` assignments; Biblicus owns
   execution and artifacts.

10. Import accepted taxonomy, projection, and graph artifacts back into Papyrus
   through the category steering and projection commands.

11. Repeat with adjusted analysis profiles until the top-level category set is
   useful enough to operate as sections and to inform section planning.

## Controlling Topic Granularity

Papyrus exposes safe re-index controls through
`corpora/papyrus-analysis-profiles.yml`. Profiles reference Biblicus
configuration files plus allowed override maps; Papyrus should not duplicate
Biblicus internals.

Use a global topic granularity sweep before treating a discovered topic list as
the publication section map:

```bash
poetry run papyrus analysis reindex-plan \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile global-topic-granularity \
  --corpus-key <corpus-key> \
  --override targetTopicRange=10:20 \
  --override bertopic_analysis.parameters.min_topic_size=8
```

Safe BERTopic controls include:

- `bertopic_analysis.parameters.nr_topics`
- `bertopic_analysis.parameters.min_topic_size`
- `bertopic_analysis.vectorizer.ngram_range`
- `bertopic_analysis.vectorizer.stop_words`
- `bertopic_analysis.umap_model.parameters.n_neighbors`
- `bertopic_analysis.umap_model.parameters.n_components`
- `bertopic_analysis.umap_model.parameters.min_dist`
- `bertopic_analysis.hdbscan_model.parameters.min_cluster_size`
- `bertopic_analysis.hdbscan_model.parameters.min_samples`

Do not force BERTopic to produce the exact number of publication sections if
that damages the analysis. It is acceptable for the generated top-level topic
set to be finer than the eventual publication section set; manual taxonomy
merge/exclusion controls are a separate management layer.

Create a live assignment when the plan is ready:

```bash
poetry run papyrus analysis create-reindex-assignment \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile global-topic-granularity \
  --corpus-key <corpus-key> \
  --override targetTopicRange=10:20 \

```

Then execute from the claimed assignment metadata:

```bash
poetry run papyrus assignments claim \
  --assignment <analysis-assignment-id> \
  --assignee-key "procedure-run:<run-id>" \
  --claim-ttl-seconds 21600

poetry run papyrus analysis execute-assignment \
  --assignment <analysis-assignment-id>
```

Assignment creation records `Assignment`, `AssignmentEvent`, and workflow
relations only. It does not run Biblicus or delete generated data.

## Seeding Semi-Supervised Topic Modeling

Generated reference-to-topic classifications are predictions. They are useful
suggestions, not authoritative labels.

When an editor approves a predicted classification, Papyrus should create an
additional semantic relation with `relationTypeKey = authoritative_label`.
When an editor rejects a generated classification, Papyrus should remove the
generated `classified_as` prediction and store no separate rejection memory for
that classification.

Use a draft category set when the generated topic set is close but not useful
enough. Draft edits do not mutate the current accepted set until promotion:

```bash
poetry run papyrus knowledge topics draft-create \
  --from-category-set <current-category-set-id> \
  --title "Initial topic sculpting pass" \


poetry run papyrus knowledge topics draft-add-topic \
  --category-set <draft-category-set-id> \
  --display-name "<expected topic>" \
  --short-title "<one-or-two-word label>" \
  --subtitle "<short description>" \

```

Manually label accepted references as authoritative examples for draft or
current topics:

```bash
poetry run papyrus references label \
  --reference <accepted-reference-id-or-external-item-id> \
  --category <category-key-or-lineage-id> \
  --category-set <draft-or-current-category-set-id> \
  --note "Why this accepted reference is a good seed example." \

```

Use authoritative labels to build the strict Biblicus seed manifest for
semi-supervised topic classifier training:

```bash
poetry run papyrus knowledge topics export-classifier-seed-manifest \
  --config <steering.yml> \
  --category-set <draft-or-current-category-set-id> \
  --corpus-key <corpus-key> \
  --output .papyrus-runs/<run-id>/seed-manifest.json
```

Then preview classifier retraining:

```bash
poetry run papyrus analysis reindex-plan \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile canonical-topic-classifier \
  --corpus-key <corpus-key> \
  --override seedManifestPath=.papyrus-runs/<run-id>/seed-manifest.json
```

Regular online updates can be affected by the growing label set if the worker
uses a freshly trained classifier or projection profile. The safe operating
pattern is to separate modes:

- `online-update`: process new or changed accepted references with the current
  accepted classifier/profile.
- `classifier-retrain`: rebuild the semi-supervised classifier from accepted
  references and authoritative labels.
- `scoped-topic-rebuild`: rediscover child topics under an accepted section/focus
  scope.
- `entity-graph-rebuild`: rebuild generated entity graph signals.
- `generated-analysis-rebuild`: clear targeted generated outputs for a
  selected profile/import run, then rerun.

## Entity Graph Controls

Entity extraction and graph analysis should also be profile-driven. The first
safe controls are exposed through the `reference-entity-graph` analysis
profile:

- `graph.extractor`
- `graph.configurationName`
- `graph.model`
- `graph.min_entity_length`
- `graph.max_entity_words`
- `graph.include_item_node`
- `graph.window_size`
- `graph.min_cooccurrence`

Preview before creating work:

```bash
poetry run papyrus analysis reindex-plan \
  --profiles corpora/papyrus-analysis-profiles.yml \
  --profile reference-entity-graph \
  --corpus-key <corpus-key> \
  --override graph.min_cooccurrence=3
```

## Sandbox Rehearsal

A full scratch rehearsal should prove that the publication can be rebuilt from
source materials plus config:

1. Deploy or update a sandbox in the correct AWS account.
2. Copy only source accession data to the sandbox S3 bucket.
3. Register references from `metadata/catalog.json`.
4. Accept a seed evidence set.
5. Export an accepted-only manifest.
6. Create `analysis.reindex` assignments for granularity, classifier, scoped
   topics, projection, and entity graph.
7. Claim and execute one assignment at a time.
8. Import generated outputs.
9. Verify the Newsroom shows references, sections, topics, graph relations, and
   assignment history.

If the rehearsal deletes generated GraphQL analysis data, that is acceptable in
a sandbox. Do not delete source files from S3 unless the test explicitly covers
corpus-prefix reconciliation and the local source accession is complete.

## Payload Attachment Maintenance

Private operational payloads for `Message`, `Reference`, `Assignment`,
`AssignmentEvent`, and `KnowledgeRawPayload` live as `ModelAttachment` rows with
S3 objects under `newsroom/payloads/`. DynamoDB rows are indexes; S3 owns the
attached text and JSON.

Operational payload writes go through API-managed upload slots. The client or
CLI reserves a canonical attachment path through GraphQL, uploads bytes to the
short-lived signed S3 URL, and completes the `ModelAttachment` row through
GraphQL. Do not hand out long-lived AWS credentials for normal newsroom payload
uploads. Large Biblicus corpus sync under `corpora/*` is still a worker/admin
operation until a separate corpus accession upload service exists.

Use a smart purge when intentionally resetting a sandbox so attachment objects
are deleted with their index rows:

```bash
poetry run papyrus ops content delete all --yes --delete-attachments
```

Use attachment pruning after hard resets, failed clone experiments, or manual
repair work. Dry-run is default:

```bash
poetry run papyrus sections prune-attachments
poetry run papyrus sections prune-attachments
```

`prune-attachments` removes two classes of maintenance garbage: attachment
index rows whose owner record no longer exists, and `newsroom/payloads/` S3
objects that no current `ModelAttachment` row references. It must not be pointed
at `corpora/` prefixes; source accession files are durable corpus material, not
operational payload garbage.

## What Not To Do

- Do not treat filesystem folders or catalogs as operational queues. Once a
  catalog is registered, monitor and control intake through GraphQL
  `Reference`, `Assignment`, `Message`, `SemanticRelation`, and
  `KnowledgeImportRun` records.
- Do not use pending, rejected, or archived references as evidence or context.
- Do not create publication `Item` rows for source materials or assignments.
- Do not copy source text, PDFs, transcripts, or raw extraction payloads into
  GraphQL.
- Do not hard-code a pilot corpus name, topic list, classifier id, or subject
  area into Papyrus application logic.
- Do not edit Biblicus source from Papyrus; request a Biblicus contract change
  when the execution layer needs new functionality.
