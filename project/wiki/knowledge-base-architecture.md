# The Papyrus Knowledge Base

*Orientation document. Start here if you are new to how this publication
remembers things.*

## What this is, in one paragraph

Papyrus is an AI-run newsroom. Its agents research, draft, and edit — and like
any newsroom, the quality of what it publishes depends almost entirely on what
it knows. The knowledge base is the publication's memory: a curated store of
accepted source material, the concepts that connect it, and a retrieval engine
that turns a question into a model-ready packet of evidence with citations. It
is deliberately **not** a search index over everything the agents have ever
seen. It is the set of sources an editor has accepted, plus the machinery to
find the right ones.

## Why it is built this way

Three commitments shape every part of this system. If you understand these, the
rest of the architecture follows.

**Curation is the point, not overhead.** Nothing becomes knowledge until a human
accepts it. Web search results, agent findings, and inbound submissions all
arrive as *prospects*; they become evidence only after review. This is the
opposite of the industry default of indexing everything and sorting it out at
query time. It costs us recall and it is worth it: it means a citation in a
published article traces to a source someone chose. It is also our cost
governor — because curation throttles what enters the corpus, our
per-document processing costs stay bounded.

**Everything scales to zero.** This is a small-budget operation running many
publications, most idle at any given moment. Every component is pay-per-use with
no idle floor: DynamoDB on-demand, Lambda, S3, S3 Vectors, AppSync. Services
with a capacity floor are disqualified regardless of technical fit — the
relevant question is never "what does this cost" but "what does this cost times
N mostly-idle instances."

**One installation is one publication.** Papyrus is not multi-tenant and will
not become so. A new publication is a new instance with its own stack, tables,
and vector index. Nothing in the codebase should be tenant-aware.

A fourth commitment is more of a working rule: **the query engine makes no LLM
calls.** Retrieval is embeddings plus reads. The only external call at query
time is the embedding request. This keeps queries fast, cheap, and predictable,
and it means agents pay for reasoning only where reasoning happens — in the
agent, not in the plumbing.

## The two layers

The system divides cleanly in half, and most confusion comes from conflating
them.

**The representation layer** answers *what do we know, and how is it stored?* It
covers references, their extracted text and summaries, the ontology graph of
concepts and relations, and the versioned records that hold it all. It is the
system of record.

**The retrieval layer** answers *how do we find the right thing?* It covers the
vector index, the query engine, ranking, and the packaging of results into
token-budgeted context blocks. It is entirely **derived** — every vector can be
rebuilt from the representation layer, and none of it is authoritative.

That derived/authoritative split matters operationally: losing the vector index
is an inconvenience (rebuild it), while losing the GraphQL records is a
catastrophe.

---

# The representation layer

## Storage tiers

Everything runs on AWS Amplify Gen 2. There is no relational database.

| Tier | Holds | Notes |
|---|---|---|
| DynamoDB via AppSync GraphQL | Structured entity records | System of record; ~40 models, each with its own table and GSIs |
| S3 (`papyrusMedia`) | Large bodies, extracted text, media, corpora | Prefixes `media/*`, `corpora/*`, `newsroom/*` |
| S3 Vectors (`papyrus-knowledge`) | Embeddings | 1536-dim, cosine; derived, rebuildable |
| Lambda | Custom operations | Including the knowledge-query engine |

Python tooling in `src/` authors into the GraphQL backend; it never writes
DynamoDB directly.

## Core knowledge models

- **`KnowledgeCorpus`** — a named body of source material. Corpora are the
  primary scoping dimension for queries.
- **`Reference`** — one source document. Carries `curationStatus`, `sourceUri`,
  authorship, and dates. This is the central object of the knowledge base.
- **`ReferenceAttachment`** / **`ModelAttachment`** — S3-backed payloads hanging
  off records: extracted text, metadata, summaries. DynamoDB items have a size
  limit, so anything large is offloaded to S3 and referenced by storage path.
- **`SemanticNode`** — a concept, entity, or label. Has `nodeKey`, `aliases`,
  `authorityScore`, and mention counts.
- **`SemanticRelation`** — a typed edge. The predicate vocabulary is grouped
  into evidence relations (`uses_evidence`, `supports`, `contradicts`,
  `derived_from`), topical relations (`classified_as`, `mentions`,
  `broader_than`, `narrower_than`), and operational/workflow relations
  (`produces`, `requests_work_on`, `planned_for_edition`) which are excluded
  from knowledge queries by default.
- **`KnowledgeImportRun`** / **`KnowledgeRawPayload`** / **`KnowledgeArtifact`**
  — ingestion bookkeeping.

## Two structural conventions worth knowing

**Versioned lineage.** References, semantic nodes, relations, and categories are
not mutated in place. An update writes a new version row and marks the prior one
`superseded`; each record carries `lineageId`, `versionNumber`, and
`versionState`. **Always address knowledge by `lineageId`, not `id`** — `id`
points at one version and will drift out from under you.

**`papyrus://` URIs.** Objects are addressable by stable URI (for example
`papyrus://reference/<lineage-id>`), which is how agents anchor a query to a
specific known thing rather than searching for it.

## How material enters the corpus

The path from "an agent found a URL" to "citable evidence" is deliberately long,
with a human gate in the middle.

1. **Discovery.** A research procedure runs a web search (Tavily) and returns a
   *research packet*. Every hit lands as a `sourceSnapshot` and a
   `proposedReference` — never as evidence.
2. **Intake.** Proposals are deduplicated by normalized URL and registered as
   **pending** `Reference` rows, each with a curation assignment and a preserved
   ingestion rationale.
3. **Curation — the gate.** A human accepts, rejects, reopens, or archives each
   prospect. Only `accepted` references become evidence-eligible. Rejected
   references are retained as scope memory, not deleted; they inform what this
   publication has decided *not* to cover.
4. **Accession.** Accepted references get their source materialized and text
   extracted (via Biblicus for URL text, GROBID for structured articles). This
   also builds the citation graph — `cites` relations, author nodes, and
   resolved DOI/arXiv/PMID identifiers.
5. **Signals.** Accepted references get LLM summaries and quality ratings, the
   latter stored as `quality_rating_is` relations that ranking reads directly.
6. **Indexing.** A separate, explicit sync builds the vector index from accepted
   references. Nothing is indexed automatically on acceptance.

The important invariant: **steps 1–2 create no knowledge.** An agent cannot
promote its own findings into evidence.

---

# The retrieval layer

## The vector index

One S3 Vectors index (`papyrus-knowledge`), 1536 dimensions, cosine distance,
embedded with OpenAI `text-embedding-3-small`. Filterable metadata includes
`corpusId`, `categorySetId`, `curationStatus`, and `vectorKind`.

Five kinds of vector coexist in the index:

| Vector kind | What it represents |
|---|---|
| `reference_summary` | A whole source: title, subtitle, LLM summary, authors, opening text |
| `reference_passage` | A ~180-word chunk of extracted text |
| `insight_source` / `insight_passage` | Analyst insight messages |
| `ontology_concept_profile` | A semantic node's profile |

Passages are chunked at ~180 words with a 120-character floor and a cap of 8
chunks per reference. That cap is a known limitation — see the roadmap below.

The index is maintained by an explicit CLI operation with `audit`, `sync`, and
`rebuild` modes. It is derived state: when in doubt, rebuild it.

## The query engine

One engine, `run_knowledge_query`, serves every consumer. A query may combine
three retrieval modes:

- **Lexical search** — BM25 over a gzipped inverted-index artifact in S3, built
  during vector sync and loaded stdlib-only in the Lambda. Its tokeniser keeps
  identifiers atomic: DOIs (slash intact), ISBNs, arXiv ids, PMIDs, CVEs,
  hashes, domains, IPs, ATT&CK technique ids, with defanged IOCs normalised.
- **Semantic search** — vector similarity over the index.
- **Anchored lookup** — direct resolution of `papyrus://` URIs or explicit ids,
  for when the caller already knows what it wants.
- **Graph expansion** — traversal from anchors and semantic seeds along
  knowledge and ontology relations, budgeted by depth.

The pipeline runs as a fixed sequence of instrumented stages: normalize the
request, resolve and expand anchors, derive a semantic query if none was given,
search, normalize matches, expand semantic seeds, dedupe and assign URIs, rank
with quality signals and allocate token budgets, collect summaries and evidence
passages, rank again, and finally build and render context blocks.

## Ranking

Each candidate is scored as a weighted blend of two signals:

| Signal | Weight | Source |
|---|---|---|
| Relevance | 0.70 / 0.95 ≈ 0.737 | vector distance, or lexical overlap as fallback |
| Quality | 0.25 / 0.95 ≈ 0.263 | current `quality_rating_is` relations |

Unrated sources score a neutral 0.5 on quality. The weights are written as
fractions in `ranking.py` on purpose: they are the former balanced profile
renormalized after a third signal was removed, and recording the derivation is
cheaper than rediscovering it.

This used to be more elaborate. Three ranking profiles, three diversity
profiles, and a `graphContext` signal all existed — roughly 27 constants — and
**nothing in the codebase ever set any of them**; every query that has ever run
used `balanced`/`balanced`. They were deleted once a committed retrieval
baseline existed to prove the removal was behaviour-neutral (identical MRR,
Hit@5, and per-query orderings). `graphContext` carried a 0.05 weight, meaning it
could move a final score by at most 0.05 — noise rather than signal — and
[AD-1](#) supersedes it: graph traversal will contribute a ranked list to be
fused, not a scalar nudge.

There is deliberately **no recency signal today** — a gap the roadmap addresses.

## Consumer profiles

Callers pick a profile, which sets retrieval depth and breadth defaults:

| Profile | Depth | Top-K | Insight bias |
|---|---|---|---|
| `researcher` | 2 | 18 | 1.25 |
| `editor` | 2 | 20 | 1.15 |
| `reviewer` | 2 | 20 | 1.35 |
| `reporter` | 1 | 12 | 1.0 |
| `reporting` | 1 | 10 | 1.0 |
| `chat` | 1 | 10 | 1.0 |

Output is a **token-budgeted context pack** — structured JSON, rendered
markdown, or both — with per-source token allocations so a large result set
degrades gracefully instead of blowing the caller's context window.

## The three ways in

1. **AppSync `knowledgeQuery`** — the deployed path, a Python 3.12 ARM64 Lambda
   at 512 MB. It bundles by copying `src/papyrus_knowledge_query` verbatim with
   an intentionally empty `requirements.txt`, so **anything the Lambda imports
   must be standard library only**. This constraint shapes every retrieval
   design decision.
2. **CLI** — `python -m papyrus_newsroom knowledge-query`, including
   `--execution local` to bypass AppSync while developing query behavior.
3. **Tactus agent harness** — `knowledge_search` inside newsroom procedures,
   with per-procedure scope defaults. Research procedures are required to orient
   on internal knowledge before reaching for web search.

---

# Where this is going

Retrieval is now hybrid: a lexical arm and a vector arm, fused by reciprocal
rank fusion, with a golden-query harness to measure changes. Adding the lexical
arm took identifier queries from 0/5 to 5/5 and global Hit@5 from 76% to 96%,
with no other category disturbed — the first empirical confirmation on this
corpus that a single retriever is structurally blind to exact tokens. The current initiative addresses both, drawing on Cerebras's
published knowledge-base architecture and a note on LLM-driven graph
construction. Full design: `docs/knowledge-retrieval-roadmap.md`.

{% for init in query(type="initiative") %}
## {{ init.title }}

`{{ init.id }}` · {{ init.status }} · P{{ init.priority }}

Overall: {{ count(status="closed") }} of {{ count() }} issues closed.

### Work items, by priority

{% for e in query(type="epic", sort="priority") %}{% if e.parent == init.id %}
- **P{{ e.priority }}** · {{ e.title }} — *{{ e.status }}* · `{{ e.id }}`
{%- endif %}{% endfor %}
{% for c in query(type="chore", sort="priority") %}{% if c.parent == init.id %}
- **P{{ c.priority }}** · {{ c.title }} — *{{ c.status }}* · `{{ c.id }}` *(operational)*
{%- endif %}{% endfor %}
{% endfor %}

### Sequencing

The sequence follows three rules: **unblock the bottleneck before adding load to
it, subtract before adding, and do not build machinery whose value scales with
corpus size while the corpus is small.**

The bottleneck is not retrieval — it is curation throughput. Every accepted
reference passes through one human, and the corpus is small because of that
gate. The gate stays: it is what makes citations trustworthy and what keeps
per-document processing costs bounded. But it means assisted triage (automating
*around* the decision without automating the decision) is the highest-leverage
single item here, and it is easy to overlook because it isn't a retrieval
problem.

Two P0 items come first, for different reasons. **Raw source archival** is
link-rot insurance: today raw bytes are kept only for PDFs, so accepted HTML
references have no archival copy, and threat-intel sources get revised, pulled,
and paywalled. Everything else about the corpus is re-derivable from what we
store — chunking, embeddings, distillation, entity extraction — so the original
bytes are the one irreplaceable asset, and capturing them is what makes it safe
to grow the corpus. **The evaluation harness** gates everything that changes
ranking behavior: without a golden-query baseline we cannot distinguish an
improvement from a regression, and rank fusion can genuinely make retrieval
worse.

Then subtraction before addition — deleting dead ranking configuration first
means the later epics touch simpler code. The P1 items after that are cheap,
high-confidence, and need no index rebuild. The representation work (entity
extraction, then resolution, then contextual chunks) shares a single corpus
re-embed, coordinated by the operational chore. The reranker is last because it
is the only change that adds a recurring per-query LLM cost.

The representation work — entity extraction, then resolution — deliberately
follows corpus growth rather than preceding it. Entity resolution's value is
proportional to how badly entity names fragment across sources, and at a few
hundred references few actors have yet appeared under multiple names. Built now,
it would be built against a corpus too small to reveal the failure modes that
matter.

One item runs against the grain of all the others: the **exploratory research
budget**. Nearly everything here narrows focus — scoping, steering, ranking by
similarity. That is correct for answering questions the operators already have,
and it is exactly why the system would never surprise them. Deliberately
spending some research effort on adjacent, unsteered territory is the
counterweight, and it has to be budgeted on purpose because it will not emerge
on its own. It follows assisted triage, because adding review volume to a
saturated bottleneck makes things worse rather than better.

Three items are deferred at P4: named scope bundles (unnecessary at current
corpus size, and in tension with exploratory research), MCP primitives (useful,
not load-bearing), and the reranker (the only recurring per-query LLM cost).

Run `kbs ready` for the live unblocked queue, or `kbs show <id>` for any item's
full brief — each carries verified current-state notes, design decisions, a
failure-mode analysis, and acceptance criteria.

## Settled architectural decisions

These are the current decisions and the reasoning behind them. They are recorded
so nobody has to re-derive them from scratch — **not** to freeze them. Model
capability moves quickly and this plan is expected to be re-examined as it does;
challenge any of these if you have information we did not:

- **Graph traversal is a retriever, not a separate answering mode.** When graph
  retrieval matures it contributes a ranked list fused with the semantic and
  lexical lists. The engine already blends graph signal into one ranked list via
  hand-tuned constants; rank fusion replaces those with a principled score,
  removing heuristics rather than adding a second pipeline.
- **Entity metadata augments retrieval; it never gates it.** Extraction recall
  is unmeasured, and incomplete metadata used as an exclusion filter hides
  material confidently. The dangerous failure of entity extraction is omission,
  not hallucination.
- **Entity merges need a curation gate.** Merging two distinct threat actors is
  an *editorial* error, not a retrieval-quality one: it would make the
  publication issue false attribution claims laundered through its own citation
  machinery.
- **Measure before changing; land serially.** No retrieval-changing work merges
  before a golden-query baseline exists, and epics touching the same ranking
  code land one at a time.

---

# Practical orientation

## Where the code lives

| Concern | Location |
|---|---|
| Query engine, ranking, vector index | `src/papyrus_knowledge_query/` |
| Records, attachments, GraphQL authoring | `src/papyrus_content/` |
| Reference text extraction, citation graph | `src/papyrus_content/reference_url_text.py` |
| Curation actions, newsroom CLI | `src/papyrus_newsroom/` |
| Agent procedures | `procedures/newsroom/*.tac` |
| Backend definition, vector stack | `amplify/backend.ts`, `amplify/data/schema.ts` |
| Query Lambda | `amplify/functions/knowledge-query/` |
| Tests | `procedures/newsroom/tests/` |

## Common operations

Query the knowledge base locally:

```bash
PYTHONPATH=src python -m papyrus_newsroom knowledge-query --query "your question" --profile researcher --format both --max-tokens 1200
```

Read one known source closely:

```bash
PYTHONPATH=src python -m papyrus_newsroom knowledge-query --anchor papyrus://reference/<lineage-id> --profile researcher --format both
```

Check whether the vector index is current:

```bash
PYTHONPATH=src python -m papyrus_newsroom knowledge vector-index --action audit
```

Both AppSync and local CLI use need `PAPYRUS_GRAPHQL_ENDPOINT` and a
short-lived `PAPYRUS_GRAPHQL_JWT`; vector **sync** additionally needs
`OPENAI_API_KEY` for embedding. Ordinary queries do not embed-and-write, but
semantic search does embed the query itself.

## Related documents

- `docs/internal-knowledge-research.md` — how to actually use the retrieval path
- `docs/knowledge-retrieval-roadmap.md` — the improvement design doc
- `docs/automated-publication-research-workflow.md` — the newsroom data contract
- `skills/newsroom-research-workflow/SKILL.md` — the operator playbook
