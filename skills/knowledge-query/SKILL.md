---
name: knowledge-query
description: Use this skill when generating, testing, debugging, or designing Papyrus knowledgeQuery context packs for agents, articles, reviews, chat, or newsroom research.
---

# Knowledge Query Skill

Use this skill when an agent needs model-ready context from the Papyrus
knowledge base. `knowledgeQuery` is the shared query path for research,
reporting, editing, reviewing, chat grounding, and context-pack experiments.

**Coding agents:** start with [`docs/internal-knowledge-research.md`](../../docs/internal-knowledge-research.md)
for prerequisites, CLI smoke commands, assignment-shaped queries, and
troubleshooting. For multi-step `knowledge_search` inside Tactus research harnesses,
see [`docs/agent-loop-patterns.md`](../../docs/agent-loop-patterns.md).

The same Python engine powers both entrypoints:

- AppSync custom query: `knowledgeQuery(input: AWSJSON!): AWSJSON`
- CLI: `poetry run papyrus knowledge query`

Keep behavior changes in `src/papyrus_knowledge_query/` so Lambda and CLI stay
identical.

## Query Shape

The input is one JSON object:

```json
{
  "anchors": [
    { "kind": "reference", "id": "<version-id>", "lineageId": "<lineage-id>" }
  ],
  "semanticQuery": "production measurement and reliability evaluation for LLM agents",
  "scope": {
    "depth": 1,
    "topK": 12,
    "semanticSeedLimit": 5,
    "relatedRecordLimit": 8
  },
  "profile": "editor",
  "ranking": {
    "profile": "balanced",
    "diversity": "balanced"
  },
  "output": {
    "format": "both",
    "maxTokens": 1200,
    "seeAlsoMaxTokens": 200
  }
}
```

All top-level fields are optional, but useful context usually needs either
`anchors`, `semanticQuery`, or both.

## Anchors

Use `anchors` for exact Papyrus objects. Supported kinds are:

- `reference`
- `item`
- `category`
- `categorySet`
- `semanticNode`
- `semanticRelation`
- `message`
- `assignment`
- `newsroomSection`
- `steeringProposal`

Prefer stable lineage ids when available. The rendered markdown uses stable
Papyrus URIs:

```text
papyrus://<kind>/<lineageId-or-id>
```

CLI and Tactus anchors may use either explicit `{kind,id}` tables or those
stable URIs directly, for example `--anchor papyrus://reference/<lineage-id>` or
`knowledge_query{ uri = "papyrus://reference/<lineage-id>" }`.

When anchors are references, they are target records. Multiple reference
anchors render under `## Target Records`; each record keeps its metadata and
excerpts together.

## Semantic Query Behavior

If `semanticQuery` is provided, semantic search uses that text.

If `semanticQuery` is omitted but anchors are provided, the engine derives a
semantic query from resolved anchor metadata such as title, authors, deck,
summary, description, category key, and node key. This derived query is used to
find supplemental `See Also` records.

If neither anchors nor `semanticQuery` are supplied, semantic search has no
meaningful input and the result will be empty except for warnings/debug data.

Semantic vector hits with text chunk metadata become passage evidence, not
generic related concepts. Non-anchor semantic matches may become `See Also`
records when they are strong matches, graph neighbors, or share corpus/category
context with the anchors.

If vector search returns a summary `Message` instead of the summarized
`Reference`, normalize the hit back to the target Reference through the current
`reference_summary_<N>_tokens` relation. Treat the summary as Reference summary
evidence, not as an orphan `Message` object and not as a chunk excerpt.

Insight messages are first-class knowledge evidence when they follow this
contract:

- `Message.messageKind = "insight"`
- `Message.messageDomain = "knowledge"`
- body text stored as a `ModelAttachment` with role `message_body`
- a current `SemanticRelation` with `relationTypeKey = "insight_about"`

`insight_about` may point at a `reference`, `item`, `category`,
`semanticNode`, `assignment`, or `newsroomSection`. General commentary
messages linked by `comment`, `about`, or `ingestion_rationale` stay outside
default knowledge context packs.

Insight vector indexing embeds only the `message_body` attachment text.
`Message.summary` is a UI/list label and may be carried as vector metadata, but
it must not be used as embedding input or as fallback content. An insight
without an active, non-empty `message_body` attachment is incomplete for vector
indexing and should be reported as missing body.

## Scope Options

`scope.depth`: graph expansion depth, clamped to `0..3`.

`scope.topK`: semantic search limit, clamped to `1..100`.

`scope.semanticSeedLimit`: when there are no anchors, maximum semantic matches
to promote as graph-expansion seeds. Default `5`, maximum `20`.

`scope.semanticSeedExpansionLimit`: when there are no anchors, maximum semantic
seeds to actually expand through graph neighbors. Default `1`. Keep this low
for search-like context packs; graph expansion is one of the most expensive
parts of live queries.

`scope.semanticSeedGraphTopK`: relation cap for each semantic seed graph
expansion. Default `6`. This is intentionally separate from vector `topK`;
do not use a broad vector search limit as the graph expansion limit.

`scope.resolveSemanticSeeds`: defaults to `false`. Set `true` only when seed
metadata is insufficient and the seed itself must be resolved before graph
expansion.

`scope.resolveSemanticSeedExpansionObjects`: defaults to `false`. Set `true`
only when graph neighbor object details are needed; otherwise relation stubs
and vector metadata are enough for search context.

`scope.relatedRecordLimit`: maximum related records to keep for `See Also`.
Default `8`, maximum `30`.

`scope.relationTypes`: explicit relation type allowlist. If present, it
overrides the default knowledge-only relation policy.

`scope.includeRelationDomains` / `scope.excludeRelationDomains`: optional
domain controls for graph relation filtering.

`scope.includeOperationalContext`: set `true` only for admin, debugging, or
workflow contexts. Default knowledge packs exclude commentary, ingestion,
publication, and workflow relations.

`scope.tokenizerModel`: optional tokenizer model override. Prefer leaving this
unset unless a downstream model requires exact model-specific counting.

## Profiles

Valid profiles are:

- `researcher`
- `reporter`
- `editor`
- `reviewer`
- `chat`

Profiles tune default graph depth, semantic `topK`, and context emphasis. They
do not override the default knowledge-only relation policy.

## Ranking And Diversity

`ranking.profile` controls score weights. Valid values are:

- `balanced`: default; relevance dominates, quality can meaningfully break
  ties, and graph context contributes a small signal.
- `relevance_first`: favors semantic/lexical relevance more strongly.
- `quality_forward`: gives accepted quality ratings more influence among
  otherwise relevant records.

Reference quality comes from one current outgoing relation:

```text
Reference --quality_rating_is--> SemanticNode
```

The ranking code reads `relationTypeKey = "quality_rating_is"` or fallback
`predicate = "quality_rating_is"`, requires `relationState = "current"` when
present, and uses `SemanticRelation.score` as the `1..5` quality rating.
Missing quality is unknown, not zero, and uses a neutral ranking fallback.

`ranking.diversity` controls source spread and token allocation. It is separate
from `ranking.profile`.

- `focused`: fewer sources, deeper treatment of the top-ranked records. Use for
  source-specific chat or close reading.
- `balanced`: default; gives explicit anchors and top records useful depth
  while preserving moderate source spread.
- `broad`: smaller slices from more unique sources. Use for exploratory
  "what does the corpus know?" queries.

Diversity affects semantic match selection, `See Also` selection, source
budgets, and passage caps. It must not change curation status, relation policy,
or scoring semantics. Explicit anchors remain visible in every diversity mode.

When summaries exist, `knowledgeQuery` prefers one selected Reference summary
for a source before semantic or extracted-text chunks. The engine chooses the
largest current summary that fits that source's token budget, using relation
types such as `reference_summary_100_tokens`,
`reference_summary_200_tokens`, and `reference_summary_500_tokens`.

## Output Options

`output.format`:

- `structured`: return structured data only.
- `markdown`: return rendered context only.
- `both`: return both.

`output.maxTokens`: total markdown token budget. Budgets use `tiktoken` with
`o200k_base` by default and fall back to the regex counter only if `tiktoken`
is unavailable.

`output.seeAlsoMaxTokens`: optional budget override for `## See Also`. Default
is `min(12% of maxTokens, 300)`, or `300` when no total budget is supplied.

`output.maxPassages`: maximum extracted-text passages to select. Default `5`,
maximum `20`.

`output.maxPassageTokens`: per-passage cap. Default `160`, clamped to
`40..500`.

`output.includeExtracts`: defaults to `true`. Set `false` only when metadata
and graph structure are enough.

`output.extractMode`: `auto`, `always`, or `never`. Default `auto`.
Semantic-only vector-backed queries skip S3 extracted-text fallback in `auto`
mode because vector chunks are already evidence passages. Anchored queries
still use extracted text in `auto` mode. Use `always` for source-specific close
reading or full-source attempts.

`output.includeProvenanceAppendix`: defaults to `false`. Set `true` to render
operational/curation facts at the end instead of mixing them into the knowledge
body.

`output.tokenizerModel`: optional tokenizer model override. This takes
precedence over `scope.tokenizerModel`.

## Relation Policy

Default policy is `knowledge_only`.

Included relation domains:

- `knowledge`
- `ontology`
- `classification`
- `evidence`

Excluded by default:

- commentary and curation notes
- ingestion rationale
- workflow and assignment routing
- publication planning edges
- generic record-keeping edges

Do not include operational relations in ordinary research, writing, review, or
chat context packs. Opt in only when the user is debugging Papyrus itself.

## Markdown Structure

Single primary reference:

```markdown
# <source title>
Papyrus URI: papyrus://reference/<lineage-id>

## Context Summary
...

## Full Source Text
...
```

If the full extracted text does not fit, the engine renders source excerpts
instead.

Multiple target references:

```markdown
## Knowledge Summary

## Target Records

### <target title>
Papyrus URI: papyrus://reference/<lineage-id>
...

## See Also

### <related title>
Object: papyrus://reference/<lineage-id>
Why related: ...
...
```

`See Also` is supplemental and should stay concise. Do not confuse `See Also`
matches with target records.

## Output Fields

The response envelope includes:

- `structured`: resolved anchors, semantic matches, semantic passages, evidence
  passages, related records, relations, expanded objects, and request metadata.
- `context`: rendered markdown text and token metadata when requested.
- `warnings`: non-fatal issues such as missing extracted text or unavailable
  providers.
- `provenance`: graph and semantic provider names.
- `debug`: counts, timings, tokenizer metadata, semantic query source,
  ranking profile, diversity profile, unique source count, source budget count,
  vector diversification mode, stage timing breakdowns, and provider-level
  graph call counts when available.

Check `structured.request.semanticQuerySource`:

- `explicit`: caller supplied `semanticQuery`.
- `anchor_derived`: engine derived it from anchors.
- `none`: no semantic query was available.

## CLI Usage

Requires `PAPYRUS_GRAPHQL_ENDPOINT` and AWS credentials (`AWS_PROFILE`; SigV4)
for default remote execution. Use `--execution local` when changing engine code under
`src/papyrus_knowledge_query/`.

Semantic-only smoke:

```bash
poetry run papyrus knowledge query \
  --query "agent memory systems" \
  --format both \
  --max-tokens 600
```

Anchored smoke:

```bash
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --anchor papyrus://reference/<lineage-id> \
  --profile researcher \
  --format both \
  --max-tokens 800
```

Input-file smoke:

```bash
poetry run papyrus knowledge query \
  --input .papyrus-runs/knowledge-query/input.json |
  jq
```

Write markdown for review:

```bash
poetry run papyrus knowledge query \
  --input .papyrus-runs/knowledge-query/input.json \
  > .papyrus-runs/knowledge-query/result.json

jq -r '.context.text // ""' \
  .papyrus-runs/knowledge-query/result.json \
  > .papyrus-runs/knowledge-query/context.md
```

Desk-anchored smoke (operational section / news desk):

```bash
poetry run papyrus knowledge query \
  --query "AI in games" \
  --anchor newsroomSection:technology \
  --max-tokens 600 \
  --format structured
```

When debugging local code changes before Lambda deploy, force local engine execution:

```bash
poetry run papyrus knowledge query \
  --query "AI in games" \
  --anchor newsroomSection:technology \
  --execution local \
  --format structured
```

The CLI uses local environment configuration:

- `PAPYRUS_GRAPHQL_ENDPOINT`
- AWS credentials from the standard chain (`AWS_PROFILE`)
- optional `PAPYRUS_S3_VECTOR_INDEX_ARN`
- optional `OPENAI_API_KEY`

## AppSync Usage

The AppSync query receives the same JSON object, stringified as `AWSJSON`:

```bash
INPUT_JSON="$(jq -c . .papyrus-runs/knowledge-query/input.json)"
jq -n --arg input "$INPUT_JSON" '{
  query: "query KnowledgeQuery($input: AWSJSON!) { knowledgeQuery(input: $input) }",
  variables: { input: $input }
}' |
eval "$(aws configure export-credentials --format env)"
curl -sS "$PAPYRUS_GRAPHQL_ENDPOINT" \
  --aws-sigv4 "aws:amz:us-east-1:appsync" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" \
  -H "x-amz-security-token: $AWS_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @- |
jq '.data.knowledgeQuery | fromjson? // .'
```

Use the CLI for fast context-pack iteration. Deploy Lambda only when the shared
logic is ready to validate through AppSync.

## Vector Indexing

S3 Vectors is a derived semantic index. GraphQL `Reference` rows and extracted
text attachments remain the source of truth; the vector index must be rebuilt or
synced after a vector bucket/index replacement.

Audit coverage before writing vectors:

```bash
AWS_PROFILE=<profile> AWS_REGION=<region> PYTHONPATH=src \
  poetry run papyrus knowledge vector-index --action audit
```

Sync missing vectors with a dry run first:

```bash
AWS_PROFILE=<profile> AWS_REGION=<region> PYTHONPATH=src \
  poetry run papyrus knowledge vector-index --action sync \
  --corpus-id <corpus-id> \
  --max-references 25 \
  --dry-run
```

Remove `--dry-run` only after reviewing the configured vector index, accepted
reference count, existing vector count, prepared vector count, and write count.
`sync` skips deterministic keys that already exist unless `--force` is passed.
By default it writes both `reference_summary` source-level vectors and
`reference_passage` extracted-text chunk vectors. Use `--no-source-vectors` or
`--no-passage-vectors` only for a targeted repair.

Use `--action rebuild` only for a derived-index rebuild where deleting existing
vectors in the configured S3 Vectors index is intentional.

## Verification

Run local checks before committing query behavior changes:

```bash
python -m compileall src/papyrus_knowledge_query src/papyrus_newsroom
PYTHONPATH=src python -m unittest procedures.newsroom.tests.test_knowledge_query procedures.newsroom.tests.test_newsroom_tools
npm run typecheck
```

For context-pack design changes, regenerate example outputs under
`.papyrus-runs/knowledge-query/` and inspect the markdown as model context.
