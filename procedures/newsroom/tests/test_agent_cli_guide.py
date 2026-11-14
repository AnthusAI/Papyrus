"""The agent CLI guide cannot drift from the CLI (features_backend/agent-cli-guide.feature).

Every fenced `papyrus ...` command in docs/agent-cli-guide.md must name a command in the CLI's route table, and every `--flag` it uses must
appear in that command's `--help` usage. Every route must print real usage for `--help`. A recipe for a pull request that has not merged is
marked `pending` in its fence and listed in PENDING below, so the day it merges the mark must come off (this test fails until it does).
"""
from __future__ import annotations

import io
import re
import shlex
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from papyrus import cli
from papyrus.operator.command_usage import _ENTRIES, usage_for_path
from papyrus.operator.help_dispatch import all_routes, answer_help, route_tree
from papyrus_content import agent_guide

REPO = Path(__file__).resolve().parents[3]
GUIDE = REPO / "docs" / "agent-cli-guide.md"
PACKAGED = REPO / "src" / "papyrus_content" / "data" / "agent-cli-guide.md"

# Flags that exist only in a pull request that has not merged: flag -> the pull request. Recipes that use them sit in ```sh pending fences.
PENDING = {
    "--no-rerender": "PR #1344 (story link commands re-render the affected pages)",
}
# Flags accepted by the whole CLI or by a form the usage text does not list per command.
GLOBAL_FLAGS = {"--help", "-h", "--version", "--site", "--backend", "--allow-cross-root", "--budget"}

FENCE = re.compile(r"^```(\S*)\s*(\S*)\s*$")


def fenced_commands() -> list[tuple[int, bool, str]]:
    """(line number, in a pending fence, command line) for every `papyrus ...` line in a fenced shell block of the guide."""
    found: list[tuple[int, bool, str]] = []
    inside = False
    shell = False
    pending = False
    for number, line in enumerate(GUIDE.read_text(encoding="utf-8").splitlines(), start=1):
        match = FENCE.match(line)
        if match and not inside:
            inside, shell, pending = True, match.group(1) in {"sh", "bash", "shell"}, match.group(2) == "pending"
            continue
        if line.strip() == "```" and inside:
            inside = False
            continue
        if inside and shell and line.startswith("papyrus "):
            found.append((number, pending, line))
    return found


def resolve(words: list[str]) -> list[str] | None:
    node = route_tree()
    path: list[str] = []
    for word in words:
        if path and not node:
            break
        if word not in node:
            return None
        node = node[word]
        path.append(word)
    return path if not node else None


def usage_text(path: list[str]) -> str:
    if path[0] == "images":
        from papyrus_content.images.cli import usage_for

        return usage_for(path[1:]) or ""
    entry = usage_for_path(path)
    return entry.render() if entry is not None else ""


def flags_of(tokens: list[str]) -> list[str]:
    return [token.split("=", 1)[0] for token in tokens if token.startswith("-") and not token.lstrip("-").isdigit() and token != "-"]


def mentions(text: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


COMMANDS = fenced_commands()


def test_the_guide_has_recipes():
    assert len(COMMANDS) > 40


@pytest.mark.parametrize("number, pending, line", COMMANDS, ids=[f"L{number}" for number, _, _ in COMMANDS])
def test_every_fenced_command_exists_with_the_flags_it_uses(number, pending, line):
    tokens = shlex.split(line)[1:]
    if tokens[:1] == ["--site"]:
        tokens = tokens[2:]
    words = []
    for token in tokens:
        if token.startswith("-"):
            break
        words.append(token)
    if not words:
        assert set(flags_of(tokens)) <= GLOBAL_FLAGS, f"line {number}: `{line}` names no command"
        return
    path = resolve(words)
    assert path is not None, f"line {number}: `{line}` is not a papyrus command; `papyrus <group> --help` lists the commands"
    usage = usage_text(path)
    assert usage, f"line {number}: `{' '.join(path)}` prints no usage"
    for flag in flags_of(tokens[len(path):]):
        if flag in GLOBAL_FLAGS:
            continue
        if flag in PENDING:
            assert pending, f"line {number}: {flag} is pending ({PENDING[flag]}) but this fence is not marked `pending`"
            continue
        assert mentions(usage, flag), f"line {number}: `{' '.join(path)}` uses {flag}, which its --help does not show:\n{usage}"


def test_pending_marks_and_the_pending_list_agree():
    marked = {line for _, pending, line in COMMANDS if pending}
    used = {flag for line in marked for flag in flags_of(shlex.split(line))}
    for flag in PENDING:
        assert flag in used, f"{flag} is listed as pending ({PENDING[flag]}) but no pending fence uses it: remove it from PENDING when the pull request merges"
    for number, pending, line in COMMANDS:
        if pending:
            assert used & set(PENDING), f"line {number}: a pending fence must use a flag listed in PENDING"
        elif any(flag in PENDING for flag in flags_of(shlex.split(line))):
            raise AssertionError(f"line {number}: uses a pending flag outside a pending fence")


def test_the_packaged_copy_is_the_guide():
    assert PACKAGED.read_text(encoding="utf-8") == GUIDE.read_text(encoding="utf-8"), (
        "docs/agent-cli-guide.md and src/papyrus_content/data/agent-cli-guide.md differ: copy the first over the second")


def test_every_task_section_is_listed_and_every_recipe_pointer_exists():
    names = {name for name, _, _ in agent_guide.sections()}
    assert {"orientation", "find", "file-reference", "tag-and-link", "write-story", "publish", "checks", "troubleshooting", "not-built"} <= names
    for path, entry in _ENTRIES.items():
        assert not entry.guide or entry.guide in names, f"{path} points at a guide task that does not exist: {entry.guide}"


def run_help(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = answer_help([*args, "--help"])
    return status, out.getvalue(), err.getvalue()


ROUTES = all_routes()


@pytest.mark.parametrize("route", ROUTES, ids=[" ".join(route) for route in ROUTES])
def test_every_route_prints_real_help(route):
    status, out, _ = run_help(route)
    assert status == 0, route
    assert out.strip(), f"papyrus {' '.join(route)} --help printed nothing"
    node = route_tree()
    for word in route:
        node = node[word]
    first = out.lstrip().splitlines()[0].lower()
    assert first.startswith("usage"), f"papyrus {' '.join(route)} --help starts with {first!r}"
    if node:
        assert "<command>" in out, route          # a group lists its commands
    elif route[0] not in {"images", "monitors"}:
        assert "Lane:" in out and "Writes:" in out, f"papyrus {' '.join(route)} --help does not say its lane and whether it writes"
        assert len(out.strip().splitlines()) >= 3


def test_the_usage_table_names_only_real_routes():
    leaves = {" ".join(route) for route in ROUTES}
    for path in _ENTRIES:
        assert path in leaves or path in {"guide"}, f"command_usage.py describes `papyrus {path}`, which is not a route"


def test_the_priority_commands_document_their_real_flags():
    required = {
        "references make-catalog": ["--input", "--output"],
        "references prepare-catalog": ["--catalog", "--output", "--corpus-key"],
        "references create-from-catalog": ["--catalog", "--corpus-key", "--status", "--dry-run", "--ingestion-rationale"],
        "references link": ["--reference", "--to-reference", "--concept", "--create", "--predicate", "--dry-run"],
        "references link-concept": ["--reference", "--concept", "--dry-run"],
        "stories create": ["--title", "--type", "--section", "--stage", "--reference", "--dry-run"],
        "stories save-version": ["--story", "--body-file", "--reason", "--front-matter-file", "--dry-run"],
        "stories link-story": ["--to", "--reference", "--note", "--dry-run"],
        "stories link-reference": ["--role", "--citation-key", "--dry-run"],
        "knowledge concepts search": ["--limit", "--list", "--json"],
        "ops content publish": ["--id", "--slug", "--verify", "--dry-run"],
        "ops content rerender": ["--story", "--no-invalidate", "--dry-run"],
        "ops content refresh": ["--path", "--run", "--force-paths", "--dry-run"],
    }
    for path, flags in required.items():
        text = usage_text(path.split())
        for flag in flags:
            assert mentions(text, flag), f"{path} --help does not show {flag}"


def test_a_command_with_no_dry_run_says_it_writes_immediately():
    for path in ("ops relations import-types", "ops content rebuild", "knowledge concepts import-types"):
        text = usage_text(path.split())
        assert "NO --dry-run" in text, path
    assert "NO --dry-run" not in usage_text(["stories", "create"])


def run_main(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = cli.main(args)
    return status, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("args", [["stories", "create"], ["references", "link"], ["references", "make-catalog"], ["stories", "link-story"]])
def test_a_bare_command_prints_usage_with_the_error(args, monkeypatch):
    monkeypatch.delenv("PAPYRUS_SITE", raising=False)
    status, out, err = run_main(args)
    assert status != 0
    assert err.count(f"Usage: papyrus {' '.join(args)}") == 1, err
    assert "Lane:" in err and "Writes:" in err
    assert re.search(r"requires|required|is required", err.split("Recipe:")[-1]), err


def test_a_command_missing_one_flag_prints_usage_with_the_error(monkeypatch, tmp_path):
    status, out, err = run_main(["references", "make-catalog", "--input", str(tmp_path / "sources.txt")])
    assert status != 0
    assert "Usage: papyrus references make-catalog" in err and "requires --output" in err


def test_papyrus_guide_lists_and_prints_tasks():
    status, out, _ = run_main(["guide", "--list"])
    assert status == 0 and "file-reference" in out and "troubleshooting" in out
    status, out, _ = run_main(["guide", "tag-and-link"])
    assert status == 0 and out.startswith("## Tag and link") and "references link-concept" in out
    status, out, _ = run_main(["guide"])
    assert status == 0 and out == GUIDE.read_text(encoding="utf-8")
    status, out, err = run_main(["guide", "no-such-task"])
    assert status != 0 and "file-reference" in err


def test_top_level_help_and_group_help_point_to_the_guide():
    status, out, _ = run_main(["--help"])
    assert status == 0 and "papyrus guide" in out
    status, out, _ = run_main(["references", "--help"])
    assert status == 0
    assert re.search(r"make-catalog\s+\S", out) and re.search(r"create-from-catalog\s+\S", out)
    assert "local pod only" in out and "papyrus guide" in out


def test_the_docs_and_skills_point_to_the_guide():
    pointers = [
        REPO / "AGENTS.md",
        REPO / "docs" / "operator-cli.md",
        *sorted((REPO / ".claude" / "skills").glob("*/SKILL.md")),
    ]
    for path in pointers:
        text = path.read_text(encoding="utf-8")
        assert "agent-cli-guide" in text, f"{path.relative_to(REPO)} does not point at docs/agent-cli-guide.md"
