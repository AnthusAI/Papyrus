"""Everything generated from the operation table (``operations.py``). Run ``python scripts/generate-image-operations.py`` to rewrite the files,
``--check`` to list the ones that are out of date. A test runs the same check, so the files cannot drift from the table.

Fully generated files are written whole. The skill and docs/images.md keep their hand-written prose and have one generated block between markers.
"""
from __future__ import annotations

import json
import pprint
import re
from pathlib import Path

from .operations import COMMON_ERRORS, ERROR_BY_CODE, ERRORS, OPERATIONS, Operation

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
CLI_SPEC = PACKAGE / "cli_generated.py"
MCP_SCHEMA = PACKAGE / "mcp_tools.generated.json"
TS_TYPES = REPO_ROOT / "lib" / "images" / "operations.generated.ts"
SKILL = REPO_ROOT / "skills" / "image-work" / "SKILL.md"
DOCS = REPO_ROOT / "docs" / "images.md"

SOURCE = "src/papyrus_content/images/operations.py"
IMAGE_OPERATIONS = tuple(item for item in OPERATIONS if item.group == "images")   # the skill and docs/images.md describe pictures; guidelines are in the CLI guide
BEGIN, END = "<!-- generated:image-operations -->", "<!-- /generated:image-operations -->"

SKILL_TEMPLATE = f"""---
name: image-work
description: Use when a Story or Reference needs a picture: finding stock images, generating options from the publication's visual style, choosing, applying or keeping the placeholder.
---

# Image work

This skill is for any agent that adds a picture to a Story or Reference, through the `papyrus images` commands or the `image_*` MCP tools. They are
the same operations, with the same input and the same JSON result.

The guidance on when to use stock, when to generate, how to choose, and how review works is written in a later build step. Until then, read the
reference below, and treat a picture you apply without a person as a suggestion: it is not approved.

{BEGIN}
{END}
"""

DOCS_TEMPLATE = f"""# Images

Every image action is one operation in one table, `{SOURCE}`. The `papyrus images` commands, the `image_*` MCP tools, the newsroom's TypeScript types,
the `image-work` skill's reference and this page are generated from it, so they cannot disagree. The design is in `project/wiki/image-toolchain.md`.

**Adding or changing an operation:** edit the table, then run `python scripts/generate-image-operations.py`. A test fails when a generated file is out of date.

Every operation is still a stub that answers `not_implemented`; later build steps fill them in.

{BEGIN}
{END}
"""


# --- small helpers ----------------------------------------------------------------------------------------------------------------------------------

def kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def is_target(schema: dict) -> bool:
    return schema.get("type") == "object" and schema.get("properties", {}).get("kind", {}).get("enum") == ["story", "reference"]


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def replace_block(text: str, block: str) -> str:
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + BEGIN + "\n" + block.strip("\n") + "\n" + END + text[end:]


def kind_of(schema: dict) -> str:
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    return "/".join(str(kind) for kind in kinds if kind) or "any"


def agent_words(item: Operation) -> str:
    return "yes" if item.agent_allowed else "no, a person only"


# --- the CLI spec ---------------------------------------------------------------------------------------------------------------------------------

def cli_command(item: Operation) -> dict:
    properties, required = item.input.get("properties", {}), set(item.input.get("required", ()))
    renamed = dict(item.flags)
    flags = []
    for field, schema in properties.items():
        if field in item.positional or field == item.file_field:
            continue
        if is_target(schema):
            flags.append({"field": field, "flag": "--story", "kind": "target", "targetKind": "story"})
            flags.append({"field": field, "flag": "--reference", "kind": "target", "targetKind": "reference"})
            continue
        kind = schema.get("type")
        if kind == "array":
            flags.append({"field": field, "flag": "--" + renamed.get(field, kebab(field)), "kind": "array", "item": schema["items"]["type"]})
        elif kind in ("string", "integer", "boolean"):
            entry = {"field": field, "flag": "--" + renamed.get(field, kebab(field)), "kind": kind}
            if "enum" in schema:
                entry["enum"] = schema["enum"]
            flags.append(entry)
        # other objects are given with --input-file
    words = " ".join(item.cli)
    parts = [f"papyrus {item.group} {words}"] + [f"<{kebab(field)}>" if field in required else f"[{kebab(field)}]" for field in item.positional]
    if item.file_field:
        parts.append("--file PATH")
    seen_target = False
    for entry in flags:
        shown = {"string": "TEXT", "integer": "N", "boolean": "", "array": "TEXT ..."}.get(entry["kind"], "ID")
        if entry["kind"] == "target":
            if seen_target:
                continue
            seen_target = True
            text = "(--story ID | --reference ID)"
            parts.append(text if entry["field"] in required else "[--story ID | --reference ID]")
            continue
        if entry["kind"] == "boolean":
            text = entry["flag"] + (f" | --no-{entry['flag'][2:]}")
        else:
            text = f"{entry['flag']} {'|'.join(entry['enum']) if 'enum' in entry else shown}"
        parts.append(text if entry["field"] in required else f"[{text}]")
    parts.append("[--input-file PATH]")
    if item.effect != "read":
        parts.append("[--dry-run]")
    return {"op": item.name, "group": item.group, "words": list(item.cli), "summary": item.summary, "effect": item.effect, "agentAllowed": item.agent_allowed,
            "usage": " ".join(parts), "positional": list(item.positional), "file": item.file_field, "flags": flags}


def render_cli() -> str:
    data = [cli_command(item) for item in OPERATIONS]
    return (f'"""The `papyrus images` commands: every flag the CLI reads, by operation.\n\nGenerated by scripts/generate-image-operations.py from {SOURCE}. '
            'Do not edit by hand.\n"""\n\nCOMMANDS = ' + pprint.pformat(data, width=150, sort_dicts=False) + "\n")


# --- the MCP schema -------------------------------------------------------------------------------------------------------------------------------

def render_mcp() -> str:
    tools = [{"name": item.name, "audience": item.audience, "description": item.summary, "agentAllowed": item.agent_allowed, "effect": item.effect,
              "inputSchema": item.input, "outputSchema": item.result} for item in OPERATIONS]
    return json.dumps({"generatedFrom": SOURCE, "tools": tools}, indent=2) + "\n"


# --- TypeScript -----------------------------------------------------------------------------------------------------------------------------------

def ts_type(schema: dict, indent: int = 0) -> str:
    pad = "  " * indent
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    parts = []
    for kind in kinds:
        if kind in ("string", "boolean"):
            parts.append(kind)
        elif kind in ("integer", "number"):
            parts.append("number")
        elif kind == "null":
            parts.append("null")
        elif kind == "array":
            inner = ts_type(schema["items"], indent)
            parts.append(f"({inner})[]" if " | " in inner else f"{inner}[]")
        elif kind == "object":
            properties = schema.get("properties") or {}
            if not properties:
                parts.append("Record<string, unknown>")
                continue
            required = set(schema.get("required", ()))
            lines = []
            for name, child in properties.items():
                if child.get("description"):
                    lines.append(f"{pad}  /** {child['description']} */")
                lines.append(f"{pad}  {name}{'' if name in required else '?'}: {ts_type(child, indent + 1)};")
            parts.append("{\n" + "\n".join(lines) + f"\n{pad}}}")
    return " | ".join(parts) if parts else "unknown"


def render_ts() -> str:
    names = [item.name for item in OPERATIONS]
    out = [f"// Generated by scripts/generate-image-operations.py from {SOURCE}. Do not edit by hand.",
           "// Types for every image operation's input and result, and one call that sends them through a transport (the newsroom's server code",
           "// supplies the transport that reaches the image door; this file does not know about it).", "",
           "export type ImageOperationName =", *[f"  | {json.dumps(name)}" for name in names] + [";", ""],
           "export type ImageErrorCode =", *[f"  | {json.dumps(error.code)}" for error in ERRORS] + [";", ""],
           "export type ImageWarning = { code: string; message: string };", "",
           "export type ImageErrorBody = {", "  code: ImageErrorCode;", "  message: string;", "  retryable: boolean;", "  details: Record<string, unknown>;", "};", "",
           "export type ImageEnvelope<Result> =",
           "  | { ok: true; op: ImageOperationName; publication: string; result: Result; warnings: ImageWarning[] }",
           "  | { ok: false; op: string; error: ImageErrorBody };", ""]
    for item in OPERATIONS:
        out += [f"/** {item.summary} */", f"export type {pascal(item.name)}Input = {ts_type(item.input)};", "",
                f"export type {pascal(item.name)}Result = {ts_type(item.result)};", ""]
    out += ["export interface ImageOperations {"]
    out += [f"  {item.name}: {{ input: {pascal(item.name)}Input; result: {pascal(item.name)}Result }};" for item in OPERATIONS]
    out += ["}", "", "/** What each operation is, for the transport: read operations are queries, write and spend operations are mutations. */",
            "export const IMAGE_OPERATIONS = {"]
    for item in OPERATIONS:
        out.append(f"  {item.name}: {{ effect: {json.dumps(item.effect)}, agentAllowed: {json.dumps(item.agent_allowed)}, group: {json.dumps(item.group)}, "
                   f"command: {json.dumps(item.command)} }},")
    out += ["} as const;", "",
            "/** `group` says which door: images go through imageRead and imageWrite, guidelines through guidelinesRead and guidelinesWrite. */",
            "export type ImageTransport = (request: {", "  op: ImageOperationName;", "  input: unknown;", "  effect: \"read\" | \"write\" | \"spend\";",
            "  group: \"images\" | \"guidelines\";", "}) => Promise<unknown>;", "",
            "export async function callImageOperation<Name extends ImageOperationName>(",
            "  name: Name,", "  input: ImageOperations[Name][\"input\"],", "  send: ImageTransport,",
            "): Promise<ImageEnvelope<ImageOperations[Name][\"result\"]>> {",
            "  const answer = await send({ op: name, input, effect: IMAGE_OPERATIONS[name].effect, group: IMAGE_OPERATIONS[name].group });",
            "  return answer as ImageEnvelope<ImageOperations[Name][\"result\"]>;", "}", ""]
    return "\n".join(out)


# --- the skill's reference block and the docs -----------------------------------------------------------------------------------------------------

def error_table() -> list[str]:
    lines = ["| Code | Meaning | Retry? | Details |", "| --- | --- | --- | --- |"]
    for error in ERRORS:
        lines.append(f"| `{error.code}` | {cell(error.message)} | {'yes' if error.retryable else 'no'} | {cell(error.details)} |")
    return lines


def skill_block() -> str:
    lines = [f"<!-- Generated from {SOURCE}. Do not edit by hand; run scripts/generate-image-operations.py. -->", "", "## Reference: the operations", "",
             "Each operation is a command and a tool with the same input and the same JSON result. A person-only operation returns `human_required` to an agent.", "",
             "| Operation (MCP tool) | Command | What it does | Agent may call | Errors it can return |", "| --- | --- | --- | --- | --- |"]
    for item in IMAGE_OPERATIONS:
        errors = ", ".join(f"`{code}`" for code in item.errors) or "only the common ones"
        lines.append(f"| `{item.name}` | `{item.command}` | {cell(item.summary)} | {agent_words(item)} | {errors} |")
    lines += ["", f"Every operation may also return: {', '.join(f'`{code}`' for code in COMMON_ERRORS)}.", "", "### Every result", "",
              "Success: `{\"ok\": true, \"op\": \"...\", \"publication\": \"...\", \"result\": {...}, \"warnings\": []}`. "
              "Failure: `{\"ok\": false, \"op\": \"...\", \"error\": {\"code\": \"...\", \"message\": \"...\", \"retryable\": false, \"details\": {}}}`. "
              "The command prints this JSON; it exits 0 on success and 2 on any error.", "", "### Errors", "", *error_table()]
    return "\n".join(lines)


def schema_table(schema: dict) -> list[str]:
    properties, required = schema.get("properties", {}), set(schema.get("required", ()))
    if not properties:
        return ["None."]
    lines = ["| Name | Type | Required | Notes |", "| --- | --- | --- | --- |"]
    for name, child in properties.items():
        note = child.get("description", "")
        if "enum" in child:
            note = (note + " " if note else "") + "One of: " + ", ".join(f"`{value}`" for value in child["enum"]) + "."
        lines.append(f"| `{name}` | {kind_of(child)} | {'yes' if name in required else 'no'} | {cell(note)} |")
    if schema.get("oneOf"):
        lines += ["", "Give exactly one of: " + ", ".join(f"`{option['required'][0]}`" for option in schema["oneOf"]) + "."]
    return lines


def docs_block() -> str:
    lines = [f"<!-- Generated from {SOURCE}. Do not edit by hand; run scripts/generate-image-operations.py. -->", "", "## Operations", "",
             "| Operation (MCP tool) | Command | Effect | What it does |", "| --- | --- | --- | --- |"]
    for item in IMAGE_OPERATIONS:
        lines.append(f"| [`{item.name}`](#{item.name.replace('_', '-')}) | `{item.command}` | {item.effect} | {cell(item.summary)} |")
    lines += ["", "Effect: `read` changes nothing; `write` changes records; `spend` asks an image provider to make something, which costs money and only works when the "
              "site's image generation is configured and approved. Every operation needs an editor or admin of the site; readers get none.", "",
              "## Results and errors", "",
              "Every call returns one envelope. Success: `{\"ok\": true, \"op\", \"publication\", \"result\", \"warnings\"}`. Failure: "
              "`{\"ok\": false, \"op\", \"error\": {\"code\", \"message\", \"retryable\", \"details\"}}`.", "",
              "The commands print the envelope as JSON and exit 0 on success and 2 on any error. `--dry-run` on a write or spend command checks the input and "
              "prints it back as `{\"dryRun\": true, \"input\": ...}` in the result without calling anything. `--input-file PATH` gives the whole input as JSON; flags override it. "
              "A command is run as a person unless `PAPYRUS_ACTOR_KIND=agent` is set; an agent may not call person-only operations and gets one picture, not a set.", "",
              f"Every operation may return {', '.join(f'`{code}`' for code in COMMON_ERRORS)}.", "", *error_table(), ""]
    for item in IMAGE_OPERATIONS:
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


# --- putting it together --------------------------------------------------------------------------------------------------------------------------

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
            print("run: python scripts/generate-image-operations.py")
        return 1 if behind else 0
    if argv:
        print("usage: generate-image-operations.py [--check]")
        return 2
    for path in write():
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0
