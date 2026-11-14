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
  GraphQL + extracted text). The index also holds the summary vector of pending
  References, as context for link suggestions only: the search filter always
  asks for accepted References (or vectors that are not References) and drops a
  pending match if one comes back, whatever `curationStatus` the request names.
- **Anchored lookup** by `papyrus://` URI or explicit anchor ids (reference,
  category, assignment, semantic node, and other supported kinds).
- **Graph expansion** along knowledge/ontology/classification/evidence relations
  (budgeted; operational/workflow edges stay out by default).
- **Quality-aware ranking** from current `quality_rating_is` relations.

- **Editors' explanations of links** (see below): the note an editor wrote on an
  accepted Reference-to-Reference link or concept tag.

Only **accepted** references are evidence-eligible. Pending prospects and web
search hits are not internal knowledge until reference intake and curation
accept them.

## Editors' explanations of links

When an editor accepts a link between two References, or tags a Reference with a
concept, and writes why (`SemanticRelation` `metadata.note`, edge kinds
`reference.link`, `reference.concept` and `concept.link`, an editor's link between two concepts; see
[idea-context-packs.md](./idea-context-packs.md) section 2.2.1), that explanation
is searchable meaning.

- **Index.** One `link_explanation` vector per link whose state is `current`, whose
  `metadata.decision` is `accepted` (or that a person made, provenance `human`),
  that has a non-empty note and whose Reference ends are accepted. Key
  `link_explanation-<relationId>`. Text: both ends' titles, the predicate and the
  explanation. Metadata: `subjectLineageId`, `objectLineageId`, `relationId`,
  `predicate`, `decidedBy`, `decidedAt`, `audience: editor`, `curationStatus:
  accepted` (set on purpose: it passes the accepted-only filter and the
  accepted-or-absent filter alike), `contentHash`. The vector's `contentHash` and
  `curationStatus` are its watermark: the router's daily pass
  (`monitoring_vectors.py`, through `index_reference_passages`) embeds a new or
  edited explanation, skips an unchanged one, and removes the vector of a link
  rejected or with its note cleared. The router's role has no
  `s3vectors:DeleteVectors`, so there the vector is re-marked `curationStatus:
  withdrawn` (the same AccessDenied fallback as for rejected References), which no
  query returns; a role that may delete removes it on its next sync. A failed read
  of the links is a warning in the sync stats and deletes nothing.
- **Result.** `knowledgeQuery` returns a match as `structured.linkExplanations`
  (attribution "Editor's explanation (<editor>)", the explanation, the predicate and
  both ends with their `papyrus://reference/...` URIs) and as a `link_explanation`
  evidence passage in the context text.
- **Audience.** The explanation was written as an internal note. `knowledgeQuery`
  has no public reader path today (AppSync authorises only the site's editors;
  newsroom Tactus procedures, the CLI and the console are internal). To keep it so,
  `scope.audience` is `editor` (the default) or `public`; any value but `editor`
  excludes explanations in the metadata filter (`vectorKind != link_explanation`),
  in the provider's post-filter, and in the engine. A future public reader feature
  must send `audience: public` and an owner decision is needed before any
  explanation reaches a public answer or page. Suggestions and idea-pack
  neighbour queries filter by `vectorKind` and never read these vectors.

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

For live assignment work, combine section context with knowledge search:

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

## Where a query reads a Reference's text

The evidence passages of a query come from the Reference's **current text**, chosen per matched Reference (PPY-caa222). Nothing is scanned: the
curation card arrives with the Reference's other attachments, and a captured body is found by listing that one Reference's `ModelAttachment`s through
`modelAttachmentsByOwnerRoleAndSortKey`. Only accepted References are read, and only the ones the query already returned for this caller.

| Order | Source | When it wins |
|---|---|---|
| 1 | The body named by the card's `current.textSortKey`, when it is a `curation-edit-NNNN-text` | A person (or an agent acting through `correctReferenceCapture`) corrected or supplied the text. The latest correction is the current text; earlier ones and the `extracted_text` attachment it replaced are not read. |
| 2 | An `extracted_text` ReferenceAttachment (Biblicus extraction in corpus storage) | No correction exists. |
| 3 | The card's machine capture (`curation-text`) | Nothing else exists: a monitor-delivered or curated Reference. |

Text from sources 1 and 3 is fetched with `createModelAttachmentDownload` **as the caller** (the knowledge-query function's own role reads only
`corpora/*`, so it could not read `newsroom/payloads/*` itself, and this way it never returns text the caller could not download). The passages
carry `textSource` (`curation_edit`, `curation_text` or `extracted_text`); for the first two they also carry `capture`: `sortKey`, `editedBy`,
`editedAt`, `via`, the capture's own `note` verbatim (so "captured by an AI agent, not independently completeness-checked" stays attached to the
text) and `assessmentOfMachineCapture`. The context summary repeats that line. The MCP tools and the signed-in CLI call this same engine
(`knowledgeQuery`), so they get the same behaviour.

The query reports in `warnings`, never silently falling back to metadata: no text anywhere; the card names a text that has no active attachment for this
Reference version; the owner lookup failed; the text exists but could not be read (a permission or storage error, with its message); the text is empty.

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
| `sourceTextMode: metadata` with warnings about captured text | The Reference has a captured text the caller could not read, or its card points at a body with no active attachment; the warning says which ([above](#where-a-query-reads-a-references-text)) |

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
