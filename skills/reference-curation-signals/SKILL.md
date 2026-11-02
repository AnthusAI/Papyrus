---
name: reference-curation-signals
description: Use this skill when creating, updating, querying, or consuming Papyrus Reference title/subtitle enrichment, summaries, and quality ratings for curation, ranking, context packs, or Tactus procedures.
---

# Reference Curation Signals Skill

Use this skill after references exist in Papyrus and need reusable curation
signals for retrieval, ranking, agent context, or editorial review.

Reference summaries and quality ratings are semantic graph signals. They are
not source ingestion, not curation-status decisions, and not publication Items.

## Title And Subtitle Enrichment

Reference titles and subtitles are durable source metadata, not semantic graph
signals. `Reference.title` is the first-class title field. Subtitle is v1
metadata-only and should be stored as `metadata.subtitle`, plus local
Biblicus sidecar/catalog copies so GraphQL rebuilds can restore it.

Use the title/subtitle resolver when a new or existing Reference lacks usable
display copy:

```bash
poetry run papyrus references title-subtitle resolve \
  --reference <reference-id> \

```

Batch missing values:

```bash
poetry run papyrus references title-subtitle batch \
  --corpus-key <corpus-key> \
  --status all \
  --only-missing true \
  --max-count 25 \

```

Reference intake also runs catalog enrichment by default. Disable it only for
offline or fast deterministic runs:

```bash
poetry run papyrus references prepare-catalog \
  --catalog <catalog.json> \
  --output <prepared.json> \
  --corpus-key <corpus-key> \
  --title-subtitle-enrichment false
```

The resolver must prefer original source metadata. Prompts for web+LLM
fallbacks must preserve the contract: use the original title verbatim if
available, use the original subtitle verbatim if available, and do not
paraphrase original titles or subtitles. If no original subtitle exists, a
generated fallback subtitle is allowed only when provenance says
`subtitle_mode = "generated_fallback"`.

## Quality Contract

A Reference's accepted quality rating is one current `SemanticRelation`:

```text
Reference --quality_rating_is--> SemanticNode
```

Ranking and context-pack code should read the relation first:

- `relationTypeKey = "quality_rating_is"` or fallback `predicate = "quality_rating_is"`.
- `relationState = "current"`.
- `subjectKind = "reference"`.
- `objectKind = "semanticNode"`.
- `score = 1..5`.

The object node gives semantic meaning and validation:

- `quality.rating.1_star`
- `quality.rating.2_star`
- `quality.rating.3_star`
- `quality.rating.4_star`
- `quality.rating.5_star`

There should be exactly one current quality relation per current Reference
lineage. Updating quality supersedes stale `quality_rating_is` relations; do
not hard-delete them. If no current relation exists, treat quality as unknown,
not zero.

Manual quality setting does not require an LLM:

```bash
poetry run papyrus references quality set \
  --reference <reference-id> \
  --rating 4 \
  --note "Strong source for context building." \
  --actor-label "<operator-or-agent>" \

```

Inspect quality:

```bash
poetry run papyrus references quality get --reference <reference-id>

poetry run papyrus references quality list \
  --corpus-key <corpus-key> \
  --min-rating 4
```

## Summary Contract

Each generated Reference summary is a private `Message`:

- `messageKind = "reference_summary"`.
- `messageDomain = "summarization"`.
- `status = "active"`.
- `summary = <generated summary text>`.
- `source = "papyrus-summary-generator"`.

The summary `Message` links to the summarized Reference through a budgeted
relation:

```text
Message --reference_summary_100_tokens--> Reference
Message --reference_summary_200_tokens--> Reference
Message --reference_summary_500_tokens--> Reference
```

The relation type is the lookup contract. If an agent needs a short summary,
query current incoming Reference relations and select
`reference_summary_100_tokens`. If it needs a longer summary, select
`reference_summary_500_tokens`.

`knowledgeQuery` reads all current summary sizes it can find for each
Reference, measures their actual token cost, and renders at most one selected
summary for that source. It prefers the largest summary that fits the source's
allocated budget because a deliberately short summary is usually more useful
than truncating a longer one mid-thought. The selected summary counts against
that source's context budget before semantic vector chunks or extracted-text
passages are added.

Context-pack diversity affects summary selection indirectly:

- `focused` can allocate more budget to a top source and therefore may choose a
  larger summary plus extra passages.
- `balanced` usually chooses a medium summary when it fits and keeps room for
  source spread.
- `broad` favors many sources, so it often chooses shorter summaries and limits
  extra chunks.

List references before selecting a target:

```bash
poetry run papyrus references list \
  --corpus-key <corpus-key> \
  --status accepted \
  --limit 25
```

The list command returns current references newest-first by default, using
import/update timestamps from GraphQL.

Dispatch assignment-backed curation refreshes:

```bash
# one specific reference lineage
poetry run papyrus references curate-recent \
  --corpus-key <corpus-key> \
  --reference <reference-lineage-id> \
  --dry-run --json

# a recent batch
poetry run papyrus references curate-recent \
  --corpus-key <corpus-key> \
  --since-hours 48 \
  --max-count 25 \
  --dry-run --json

# all references in the corpus
poetry run papyrus references curate-recent \
  --corpus-key <corpus-key> \
  --all \
  --max-count 250 \
  --dry-run --json
```

There should be exactly one current summary relation per
`(reference lineage, maxTokens)`. Refreshing a summary creates a new `Message`
and supersedes the old summary relation. Historical `Message` rows remain.

Summary metadata is stored both on the `SemanticRelation.metadata` and as a
`ModelAttachment` on the `Message` because the current deployed `Message`
schema does not carry inline metadata. Expected metadata keys include:

- `maxTokens`
- `actualTokenEstimate`
- `tokenizer`
- `model`
- `promptVersion`
- `sourceContentHash`
- `referenceLineageId`
- `runId`
- `assignmentId`
- `generatedAt`
- `rationale`
- `doctrineContextStatus`
- `doctrineSlugs`
- `doctrineContentHash`
- `doctrineScope`
- `policyUse`

LLM-generated summaries include publication-level doctrine context by default.
The generator reads private doctrine `Item` records for
`editorial-doctrine-mission` and `editorial-doctrine-policy` and stores
`promptVersion = "reference-summary-v2-publication-doctrine"`.

Editorial policies are context only. They describe standards for downstream
published Papyrus content; they are not rules that the source `Reference` must
satisfy. Summary and quality-assessment prompts must preserve this distinction.
Older summaries may have `promptVersion = "reference-summary-v1"` and no
doctrine metadata. Refresh those explicitly with `--refresh` if needed.

Manual summaries supplied through `--summary-text` do not load doctrine and
record `doctrineContextStatus = "not_used_manual_summary"`.

Generate or dry-run a single summary:

```bash
poetry run papyrus references summarize \
  --reference <reference-id> \
  --max-tokens 100 \
  --summary-text "Manual or externally generated summary."
```

Apply the write:

```bash
poetry run papyrus references summarize \
  --reference <reference-id> \
  --max-tokens 100 \
  --summary-text "Manual or externally generated summary." \

```

If `--summary-text` is omitted, the command uses `OPENAI_API_KEY` and the
configured model to generate the summary from resolved source text. Prefer
passing `--source-text-file` when local source text resolution is uncertain.

Batch missing summaries:

```bash
poetry run papyrus references summarize-batch \
  --corpus-key <corpus-key> \
  --budgets 100,200,500 \
  --only-missing true \
  --max-count 25
```

Remove `--dry-run` only after reviewing the dry-run output.

Read summaries already linked to a reference:

```bash
poetry run papyrus references summaries \
  --reference <reference-id> \
  --max-tokens 100
```

## Tactus Use

The Tactus runtime exposes these APIs:

- `reference.list`
- `reference.quality_get`
- `reference.quality_set`
- `reference.summarize`
- `reference.summaries`

Use Tactus for agent-scored quality or generated summaries when the procedure
needs doctrine, rubric, retrieval, or LLM reasoning. Agent quality prompts may
include publication doctrine, but must not use publication policies as the
quality scoring rubric; quality is scored by the explicit quality rubric. Use
the CLI for direct operator curation or smoke tests. Both paths use the same
Python planner and write the same graph contracts.

## After Reference Intake

Use this sequence after a pending reference has been accepted and source text is
available.

1. Decide quality with the user when the source is nuanced. Manual agreement is
   valid and should be recorded directly:

   ```bash
   poetry run papyrus references quality set \
     --reference <reference-id> \
     --rating <1-5> \
     --note "<why this rating was chosen>" \
     --actor-label "<operator-or-agent>" \

   ```

2. If the user wants the agent to classify quality from source text and the
   quality rubric, use the assessor instead:

   ```bash
   poetry run papyrus references quality assess \
     --reference <reference-id> \

   ```

3. Generate budgeted summaries. Use at least a short summary for indexing and
   broad context packs; add 200/500-token summaries when the source is important
   enough to justify richer downstream context:

   ```bash
   poetry run papyrus references summarize-batch \
     --corpus-key <corpus-key> \
     --budgets 100,200,500 \
     --only-missing true \
     --max-count 25 \

   ```

4. Sync the derived vector index after summaries and extracted-text attachments
   exist. The vector store is not the source of truth and does not update merely
   because a `Reference` was accepted:

   ```bash
   PAPYRUS_GRAPHQL_AUTH=iam AWS_PROFILE=<profile> AWS_REGION=<region> PYTHONPATH=src \
     poetry run papyrus knowledge vector-index --action sync \
     --corpus-id <corpus-id> \
     --max-references 25 \
     --dry-run
   ```

   Remove `--dry-run` only after reviewing the prepared vector count. See
   `skills/knowledge-query/SKILL.md` for vector-index audit, sync, and rebuild
   rules.

## Operational Rules

- Run `relations import-types` and the normal semantic concept import path after
  adding or deploying the seed contract.
- Mutations should update the Newsroom aggregate summary snapshot. If summary
  update fails or drift is suspected, run:

  ```bash
  poetry run papyrus sections recount-summary
  ```

- Do not store raw source text in `Message.summary`, `Message` payloads, or
  DynamoDB metadata. Source text stays in Biblicus/local corpus/S3 files.
- Do not use quality ratings as curation status. `Reference.curationStatus`
  still controls accepted/pending/rejected/archived eligibility.
- Ranking code should use `SemanticRelation.score` for quality and should treat
  missing quality as unknown.
