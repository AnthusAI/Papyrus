---
name: category-steering
description: Use this skill when working on Papyrus category, taxonomy, graph, reference, curation-cycle, Biblicus integration, S3 corpus, or production authoring workflows.
---

# Category Steering Skill

Use this skill when you need to run, debug, document, or change Papyrus category
steering, taxonomy steering, graph steering, reference visibility, projection
imports, or curation-cycle operations.

Papyrus is the human steering and publication system. Biblicus is the corpus
artifact producer. Papyrus may invoke Biblicus CLI commands, but do not edit
`/Users/ryan/Projects/Biblicus` source from this repo. If Biblicus needs a new
contract or command, relay the request to the Biblicus agent.

The AI/ML corpora are pilot data only. Papyrus must remain a generalized
newsroom: corpus names, classifier ids, categories, and research domains come
from configuration and steering state, not application logic.

## Files To Read First

- `corpora/papyrus-steering.yml`: publication corpus keys, roles, classifier
  ids, local paths, and S3 prefixes.
- `corpora/papyrus-semantic-concepts.yml`: preloaded semantic concept nodes,
  including global editorial forms and corpus-scoped comment concepts.
- `corpora/papyrus-lexical-steering.yml`: default lexical steering such as
  ignored keyword noise and keyword display limits.
- `corpora/papyrus-analysis-profiles.yml`: YAML-backed Biblicus analysis and
  re-index profiles for topic modeling, classifier retraining, projection, and
  entity-graph work.
- `papyrus`: CLI command registration.
- `src/papyrus_content/steering.py`: steering config parsing and corpus
  resolution.
- `src/papyrus_content/categories_steering.py`: category/reference/proposal import and
  export logic.
- `src/papyrus_content/curation_cycle.py`: repeatable curation-cycle
  orchestration.
- `amplify/data/resource.ts`: GraphQL data model and auth rules.
- `AGENTS.md`: current Papyrus operating constraints.

Read `/Users/ryan/Projects/Biblicus/docs/` only for Biblicus command contracts.
Do not modify Biblicus files.

## Auth Setup

The content CLI signs every AppSync request with SigV4 (IAM) from the standard
AWS credential chain. It does not use a browser login, Cognito editor session,
stored token, or local auth-session cache.

Production authoring environment:

```bash
export AWS_PROFILE=Ryan
export AWS_REGION=us-east-1
export PAPYRUS_GRAPHQL_ENDPOINT="https://64hviw44q5cq5nwjcigmasowlq.appsync-api.us-east-1.amazonaws.com/graphql"
```

Set `AWS_PROFILE` to a profile that can assume the production site's
`<siteId>-papyrus-authoring` role (`docs/site-hosting.md`, "Running the CLI
locally"). Nothing is stored in `.env`.

Smoke-check the authoring credentials before mutating data:

```bash
poetry run papyrus ops content inspect
```

## Steering Config And S3 Corpus Rules

`corpora/papyrus-steering.yml` is the tracked v1 steering config contract and
should be mirrored to S3 beside corpus data. CLI config resolution order is:

1. `--config <path>`
2. `PAPYRUS_STEERING_CONFIG`
3. `corpora/papyrus-steering.yml`

Materialize configured corpora into GraphQL after changing config:

```bash
poetry run papyrus ops categories import-config --config corpora/papyrus-steering.yml
```

The production Amplify Storage bucket owns private corpus prefixes:

```bash
export PAPYRUS_CORPORA_BUCKET="amplify-dbsyytcm9drqa-mai-papyrusmediabucket0dab24-4hstaautjdqo"
aws s3 cp corpora/papyrus-steering.yml \
  s3://$PAPYRUS_CORPORA_BUCKET/corpora/papyrus-steering.yml
```

Local `corpora/` folders are working copies only. Durable corpus data lives in
S3 under private `corpora/*` prefixes. Do not make the bucket raw-public. Do not
use `aws s3 sync --delete` unless this worker is intentionally reconciling S3 to
its complete local working copy.

Before a worker claims analysis work, verify that local corpus, S3 corpus, and
GraphQL reference state agree:

```bash
poetry run papyrus ops corpora worker-bootstrap \
  --config <steering.yml> \
  --json

poetry run papyrus ops corpora status \
  --config <steering.yml> \
  --corpus-key <corpus-key> \
  --json
```

Use `corpora sync-from-cloud` to initialize a new Mac or EC2 worker from S3, and
`corpora sync-to-cloud` after adding new local corpus material. S3 sync does not
register references in GraphQL; `references create-from-catalog` is still required
for Newsroom visibility and curation.

Papyrus imports steering state, artifact refs, strict private `Reference`
metadata, `ReferenceAttachment` paths, `Message` rows,
`SemanticNode` rows, `SemanticRelation` links, proposals, decisions, and stable
external `item_id` references. It does not mirror source text, PDFs,
transcripts, extraction output, or Biblicus corpus internals into GraphQL.

`corpora/papyrus-semantic-concepts.yml` is the tracked seed file for semantic
concept nodes that Papyrus owns directly. Use it for durable, publication-wide
or corpus-scoped ontology terms such as editorial forms. The curation import and
projection paths upsert these nodes idempotently.

`corpora/papyrus-lexical-steering.yml` is the tracked seed file for default
ignored keyword rules and keyword display limits. `categories import-config`
also materializes these defaults into private `LexicalSteeringRule` rows. Editors
can add more ignored terms from `/newsroom/topics`; export active rules before a
new analysis cycle with:

```bash
poetry run papyrus ops categories export-lexical-steering \
  --output /tmp/papyrus-lexical-steering.json
```

Papyrus can export this lexical steering today. Biblicus must explicitly accept
that contract before agents assume taxonomy discovery or topic classifier
training can consume it directly. Until then, relay that request to the Biblicus
agent instead of editing Biblicus source.

## Analysis Profiles And Re-Index Assignments

Papyrus records analysis/re-index intent as private `Assignment` work. It does
not execute Biblicus or clear generated GraphQL records when an assignment is
created.

Validate and inspect the YAML-backed profiles:

```bash
poetry run papyrus analysis validate-profiles \
  --profiles corpora/papyrus-analysis-profiles.yml

poetry run papyrus analysis profiles \
  --profiles corpora/papyrus-analysis-profiles.yml
```

Preview the exact Biblicus command plan before creating work:

```bash
poetry run papyrus analysis reindex-plan \
  --profile canonical-topic-classifier \
  --corpus-key AI-ML-research \
  --override bertopic_analysis.parameters.nr_topics=14
```

Create live work only after the preview is acceptable:

```bash
poetry run papyrus analysis create-reindex-assignment \
  --profile canonical-topic-classifier \
  --corpus-key AI-ML-research \

```

Execute claimed analysis work from assignment metadata (worker/operator path):

```bash
poetry run papyrus analysis execute-assignment \
  --assignment <analysis-assignment-id>
```

Run immediate assignment-backed execution in one step:

```bash
poetry run papyrus analysis run-now \
  --profile canonical-topic-classifier \
  --corpus-key AI-ML-research \
  --override bertopic_analysis.parameters.nr_topics=14
```

Process queued assignments in deterministic batches (priority desc, createdAt asc):

```bash
poetry run papyrus assignments process-queue \
  --type analysis.reindex \
  --status open \
  --max-count 10 \
  --stop-on-error false
```

The assignment metadata must preserve the profile key, scope, re-index mode,
safe parameter overrides, command plan, expected outputs, and dry-run
destructive preview. Assignment creation writes only `Assignment`,
`AssignmentEvent`, and workflow `SemanticRelation` rows.

Re-index execution requires an exclusive assignment claim. Treat
`Assignment.assigneeKey` as the flexible lease identity for the current worker
cycle. It may be a user profile, a procedure run, an OS process, or any other
string that is unique within the competing worker pool. `assigneeType` and
`assigneeId` are optional detail fields; `assigneeKey` is the coordination key.
Use a TTL for worker claims so crashed agents do not hold work forever:

```bash
poetry run papyrus assignments claim \
  --assignment <assignment-id> \
  --assignee-key "procedure-run:<run-id>" \
  --claim-ttl-seconds 21600
```

An unexpired claim by a different `assigneeKey` blocks another worker from
claiming the assignment. The same `assigneeKey` may claim again to refresh the
lease, and expired claims may be taken over. Do not run the Biblicus command
plan for `analysis.reindex` work before the assignment is claimed.

## Manual Topic Sculpting

Use draft category sets when humans or agents need to shape the canonical topic
set before classifier retraining. Do not hard-delete accepted historical
categories. Draft edits write new `CategorySet` / `Category` rows, and
promotion supersedes the previous current version.

Create and edit a draft:

```bash
poetry run papyrus knowledge topics draft-create \
  --from-category-set <current-category-set-id> \
  --title "Topic sculpting draft" \


poetry run papyrus knowledge topics draft-add-topic \
  --category-set <draft-category-set-id> \
  --display-name "Agent Tooling" \
  --short-title "Tools" \
  --subtitle "Tool use" \


poetry run papyrus knowledge topics draft-update-topic \
  --category <category-id-or-key> \
  --display-name "Clearer topic name" \


poetry run papyrus knowledge topics draft-archive-topic \
  --category <category-id-or-key> \

```

Manual reference labels are immediate authoritative labels. They are allowed
only for current accepted `Reference` rows:

```bash
poetry run papyrus references label \
  --reference <reference-id-or-external-item-id> \
  --category <category-key-or-lineage-id> \
  --category-set <draft-or-current-category-set-id> \
  --note "Why this reference is a good seed example." \


poetry run papyrus references labels --reference <reference-id-or-item-id>
```

Export the strict Biblicus seed manifest from authoritative labels, then pass it
to classifier retraining as the `seedManifestPath` override:

```bash
poetry run papyrus knowledge topics export-classifier-seed-manifest \
  --config corpora/papyrus-steering.yml \
  --category-set <draft-or-current-category-set-id> \
  --corpus-key <corpus-key> \
  --output .papyrus-runs/<run-id>/seed-manifest.json

poetry run papyrus analysis preview-reindex \
  --profile canonical-topic-classifier \
  --corpus-key <corpus-key> \
  --override seedManifestPath=.papyrus-runs/<run-id>/seed-manifest.json
```

Promote only when the draft is ready to become the accepted publication basis:

```bash
poetry run papyrus knowledge topics draft-promote \
  --category-set <draft-category-set-id> \

```

## Regular Curation Cycle

Prefer the repeatable cycle command over hand-running every step:

```bash
export BIBLICUS_WORKDIR="/Users/ryan/Projects/Biblicus"
poetry run papyrus ops categories run-curation-cycle --config corpora/papyrus-steering.yml
```

For a reference-ingest task, this cycle is the normal production GraphQL import
step after Biblicus local corpus work and explicit S3 sync. "Do not run it
casually" means do not run it accidentally or without correct production auth;
if the user asked for cloud import, run it deliberately and verify the result.

The cycle does not sync S3. If local corpus files or Biblicus artifacts changed,
sync the configured corpus working copy to its private S3 prefix first, with
`aws s3 sync --dryrun` reviewed before the real sync.

`analysis run-now` and `analysis execute-assignment` pull from S3 automatically
when the local catalog is missing or stale (`corpora sync-from-cloud`
semantics). Pass `--skip-sync-from-cloud` to skip or `--sync-from-cloud` to
force a pull before Biblicus runs.

The cycle uses the steering config to discover the canonical corpus and source
corpora. It stores output under `.papyrus-runs/<timestamp>/`, including
accepted category JSON, accepted category-tree JSON, steering feedback, lexical
steering, projection JSON, Biblicus logs, and `verification.json`.

The cycle runs:

1. `categories import-config`
2. canonical `categories import-steering`
3. export accepted category set, category tree, steering feedback, and lexical
   steering
4. Biblicus taxonomy record/discover, seed-manifest render, classifier train,
   and projection for configured source corpora
5. `categories import-projection`
6. re-import steering after recorded proposal bundles
7. verification of references, `classified_as` relations, and relation targets

`classified_as` relations come from projection import. If Newsroom topic
reference counts are zero after references exist, inspect projection import
resolution first.

Biblicus topic modeling is an optional Biblicus extra. The Papyrus cycle invokes
Biblicus with `uv run --extra topic-modeling`; do not change Biblicus source to
work around missing optional dependencies.

## Manual Troubleshooting Commands

Import the configured corpus records:

```bash
poetry run papyrus ops categories import-config --config corpora/papyrus-steering.yml
```

Import steering artifacts for one configured corpus:

```bash
poetry run papyrus ops categories import-steering \
  --config corpora/papyrus-steering.yml \
  --corpus-key AI-ML-research
```

Export accepted category state and review memory:

```bash
poetry run papyrus knowledge topics export-category-set \
  --category-set <category-set-id> \
  --output /tmp/accepted-category-set.json

poetry run papyrus ops categories export-category-tree \
  --category-set <category-set-id> \
  --output /tmp/accepted-category-tree.json

poetry run papyrus ops categories export-steering-feedback \
  --category-set <category-set-id> \
  --output /tmp/papyrus-steering-feedback.json
```

Rejected proposals are not cosmetic. Pass exported steering feedback to
Biblicus taxonomy and graph proposal commands so rejected child topics,
relationships, labels, and weak patterns are suppressed in future proposal
cycles.

Typical Biblicus loop from the Biblicus checkout:

```bash
cd /Users/ryan/Projects/Biblicus

uv run biblicus taxonomy record \
  --corpus corpora/AI-ML-research \
  --input /tmp/accepted-category-tree.json

uv run biblicus taxonomy discover \
  --corpus corpora/AI-ML-research \
  --classifier ai-ml-research \
  --steering-feedback /tmp/papyrus-steering-feedback.json \
  --record

uv run biblicus steering render-seed-manifest \
  --input /tmp/accepted-category-set.json \
  --output corpora/AI-ML-research/metadata/topic-classifiers/ai-ml-research/seed-manifest.json

uv run --extra topic-modeling biblicus topic-classifier train \
  --corpus corpora/AI-ML-research \
  --manifest corpora/AI-ML-research/metadata/topic-classifiers/ai-ml-research/seed-manifest.json \
  --configuration configurations/topic-classifier.yml \
  --extraction-snapshot <snapshot-ref>

uv run --extra topic-modeling biblicus topic-classifier project \
  --classifier-corpus corpora/AI-ML-research \
  --target-corpus corpora/AI-ML-history \
  --classifier ai-ml-research \
  --extraction-snapshot <snapshot-ref> \
  --all \
  --record \
  --format json > /tmp/projection.json
```

Import a projection with config-derived corpus ids:

```bash
cd /Users/ryan/Projects/Papyrus
poetry run papyrus ops categories import-projection \
  --config corpora/papyrus-steering.yml \
  --target-corpus-key AI-ML-history \
  --authority-corpus-key AI-ML-research \
  --bundle /tmp/projection.json \
  --classifier ai-ml-research
```

The AI/ML names above are pilot examples. For another publication, use the
corpus keys and classifier ids from that publication's steering config.

## Graph, Taxonomy, And Ontology Notes

Papyrus v1 keeps canonical category copy typed, imports accepted taxonomy into
`CategorySet` and `Category`, and reviews taxonomy/ontology/graph proposals
through generic proposal rows. Accepted graph and ontology artifacts may
materialize private `SemanticNode` and `SemanticRelation` rows for Newsroom and
procedure queries.

Biblicus proposal labels such as `recommend`, `do_not_recommend`, and
`needs_clarification` are agent recommendation labels. Papyrus human decisions
remain `accept`, `reject`, or no action, recorded as append-only decisions.

If a Biblicus output contract is unclear or broken, stop changing Papyrus around
it and relay the concrete issue to the Biblicus agent. Useful escalation details
include the command, cwd, input artifact path, output path, stderr, and the
expected contract.

## Reference Intake Boundary

Use `skills/reference-intake/SKILL.md` for new knowledge-base source materials,
reference metadata, reference attachments, intake assignments, and Biblicus
ingestion handoffs. Category steering imports may create `Reference` rows as a
side effect of steering/projection artifacts, but the source-material intake
rules live in the reference-intake skill.

## Verification Checklist

Run the focused checks after changing category steering code or this skill:

```bash
npm run test:categories
npm run lint
npm run typecheck
```

Run `npm run build` when runtime, schema, or UI code changed.

After a real curation-cycle run, inspect `.papyrus-runs/<timestamp>/verification.json`
and confirm:

- `Reference` rows are present.
- `classified_as` relations are nonzero when projections were expected.
- relation targets resolve to existing categories and references.
- graph/proposal imports did not duplicate corpus content into GraphQL.

Local Newsroom smoke:

```bash
curl -I http://localhost:3000/newsroom
```

If the dev server is on another port, use that port. Do not stop a user-owned
dev server unless asked.
