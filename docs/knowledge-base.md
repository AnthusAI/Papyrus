# Knowledge base

Each publication keeps what it knows as data in its own backend: accepted references, a topic tree, and a graph of entities and relations. Agents and editors read it; Papyrus does not train on it.

Status words used here: Live, Beta, Not built yet.

## Concepts wiki (Live)

`/newsroom/concepts` is a wiki of concepts for editors. It sits in the newsroom, so it is for signed-in editors and not for the public. Each page is a concept: an entity in the knowledge graph that the newsroom has reported on, researched or cited. A page shows what it is, what it connects to and the references behind it. The front page is an ordinary content item with the slug `wiki-index`, and it lists recently edited concepts and all concepts. Code: `lib/wiki.ts`.

## Topics and taxonomy (Live)

Accepted topics are a versioned tree: a `CategorySet` with parent and child `Category` rows. Editors accept, reject, rename, move, split, merge or ignore proposed changes. How that steering works is in [steering-and-relevance.md](steering-and-relevance.md). The model is described in [how-papyrus-works.md](how-papyrus-works.md).

## Graph and entities (Live)

- `SemanticNode` rows are typed entities and concepts.
- `SemanticRelation` rows are explicit, versioned relations between them, with relation types seeded as `SemanticRelationType` records.
- Graph artifacts are imported and published with the `papyrus analysis` commands (`src/papyrus_content/analysis_graph.py`).
- Ontology enrichment (`src/papyrus_content/ontology_enrichment.py`) is run with the `papyrus ontology` commands: `preflight`, `rank`, `status`, `explain`, `profile`, `associate`, `dedupe`, `recompute-authority` and `doctor`.

## Context packs for agents (Live)

`knowledgeQuery` searches accepted references and the graph and returns a context pack for a model: semantic search, lookup by anchor, and budgeted graph expansion. Only accepted references count as evidence. Research and reporting procedures call it as `knowledge_search`. See [internal-knowledge-research.md](internal-knowledge-research.md).

## Trending concepts report (Beta)

A report ranks concepts by popularity, by trend over a time window, or by PageRank, from the mentions in accepted references. It is run from the command line. It is Beta: it is a private analytics report for editors and is not shown to readers.

```bash
# Trending concepts over the last 30 days. Prints the report and writes nothing.
papyrus signals concept-report --corpus-key <corpus key> --report-type trending --json

# Same report, saved to the backend as a private Message of kind concept_report.
papyrus signals concept-report --corpus-key <corpus key> --report-type trending --apply
```

Options: `--report-type all|popularity|trending|pagerank` (default `all`), `--trend-window-days` (default 30), `--limit` (default 25), `--node-kinds` (default `entity`), `--max-nodes-per-reference`, `--run-id` and `--input` (a fixture file). The report creates no article and no edition item. The command is in `src/papyrus_newsroom/cli.py` and is reached through `papyrus signals`.

## Biblicus (Live)

[Biblicus](https://github.com/AnthusAI/Biblicus) is the corpus and analysis engine behind topic modeling and graph extraction. Papyrus calls it only through one process boundary, `src/papyrus_content/biblicus_runner.py`, which runs the `biblicus` command and parses its JSON. Corpora live under the directory named by `BIBLICUS_WORKDIR`. To start a publication from a pile of files, see [new-publication-from-corpus.md](new-publication-from-corpus.md). Version notes: [biblicus-1-14-upgrade.md](biblicus-1-14-upgrade.md).

## Not built yet

These are planned under initiative PPY-428252:

- A public, read-only wiki (epic PPY-495ec8).
- Public topic pages and public trends (epics PPY-a45fd1 and PPY-964472).
- Entity trends (epic PPY-0331f5). The report above ranks concepts for editors; it is not an entity trend feature for readers.
