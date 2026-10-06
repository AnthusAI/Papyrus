---
name: reference-intake
description: Use this skill when processing or registering new Papyrus knowledge-base references, source materials, corpus attachments, reference-intake assignments, or Biblicus handoffs.
---

# Reference Intake Skill

Use this skill when new source materials need to become visible in Papyrus as
knowledge-base references, or when debugging why newly processed corpus materials
are not visible in the Newsroom.

After references exist and need budgeted summaries or quality ratings, use
[`skills/reference-curation-signals/SKILL.md`](/Users/ryan/Projects/Papyrus/skills/reference-curation-signals/SKILL.md).

If the source material came from a research agent packet, first use
[`skills/newsroom-research-workflow/SKILL.md`](/Users/ryan/Projects/Papyrus/skills/newsroom-research-workflow/SKILL.md)
to inspect the assignment packet. Use `assignments process-proposals` or
`assignments process-research-now` to turn `proposedReferences` into pending
reference-intake work; manual catalog construction is now the fallback.

Papyrus owns newsroom visibility, reference metadata, assignments, comments,
semantic links, and editorial steering state. Biblicus owns corpus ingestion,
source files, extraction artifacts, classifier artifacts, graph artifacts, and
reproducible worker commands. Do not edit `/Users/ryan/Projects/Biblicus`
source from Papyrus.

## Terminology Contract

Use this language consistently in operator-facing guidance:

- `reference processing`: full DOI/URL-to-usable-reference workflow.
- `process reference`: verb for running that workflow.
- `register reference`: create the initial sparse `Reference`.
- `curate reference`: editor decision workflow only.
- `ingest`: Biblicus corpus-storage term.
- `import`: config/artifact transfer term.

Legacy command and assignment names may still use `intake`; treat those as
historical command ids, not the preferred operator verb.

## Completion Contract

If the user asks to process, register, add, or research new references without
saying "local only," the task is not done until the new references are
cloud-visible:

1. the materials are in the correct local Biblicus corpus working copy;
2. Biblicus ingest/extraction has succeeded locally;
3. the changed corpus working copy has been synced to the configured private S3
   `corpora/*` prefix, using a reviewed `aws s3 sync --dryrun` first;
4. the Papyrus production curation cycle has completed through the IAM
   authoring role;
5. Newsroom/GraphQL verification shows the new `Reference` rows or explains
   why they are not expected yet.

"Do not run production casually" means run production steps deliberately with
the correct AWS profile, endpoint, and config. It does not mean stop before
S3 sync or GraphQL import when the user asked for cloud import.

If you lack AWS access, a authoring role, or permission to mutate production,
state the exact blocker and report "local-only / not imported into Papyrus."
Do not claim references are imported into Papyrus until the curation cycle and
verification have succeeded.

## Files To Read First

- `corpora/papyrus-steering.yml`: configured corpora, corpus keys, local paths,
  S3 prefixes, roles, and classifier ids.
- `skills/category-steering/SKILL.md`: production auth setup, curation-cycle
  commands, S3 corpus rules, and Biblicus escalation rules.
- `src/papyrus_content/categories_steering.py`: current reference, attachment, message,
  assignment, and semantic-relation import mappers.
- `amplify/data/resource.ts`: `Reference`, `ReferenceAttachment`,
  `Message`, `Assignment`, and `SemanticRelation` schema/auth rules.
- `lib/category-repository.ts`: private Newsroom data shape for references and
  assignments.

Read Biblicus docs only for command contracts. If the handoff contract is
missing, ask the Biblicus agent for it instead of patching Biblicus source.

## Data Boundary

Knowledge-base source materials are `Reference` records, not publication
`Item` rows. Publication `Item` rows are CMS objects such as articles, briefs,
promos, ads, and reader-facing edition content. Assignments are private
`Assignment` records. Do not create `Item` rows with `type: "assignment"` and
do not use `Item` rows for corpus references.

GraphQL is the operational source of truth after registration. Files, folders,
and catalogs are adapters into this workflow; they are not the queue. GraphQL
stores strict private metadata and relationships only:

- `KnowledgeImportRun`: the registration batch or generated-artifact import
  that operators can inspect.
- `KnowledgeRawPayload`: sanitized catalog/import summaries for monitoring,
  never source bodies or extraction content.
- `Reference`: stable Biblicus `item_id`, title, authors, source URI,
  normalized S3/corpus path, media type, checksums, dates, sanitized metadata.
- `ReferenceAttachment`: private file-path metadata for source PDFs, text,
  transcripts, extraction JSON, and auxiliary corpus files.
- `Message`: append-only private commentary such as ingestion rationale and
  reference-curation notes.
- `Assignment`: private work item such as `curation.reference-intake`.
- `SemanticRelation`: typed links from assignments/messages/references to exact
  target lineages such as `Reference`, `Category`, or `SemanticNode`.

Do not store source text, PDFs, transcripts, abstracts, raw extraction payloads,
or private source notes directly in GraphQL. Those stay in private S3
`corpora/*` prefixes or Biblicus corpus working copies. GraphQL may store a
path, checksum, media type, and sanitized provenance.

Text availability is tracked as attachment metadata, not DynamoDB content. When
Biblicus has produced text, register a `ReferenceAttachment` with
`role = "extracted_text"` that points at the Biblicus extraction snapshot text:
`corpora/<corpus>/extracted/pipeline/<snapshot-id>/text/<item-id>.txt`. Keep
Biblicus snapshot metadata on the attachment so agents can see which extractor,
configuration, and stage produced the selected text. Do not copy that text into
`Reference.metadata`, `Message.body`, or a raw payload.

Use `references process-status` to distinguish `snapshot_extracted` from
`text_ready`. A snapshot-only reference still needs `process-attach-extracted-text` to
register the selected snapshot path before it is eligible for analysis
manifests.

## Stable IDs

Use stable identifiers everywhere:

- corpus identity comes from `corpora/papyrus-steering.yml`;
- Biblicus item identity is `item_id`;
- Papyrus reference lineage is derived from corpus id plus `item_id`;
- attachment identity is derived from reference version, role, sort key, and
  storage/source path;
- category links use current category lineages, not display names;
- checksums and S3 paths are metadata, not primary identity.

Display names, titles, and source labels are editable copy. Do not key records
or URLs from them.

## Reference Status Policy

Papyrus uses `Reference.curationStatus` as the editor decision field:

- `pending`: a reference prospect that is visible for curation.
- `accepted`: an accepted reference that is eligible for evidence sets, topic
  modeling manifests, graph analysis, desk memory, context packs, and edition
  planning.
- `rejected`: a rejected reference retained as scope memory. Only
  `out_of_scope` and `policy_exclusion` rejections become negative examples in
  the scope training set.
- `archived`: retained but inactive.

Do not use pending, rejected, or archived references as publishable evidence or
agent context. They may appear in the Reference Ledger, curation assignments,
comments, votes, and scope-training exports.

Every pending reference prospect registered through `references create-from-catalog`
needs an ingestion rationale. Provide it in the catalog as
`ingestion_rationale` or through `--ingestion-rationale`. The rationale should
briefly summarize the source material, explain how it relates to the current
research focus, and explain why it fits the publication mission.

When a research packet supplies `proposedReferences`, each proposal is still
only a reference prospect. Register it through `assignments process-proposals`,
`assignments process-research-now`, `references create-from-catalog`, or the
repeatable Biblicus corpus path before any curation or evidence use. Do not copy
web-search `evidence_candidate_id` values into `evidenceItemIds`; those are audit
identifiers, not accepted reference ids.

URL-only prospects are reviewable but not extraction-ready. If
`Reference.sourceUri` is set and `Reference.storagePath` is empty, the source
material still needs a `reference.corpus-accession` assignment before Biblicus
can extract text. For arXiv abstract URLs, the accession step should resolve the
PDF URL and store the PDF in the corpus accession.

Accession and extraction are separate workflow concepts. `reference.corpus-accession`
materializes the source file. `reference.text-extraction` runs Biblicus
extraction for accessioned sources and registers snapshot-backed text artifacts as
`ReferenceAttachment` rows. Neither workflow stores raw source bytes or
extracted text in DynamoDB.

YouTube references (`video/youtube`, `youtu.be`, `watch?v=`) skip PDF accession.
Use `references process-fetch-url-text` to pull transcript markdown via
Biblicus/MarkItDown. Caption fetches can hit YouTube rate limits; Biblicus retries
with long exponential backoff (default up to one hour). Tune with:

- `BIBLICUS_YOUTUBE_TRANSCRIPT_MAX_WAIT_SECONDS` (default `3600`)
- `BIBLICUS_YOUTUBE_TRANSCRIPT_INITIAL_BACKOFF_SECONDS` (default `30`)
- `BIBLICUS_YOUTUBE_TRANSCRIPT_MAX_BACKOFF_SECONDS` (default `300`)

After the first failed attempt, retries call `youtube-transcript-api` directly
instead of re-running MarkItDown, to reduce duplicate caption requests.

## Research Packet Intake Path

For normal agent-discovered sources, do not hand-build a catalog. Convert the
latest linked `research_packet` for an assignment into pending references and
curation assignments:

```bash
poetry run papyrus assignments process-proposals \
  --assignment <assignment-id> \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --status pending \
 \
  --json
```

If the research run has not happened yet, use the one-command path:

```bash
poetry run papyrus assignments process-research-now \
  --assignment <assignment-id> \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --research-mode source_discovery \
  --max-evidence-items 20 \
 \
  --json
```

These commands deduplicate proposals by normalized URL, preserve each proposal's
`ingestion_rationale`, write a run-local
`.papyrus-runs/<run-id>/research-proposals-catalog.json`, and use targeted
deterministic record lookups for research-generated catalogs instead of broad
model scans. They create pending `Reference` rows and
`curation.reference-intake` assignments only; they do not accept references,
create evidence relations, create publication items, or run analysis.

For automation, prefer `poetry run papyrus ... --json`. The JSON
result includes a compact `references[]` list with reference id, item id, title,
URL, source domain, curation assignment id, source-readiness state, and the next
source command. Re-running the same packet intake should report the same
references as existing/no-op rows. Use low-level `references create-from-catalog`
only for arbitrary manual catalogs, compatibility debugging, or fallback
inspection.

## Human-Agent Screening Loop

After proposal intake, handle references one at a time unless the user clearly
asks for a batch decision. The agent should present the source title, URL,
domain, ingestion rationale, source-readiness state, and its recommendation,
then ask for or record the human decision.

Useful inspection command:

```bash
poetry run papyrus references process-status \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --status pending \
  --limit 25
```

Accepted means "this belongs in the knowledge base and can become evidence
after source text is available." Rejected means "retain this as scope memory,
but do not use it as evidence." Archive is for inactive records that should not
be part of active curation.

Decision commands:

```bash
poetry run papyrus references review-curation \
  --reference <reference-id> \
  --action accept \
  --note "<why accepted>"

poetry run papyrus references review-curation \
  --reference <reference-id> \
  --action reject \
  --reason-code out_of_scope \
  --note "<why rejected>"
```

`review-curation` mutates immediately through the protected GraphQL action. It
does not require an apply flag.

The post-acceptance completion sequence is:

1. Accession URL-only accepted references into the configured Biblicus corpus if
   `storagePath` is missing.
2. Run text extraction and register `extracted_text` `ReferenceAttachment`
   rows.
3. Create or assess quality ratings and budgeted summaries using
   `skills/reference-curation-signals/SKILL.md`.
4. Sync the derived vector index using `skills/knowledge-query/SKILL.md`.
5. Export accepted-only manifests before topic modeling or entity-graph work.

Use this standard curation sequence for recent references:

1. `poetry run papyrus ops content inspect`
2. `poetry run papyrus references curate-recent --corpus-key <key> --since-hours 48 --max-count 25 --dry-run --json`
3. rerun without `--dry-run` after reviewing dry-run diagnostics.

`references curate-recent` enforces identifier prepass before title/subtitle,
summary, and quality updates. It writes a resumable manifest at
`.papyrus-runs/reference-curation-<run-id>/manifest.json`; use `--resume` to
continue unfinished runs without redoing completed successful stages.

Do not confuse these stages. A pending URL is only a prospect. An accepted URL
without corpus text is evidence-eligible by curation policy, but not yet useful
for extraction, vector indexing, topic modeling, or entity graph analysis.

## Current Intake Path

Reference visibility is created either through direct catalog registration or
through Biblicus corpus work, S3 sync, and curation import/projection outputs:

```bash
poetry run papyrus references create-from-catalog \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --catalog <catalog.json> \
  --status pending \
  --ingestion-rationale "<summary, research focus, editorial mission fit>" \

```

1. Put each source material in the correct configured Biblicus corpus. For the
   current pilot, journalism/publishing/automated-news papers belong in
   `AI-ML-journalism` unless they are intentionally part of the canonical
   `AI-ML-research` authority corpus.
2. Run or verify Biblicus ingest/extraction from the Biblicus checkout with
   `uv run biblicus ...`, producing local corpus artifacts.
3. Sync the changed corpus working copy to the configured S3 prefix. Review the
   dry run first and do not use `--delete` unless explicitly reconciling the
   complete prefix. Prefer the Papyrus wrapper so endpoint/bucket mismatches are
   caught before the AWS command runs:

   ```bash
   poetry run papyrus ops corpora sync-to-cloud \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --dryrun
   ```

   On a new worker machine, pull the durable corpus down before running
   Biblicus:

   ```bash
   poetry run papyrus ops corpora sync-from-cloud \
     --config <steering.yml> \
     --corpus-key <corpus-key> \
     --dryrun
   ```

   Repeat the same command without `--dryrun` only after reviewing the output.
4. Papyrus imports Biblicus artifacts through the IAM authoring role:

   ```bash
   poetry run papyrus ops categories import-steering \
     --config corpora/papyrus-steering.yml \
     --corpus-key <corpus-key>

   poetry run papyrus ops categories import-projection \
     --config corpora/papyrus-steering.yml \
     --target-corpus-key <source-corpus-key> \
     --authority-corpus-key <canonical-corpus-key> \
     --bundle <projection.json> \
     --classifier <classifier-id>
   ```

5. The mapper creates or updates private `Reference` rows, private
   `ReferenceAttachment` rows, optional ingestion-rationale `Message`
   rows, `curation.reference-intake` `Assignment` rows, and `SemanticRelation`
   links.
6. The Newsroom reads the private models for signed-in editor/admin users.

Prefer the full repeatable cycle when the goal is category/reference visibility
after new corpus work:

```bash
export BIBLICUS_WORKDIR="/Users/ryan/Projects/Biblicus"
poetry run papyrus ops categories run-curation-cycle --config corpora/papyrus-steering.yml
```

Use `skills/category-steering/SKILL.md` for the full cycle and auth setup. The
cycle does not sync S3; do the S3 sync explicitly before the cycle when corpus
files changed.

## Newsroom Verification

After import, verify from the editor/private side:

- `/newsroom/references` shows the new references or updated reference counts.
- `/newsroom/assignments` shows `curation.reference-intake` assignments for
  references that need human or agent review.
- a selected reference has attachment metadata, ingestion rationale if available,
  and semantic links to categories or other graph objects when expected.
- the curation-cycle `verification.json` has nonzero current references and no
  unresolved reference relations when projections were expected.

CLI checks:

```bash
poetry run papyrus ops content inspect
poetry run papyrus ops categories run-curation-cycle --config corpora/papyrus-steering.yml
```

`poetry run papyrus ops content inspect` is the hard auth preflight before any live
CLI smoke run. If it fails, stop and fix the AWS profile or role before running additional
reference commands.

Inspect `.papyrus-runs/<timestamp>/verification.json` after the cycle.

When reporting completion, include: corpus key, Biblicus `item_id`s, whether S3
sync completed, curation-cycle run directory, verification result, and any
references that failed to surface.

## Direct Reference Registration CLI

Papyrus has a direct registration command for making Biblicus catalog/accession
metadata visible in GraphQL without turning the material into evidence:

```bash
poetry run papyrus references prepare-catalog \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --catalog <metadata/catalog.json> \
  --output .papyrus-runs/<run-id>/<corpus-key>-prepared-catalog.json

poetry run papyrus references create-from-catalog \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --catalog .papyrus-runs/<run-id>/<corpus-key>-prepared-catalog.json \
  --status pending \

```

Use `prepare-catalog` for sandbox bootstrap rehearsals or legacy catalogs that
lack item-level `ingestion_rationale`. It writes a run-local prepared catalog
and must not rewrite source corpus metadata unless the user explicitly asks.

Rejected registrations require structured scope memory:

```bash
poetry run papyrus references create-from-catalog \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --catalog <metadata/catalog.json> \
  --status rejected \
  --reason-code out_of_scope \
  --note "Outside the publication mission." \

```

`create-from-catalog` applies by default. With `--dry-run`, it only previews a
`KnowledgeImportRun`, sanitized `KnowledgeRawPayload`, `Reference`,
`ReferenceAttachment`, curation `Message`, `curation.reference-intake`
`Assignment`, and audit/workflow `SemanticRelation` rows. Pending references get
one open curation assignment each. Rejected registrations create curation
commentary but no open review assignment unless explicitly requested. It must
not create `Item`, `EditionItem`, `classified_as`, or `uses_evidence` records.

To start from a live assignment research packet:

```bash
poetry run papyrus assignments process-proposals \
  --assignment <assignment-id> \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --status pending \

```

Use `assignments research-packets --assignment <assignment-id>` only when you
need to inspect packets manually. If `process-proposals` cannot handle a packet,
use the listed `proposedReferences` to build fallback catalog metadata,
preserving each proposal's ingestion rationale. The catalog registration step is
what makes the prospect visible as a pending or rejected `Reference`.

Export accepted-only manifests before analysis runs:

```bash
poetry run papyrus references process-status \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --status all

poetry run papyrus references process-create-accession-assignments \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --status pending \


poetry run papyrus references process-accession-now \
  --reference <reference-id> \
  --assignee-key <worker-run-id>

poetry run papyrus references process-extract-text-now \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --assignee-key <worker-run-id>

poetry run papyrus references process-attach-extracted-text \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --max-count 10 \


poetry run papyrus references export-analysis-manifest \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --output /tmp/accepted-reference-manifest.json

poetry run papyrus references export-scope-training \
  --config corpora/papyrus-steering.yml \
  --corpus-key <corpus-key> \
  --output /tmp/reference-scope-training.json
```

Biblicus should remain responsible for source ingestion, extraction, corpus
sidecars, classifier artifacts, graph artifacts, and reproducible analysis
commands. Papyrus should remain responsible for GraphQL visibility, editor
review workflow, assignments, comments, semantic links, accepted-only analysis
manifests, and scope-training exports.

Operational payload attachments are separate from source accession material.
Messages, assignment payloads, raw payload snapshots, and rich reference
metadata are stored under `newsroom/payloads/` as `ModelAttachment` records.
Use the API-managed upload-slot flow for those payloads; do not require client
or CLI users to have long-lived AWS credentials just to write `ModelAttachment`
objects. The client reserves a slot through GraphQL, uploads to the short-lived
signed URL, then completes the attachment through GraphQL.
For sandbox rebuilds, use `content delete all --yes --delete-attachments` or
`newsroom prune-attachments` to clean those payloads. Never use those
maintenance commands as a substitute for corpus accession cleanup under
`corpora/`.

If the direct CLI needs a Biblicus feature, ask the Biblicus agent for a stable
contract such as Papyrus intake id to Biblicus `item_id` mapping, artifact path
mapping, full-corpus S3 sync, or locking. Do not patch Biblicus source from
Papyrus.

## Verification Checklist

Run these after changing reference-intake docs or mappers:

```bash
npm run test:categories
npm run lint
npm run typecheck
```

Run `npm run build` only when runtime, schema, or UI code changed.
