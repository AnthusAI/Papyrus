# Internal Knowledge Base Research

Papyrus keeps accepted references, ontology, and graph context in GraphQL. The
**internal research path** turns that into model-ready context packs through one
shared Python engine: `knowledgeQuery`.

Use this document when you need to search what the publication already knows.
Use [skills/newsroom-research-workflow/SKILL.md](../skills/newsroom-research-workflow/SKILL.md)
when the task is assignment workflow, research packets, or web handoff. Use
[skills/knowledge-query/SKILL.md](../skills/knowledge-query/SKILL.md) for full
query shape, ranking, vector indexing, and output tuning.

## What counts as internal research

- **Semantic search** over accepted references (S3 Vectors index, derived from
  GraphQL + extracted text).
- **Anchored lookup** by `papyrus://` URI or explicit anchor ids (reference,
  category, assignment, semantic node, and other supported kinds).
- **Graph expansion** along knowledge/ontology/classification/evidence relations
  (budgeted; operational/workflow edges stay out by default).
- **Quality-aware ranking** from current `quality_rating_is` relations.

Only **accepted** references are evidence-eligible. Pending prospects and web
search hits are not internal knowledge until reference intake and curation
accept them.

## Prerequisites

Local CLI and AppSync both need authoring credentials:

- `PAPYRUS_GRAPHQL_ENDPOINT` — production or sandbox AppSync URL
- AWS credentials (`AWS_PROFILE`) for the site's authoring role; requests are
  signed with SigV4 (IAM)

Copy from [`.env.example`](../.env.example). See
[skills/category-steering/SKILL.md](../skills/category-steering/SKILL.md) for
the production setup; there is no token to commit.

Semantic search also needs a configured vector index (`PAPYRUS_S3_VECTOR_INDEX_ARN`
or `custom.knowledgeQuery.s3VectorIndexArn` in Amplify outputs). If vectors are
missing or auth fails, you may still get anchor/graph results but
`warnings` will mention semantic failure.

Optional: `OPENAI_API_KEY` for embedding during vector **sync** operations, not
for ordinary queries.

## Fastest path: CLI smoke

From the repo root, with Poetry or `PYTHONPATH=src`:

```bash
# Semantic-only (exploratory)
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --query "production measurement for LLM agents" \
  --profile researcher \
  --format both \
  --max-tokens 1200 \
  --top-k 12 \
  --depth 1

# Anchored close read on one accepted reference
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --anchor papyrus://reference/<lineage-id> \
  --profile researcher \
  --format both \
  --max-tokens 1000 \
  --depth 1

# Force local engine (no AppSync round-trip) when developing query behavior
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --execution local \
  --query "test query" \
  --format structured
```

Poetry equivalent:

```bash
poetry run papyrus-newsroom knowledge-query --query "..." --format both --max-tokens 800
```

Save and inspect markdown context:

```bash
mkdir -p .papyrus-runs/knowledge-query
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --input .papyrus-runs/knowledge-query/input.json \
  > .papyrus-runs/knowledge-query/result.json

jq -r '.context.text // ""' .papyrus-runs/knowledge-query/result.json \
  > .papyrus-runs/knowledge-query/context.md
```

## Assignment-shaped internal research

For live assignment work, combine desk context with knowledge search:

```bash
npm run content -- assignments build-context --assignment <id> --context-profile researcher
PYTHONPATH=src python -m papyrus_newsroom knowledge-query \
  --query "<tight question from the assignment brief>" \
  --profile researcher \
  --format both \
  --max-tokens 1200
```

Inside Tactus procedures, the research harness exposes the same engine as
`knowledge_search(...)` and `knowledge_search_uri(...)` (wrappers around
`knowledge_query{...}` in `src/papyrus_newsroom/tactus_runtime.py`).

## AppSync (deployed engine)

Same JSON input as CLI, via `knowledgeQuery(input: AWSJSON!)`. Example curl
pattern is in [skills/knowledge-query/SKILL.md](../skills/knowledge-query/SKILL.md).

Prefer CLI iteration until context-pack behavior is stable, then deploy Lambda
changes.

## Vector index maintenance

If semantic queries return empty matches but references exist in GraphQL, audit
and sync the derived index (see knowledge-query skill). Typical flow:

```bash
AWS_PROFILE=<profile> AWS_REGION=<region> PYTHONPATH=src \
  python -m papyrus_newsroom knowledge-vector-index --action audit

AWS_PROFILE=<profile> AWS_REGION=<region> PYTHONPATH=src \
  python -m papyrus_newsroom knowledge-vector-index --action sync \
  --corpus-id <corpus-id> --max-references 25 --dry-run
```

## Troubleshooting

| Symptom | Likely cause |
|--------|----------------|
| `Semantic search failed: HTTP Error 401` | Expired or missing AWS credentials, or a principal without `appsync:GraphQL` |
| `No accepted reference evidence` with empty `semanticMatches` | No vectors, no accepted refs for query, or index not synced |
| `cliExecution: remote` but you expected local edits | Default is remote when the endpoint is set and AWS credentials resolve; pass `--execution local` |
| Graph hits but no passages | `extractMode: auto` on semantic-only queries; use anchors or `extractMode: always` |

Check `structured.request.semanticQuerySource`: `explicit`, `anchor_derived`,
or `none`.

## Related skills and code

| Topic | Location |
|-------|----------|
| Full query contract | [skills/knowledge-query/SKILL.md](../skills/knowledge-query/SKILL.md) |
| Assignment + web workflow | [skills/newsroom-research-workflow/SKILL.md](../skills/newsroom-research-workflow/SKILL.md) |
| Bounded agent loops (ReAct-style) | [docs/agent-loop-patterns.md](./agent-loop-patterns.md) |
| Engine implementation | `src/papyrus_knowledge_query/` |
| CLI entry | `src/papyrus_knowledge_query/cli.py`, `src/papyrus_newsroom/cli.py` |
| Tactus helpers | `src/papyrus_newsroom/tactus_runtime.py` |
