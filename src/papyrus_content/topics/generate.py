"""Everything generated from the topic operation table (``operations.py``). Run ``python scripts/generate-topic-operations.py`` to rewrite the
files, ``--check`` to list the ones that are out of date. A test runs the same check, so the files cannot drift from the table.

It is the image generator (``images/generate.py``) pointed at this table: the helpers that turn a schema into a flag spec, a TypeScript type or a
table are the same ones. Fully generated files are written whole; the skill and docs/topics.md keep their hand-written prose and have one
generated block between markers.
"""
from __future__ import annotations

import json
import pprint
from pathlib import Path

from papyrus_content.images.generate import agent_words, cell, cli_command, pascal, schema_table, ts_type

from .operations import COMMON_ERRORS, ERRORS, OPERATIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
CLI_SPEC = PACKAGE / "cli_generated.py"
MCP_SCHEMA = PACKAGE / "mcp_tools.generated.json"
TS_TYPES = REPO_ROOT / "lib" / "topics" / "operations.generated.ts"
SKILL = REPO_ROOT / "skills" / "topic-work" / "SKILL.md"
DOCS = REPO_ROOT / "docs" / "topics.md"

SOURCE = "src/papyrus_content/topics/operations.py"
BEGIN, END = "<!-- generated:topic-operations -->", "<!-- /generated:topic-operations -->"

SKILL_TEMPLATE = f"""---
name: topic-work
description: Use when you want to know what the newsroom's recent References are about: the topics of the last week, two weeks or four, which are rising or falling, and which References show them.
---

# Topic work

This skill is for any agent that needs the shape of recent References, through `papyrus topics model` or the `topics_model` MCP tool. They are
the same operation, with the same input and the same JSON result.

Start with the default (the last 14 days, accepted and pending References, compared with the 14 days before). Narrow it with `--section` or
`--monitor` only when you have a reason. Read the marks as words as well as symbols: a topic marked rising has a larger share of this window
than of the one before, a new one had nothing like it before. A topic is a lead, not a verdict: open its representative References before you
write about it. Nothing here publishes anything.

{BEGIN}
{END}
"""

DOCS_TEMPLATE = f"""# Topics

What the newsroom's recent References are about, on demand. `papyrus topics model` (and the `topics_model` MCP tool) reads the References of a
window of days, finds their topics with the same engine the weekly knowledge run uses, and marks each topic rising, falling, steady or new
against the window before. It is an interactive tool for editors and editor agents. It publishes nothing and changes no record. Epic PPY-d0f028.

Every topic action is one operation in one table, `{SOURCE}`. The `papyrus topics` commands, the MCP tool schema, the newsroom's TypeScript types,
the `topic-work` skill's reference and this page's reference section are generated from it, so they cannot disagree.

**Adding or changing an operation:** edit the table, then run `python scripts/generate-topic-operations.py`. A test fails when a generated file is out of date.

## How a run works

1. **The window.** Whole days, counted back from `--as-of` (today by default), on each Reference's **source date** (`sourcePublishedAt`), never the date
   it reached the newsroom. Presets are `7d`, `14d` (the default) and `28d`. The previous window is the same number of days ending the day before.
2. **The read.** The References come through the index `listReferencesByCorpusAndSourcePublishedAt` (corpus, then source date): only the window is
   read, a page of 100 at a time, never the table. A Reference with no source date, or one that is not written as an ISO date, is not in the index and is
   not seen. Each returned row is then kept or dropped: only the current version; the vote (default accepted and pending, rejected only with
   `--states`); the section its vote was filed under (`--section`); the monitor that delivered it (`--monitor`). `--max-references` is a safety stop only:
   when it is reached the run says so in `warnings` and in the log. There is no other cap.
3. **The text.** A Reference's title and the summary held on its row (`cardSummary`). The engine sees nothing else.
4. **The model.** Both windows are modeled together in one pass, so a topic means the same thing in both. The smallest topic scales with the number of
   References, the square root, never under 3 (`--min-cluster-size` overrides). The engine is BERTopic through Biblicus with the knowledge run's settings
   (`knowledge_snapshot/topic_config.py`), behind the small interface in `src/papyrus_content/topics/engine.py`; tests use a deterministic fake.
5. **The trend.** Each topic's share of the current window against its share of the previous one, by a two-proportion test at 95 percent: **rising**
   (a larger share), **falling** (a smaller share), **steady** (no clear change), or **new** (nothing in the previous window). The result carries the
   mark (`▲ ▼ = +`) and the word, and a legend, so the trend never depends on colour.
6. **The saved id.** A hash of the question, the engine and the exact Reference versions (`id` and `updatedAt`). Asking the same thing of the same
   References finds the earlier answer (`cached: true`) and models nothing; `--refresh` models again. The full record, member lists included, is kept
   in a folder on the machine that ran the command (`PAPYRUS_TOPICS_DIR`, else `~/.cache/papyrus/topics`).

Small windows run inline, on the machine that asked. The engine is behind a plain interface (documents in, topics out, nothing else), so a later cloud
job can run the same call and store the same record; that job, `topics.show` and `topics.members`, and the public Trending block are follow-ups.

## What it needs deployed

The index is one new global secondary index on `Reference`. It uses attributes the table already has, so no backfill is needed. A site gets it when
its data API is released and deployed; until then the command answers `service_unavailable`. A deploy can add only one index per table, so this one
must not share a release with another Reference index.

{BEGIN}
{END}
"""


def replace_block(text: str, block: str) -> str:
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + BEGIN + "\n" + block.strip("\n") + "\n" + END + text[end:]


def render_cli() -> str:
    data = [{**cli_command(item), "group": "topics"} for item in OPERATIONS]
    return (f'"""The `papyrus topics` commands: every flag the CLI reads, by operation.\n\nGenerated by scripts/generate-topic-operations.py from {SOURCE}. '
            'Do not edit by hand.\n"""\n\nCOMMANDS = ' + pprint.pformat(data, width=150, sort_dicts=False) + "\n")


def render_mcp() -> str:
    tools = [{"name": item.name, "audience": item.audience, "description": item.summary, "agentAllowed": item.agent_allowed, "effect": item.effect,
              "inputSchema": item.input, "outputSchema": item.result} for item in OPERATIONS]
    return json.dumps({"generatedFrom": SOURCE, "tools": tools}, indent=2) + "\n"


def render_ts() -> str:
    names = [item.name for item in OPERATIONS]
    out = [f"// Generated by scripts/generate-topic-operations.py from {SOURCE}. Do not edit by hand.",
           "// Types for every topic operation's input and result.", "",
           "export type TopicOperationName =", *[f"  | {json.dumps(name)}" for name in names] + [";", ""],
           "export type TopicErrorCode =", *[f"  | {json.dumps(error.code)}" for error in ERRORS] + [";", ""],
           "export type TopicWarning = { code: string; message: string };", "",
           "export type TopicErrorBody = {", "  code: TopicErrorCode;", "  message: string;", "  retryable: boolean;", "  details: Record<string, unknown>;", "};", "",
           "export type TopicEnvelope<Result> =",
           "  | { ok: true; op: TopicOperationName; publication: string; result: Result; warnings: TopicWarning[] }",
           "  | { ok: false; op: string; error: TopicErrorBody };", ""]
    for item in OPERATIONS:
        out += [f"/** {item.summary} */", f"export type {pascal(item.name)}Input = {ts_type(item.input)};", "",
                f"export type {pascal(item.name)}Result = {ts_type(item.result)};", ""]
    out += ["export interface TopicOperations {"]
    out += [f"  {item.name}: {{ input: {pascal(item.name)}Input; result: {pascal(item.name)}Result }};" for item in OPERATIONS]
    out += ["}", "", "export const TOPIC_OPERATIONS = {"]
    for item in OPERATIONS:
        out.append(f"  {item.name}: {{ effect: {json.dumps(item.effect)}, agentAllowed: {json.dumps(item.agent_allowed)}, command: {json.dumps(item.command)} }},")
    out += ["} as const;", ""]
    return "\n".join(out)


def error_table() -> list[str]:
    lines = ["| Code | Meaning | Retry? | Details |", "| --- | --- | --- | --- |"]
    for error in ERRORS:
        lines.append(f"| `{error.code}` | {cell(error.message)} | {'yes' if error.retryable else 'no'} | {cell(error.details)} |")
    return lines


def skill_block() -> str:
    lines = [f"<!-- Generated from {SOURCE}. Do not edit by hand; run scripts/generate-topic-operations.py. -->", "", "## Reference: the operations", "",
             "Each operation is a command and a tool with the same input and the same JSON result.", "",
             "| Operation (MCP tool) | Command | What it does | Agent may call | Errors it can return |", "| --- | --- | --- | --- | --- |"]
    for item in OPERATIONS:
        errors = ", ".join(f"`{code}`" for code in item.errors) or "only the common ones"
        lines.append(f"| `{item.name}` | `{item.command}` | {cell(item.summary)} | {agent_words(item)} | {errors} |")
    lines += ["", f"Every operation may also return: {', '.join(f'`{code}`' for code in COMMON_ERRORS)}.", "", "### Every result", "",
              "Success: `{\"ok\": true, \"op\": \"...\", \"publication\": \"...\", \"result\": {...}, \"warnings\": []}`. "
              "Failure: `{\"ok\": false, \"op\": \"...\", \"error\": {\"code\": \"...\", \"message\": \"...\", \"retryable\": false, \"details\": {}}}`. "
              "The command prints this JSON; it exits 0 on success and 2 on any error. `warnings` can say that a safety stop ended the read, that there were "
              "too few References for topics, or that the previous window was empty: read them.", "", "### Errors", "", *error_table()]
    return "\n".join(lines)


def docs_block() -> str:
    lines = [f"<!-- Generated from {SOURCE}. Do not edit by hand; run scripts/generate-topic-operations.py. -->", "", "## Operations", "",
             "| Operation (MCP tool) | Command | Effect | What it does |", "| --- | --- | --- | --- |"]
    for item in OPERATIONS:
        lines.append(f"| [`{item.name}`](#{item.name.replace('_', '-')}) | `{item.command}` | {item.effect} | {cell(item.summary)} |")
    lines += ["", "Effect: `read` changes no record in the backend. Every operation needs an editor or admin of the site; readers get none.", "",
              "## Results and errors", "",
              "Every call returns one envelope. Success: `{\"ok\": true, \"op\", \"publication\", \"result\", \"warnings\"}`. Failure: "
              "`{\"ok\": false, \"op\", \"error\": {\"code\", \"message\", \"retryable\", \"details\"}}`. The commands print the envelope as JSON and exit 0 "
              "on success and 2 on any error. `--input-file PATH` gives the whole input as JSON; flags override it.", "",
              f"Every operation may return {', '.join(f'`{code}`' for code in COMMON_ERRORS)}.", "", *error_table(), ""]
    for item in OPERATIONS:
        lines += [f"## {item.name}", "", item.summary, "", f"- Command: `{item.command}`", f"- MCP tool: `{item.name}`", f"- Effect: {item.effect}",
                  f"- Agent may call: {agent_words(item)}"]
        if item.notes:
            lines.append(f"- Note: {item.notes}")
        lines += ["", "Input:", "", *schema_table(item.input), "", "Result:", "", *schema_table(item.result), ""]
        lines.append("Errors: " + (", ".join(f"`{code}`" for code in item.errors) or "only the common ones") + ".")
        for example in item.examples:
            lines += ["", "Example input:", "", "```json", json.dumps(example.input, indent=2), "```", "", "Example result:", "", "```json",
                      json.dumps(example.result, indent=2), "```"]
        lines.append("")
    return "\n".join(lines)


def outputs() -> dict[Path, str]:
    """The text every generated file should have now."""
    skill = SKILL.read_text(encoding="utf-8") if SKILL.exists() else SKILL_TEMPLATE
    docs = DOCS.read_text(encoding="utf-8") if DOCS.exists() else DOCS_TEMPLATE
    return {CLI_SPEC: render_cli(), MCP_SCHEMA: render_mcp(), TS_TYPES: render_ts(),
            SKILL: replace_block(skill, skill_block()), DOCS: replace_block(docs, docs_block())}


def stale() -> list[Path]:
    return [path for path, text in outputs().items() if not path.exists() or path.read_text(encoding="utf-8") != text]


def write() -> list[Path]:
    changed = stale()
    for path, text in outputs().items():
        if path in changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    if argv == ["--check"]:
        behind = stale()
        for path in behind:
            print(f"out of date: {path.relative_to(REPO_ROOT)}")
        if behind:
            print("run: python scripts/generate-topic-operations.py")
        return 1 if behind else 0
    if argv:
        print("usage: generate-topic-operations.py [--check]")
        return 2
    for path in write():
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0
