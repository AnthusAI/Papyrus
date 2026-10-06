# Agent Loop Patterns in Papyrus

This note summarizes what Papyrus implements today for **agentic looping**,
how that relates to the common **ReAct** pattern, and how it differs from
**Ralph loops** (an external shell-loop pattern not named in this repository).

Internal knowledge-base searches for these topics returned no accepted
reference hits in the current environment (semantic search returned 401 against
the vector provider with the available credentials). The implementation detail below
comes from procedures, runtime code, and skills in this repo.

## ReAct-style looping (what Papyrus has)

**ReAct** (Reason + Act) usually means: the model alternates reasoning with
tool calls until it has enough evidence to answer. Papyrus does not use the
word “ReAct” in code, but the exploratory researcher implements a **bounded**
variant:

| Procedure | Tool calls | Internal knowledge | Web |
|-----------|------------|-------------------|-----|
| `procedures/newsroom/researcher.tac` | **1** `execute_tactus` (harness `research`) | Via harness `knowledge_search` inside the final snippet | Optional, inside same harness |
| `procedures/newsroom/research_explorer.tac` | **Up to 6** `execute_tactus` total | Up to **3** `knowledge_query` / `knowledge_search` | Up to **2** web searches; **2** `papyrus://` lookups |

`research_explorer.tac` is the knowledge-aware, multi-step path. Its system
prompt requires:

1. Assignment context and budgeted agent context pack.
2. One broad `knowledge_query` (compact researcher profile, higher `top_k`).
3. Optional anchored follow-ups or `papyrus.resolve_uri`.
4. Web search when mode is `source_discovery` or `full_research` (mandatory
   unless `blockedReason` is recorded).
5. A final `execute_tactus` with `harness="research"` calling
   `finish_research(...)` or `finish_research_from_search(...)`.

The procedure also retries up to **3** times when the agent returns malformed
structured output, then falls back to a deterministic Tactus snippet (still
using `knowledge_search` + optional `web_search`).

[skills/newsroom-research-workflow/SKILL.md](../skills/newsroom-research-workflow/SKILL.md)
calls this a “bounded ReAct-style loop” for exploratory assignments.

### Runtime helpers (inside `execute_tactus`)

Preloaded in the research harness (`src/papyrus_newsroom/tactus_runtime.py`):

- `knowledge_search(query, options)` → `knowledge_query{...}`
- `knowledge_search_uri(uri, options)` → anchored query
- `resolve_papyrus_uri(uri)` / `papyrus.resolve_uri`
- `evidence_item_ids_from_knowledge(knowledge)` — accepted references only
- `web_search(query)` — Tavily by default via `papyrus.reference.web_search` (`WEB_SEARCH_PROVIDER=tavily`); set `provider="openai"` or `WEB_SEARCH_PROVIDER=openai` for OpenAI web search
- `finish_research{...}` / `finish_research_from_search{...}` — standard packet shape

Constrained one-shot researcher (`researcher.tac`) tells the agent to call
`execute_tactus` **exactly once** with `harness="research"` — no multi-step
tool loop at the agent layer.

### Reporter

`procedures/newsroom/reporter.tac` follows the same **single** `execute_tactus`
pattern as the constrained researcher (compose context, optional web inside
one snippet).

## Ralph loops (not implemented in Papyrus)

**Ralph loop** is an external pattern: a **host process** (often a shell loop)
repeatedly invokes the same agent prompt with **fresh context** each iteration,
while **state lives outside the model** (git commits, progress files, task lists,
passing tests). The model does not carry a long chat history forward.

There are **no** matches for “Ralph” in this repository. Papyrus instead:

- Persists research output in GraphQL (`Message` research packets,
  `AssignmentEvent`, relations).
- Uses **procedure-level** retries and deterministic fallbacks in
  `research_explorer.tac`, not an outer infinite Ralph shell.
- Resets agent context per `execute_tactus` call, but caps total calls (6)
  inside one procedure run rather than looping until an external completion file
  says stop.

If you want Ralph-style overnight runs, that would be **orchestration outside**
Papyrus (CI, worker script, or Tactus host) calling `tactus run procedures/...`
or `poetry run papyrus-newsroom execute-tactus` in a loop with explicit exit
conditions (tests green, assignment complete, max iterations).

## Choosing a pattern

| Goal | Use |
|------|-----|
| Quick internal briefing from accepted KB only | `knowledge-query` CLI or `research_mode=internal_brief` |
| One-shot research packet with optional web | `researcher.tac` or `assignments research-intake-now` |
| Orient in KB, follow URIs, then discover external sources | `research_explorer.tac` (bounded ReAct-style) |
| Iterate query-pack ranking/rendering logic | `knowledge-query` with `--execution local`; see knowledge-query skill |
| Long-running “same prompt until done” automation | External Ralph-style host loop (not in repo) |

## Further reading

- [docs/internal-knowledge-research.md](./internal-knowledge-research.md)
- [skills/knowledge-query/SKILL.md](../skills/knowledge-query/SKILL.md)
- [skills/newsroom-research-workflow/SKILL.md](../skills/newsroom-research-workflow/SKILL.md)
- [docs/automated-publication-research-workflow.md](./automated-publication-research-workflow.md)

External Ralph loop references (not Papyrus-owned): [ralphloops.io](https://ralphloops.io/),
[ralphloop.sh](https://ralphloop.sh/).
