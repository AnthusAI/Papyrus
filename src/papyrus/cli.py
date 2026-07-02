from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from papyrus_content import cli as content_cli
from papyrus_content.env import PAPYRUS_ROOT
from papyrus_newsroom import cli as newsroom_cli

_ALLOW_CROSS_ROOT_FLAG = "--allow-cross-root"
_TRUTHY = {"1", "true", "yes", "on"}


def _usage() -> None:
    print("Usage: poetry run papyrus [--allow-cross-root] <group> <command> [options]")
    print(
        "Groups: assignments, reporting, research, references, knowledge, sections, editions, procedures, analysis, auth, batch, ops, videos"
    )


def _delegate_content(group: str, command: str, flags: list[str]) -> None:
    content_cli.load_dotenv()
    content_cli.dispatch(group, command, flags)


def _delegate_newsroom(argv: list[str]) -> int:
    return newsroom_cli.main(argv)


def _require_command(group: str, argv: list[str]) -> tuple[str, list[str]]:
    if len(argv) < 2:
        raise ValueError(f"papyrus {group} requires <command>.")
    return argv[1], argv[2:]


def _map_reporting(command: str, flags: list[str]) -> None:
    mapped = {
        "create": "create-reporting",
        "run": "run-reporting",
        "apply": "apply-reporting-packet",
        "review": "review-reporting-packet",
        "copywriting": "run-copywriting",
        "copywriting-output": "copywriting-output",
    }.get(command)
    if not mapped:
        raise ValueError(f"Unsupported papyrus reporting command: {command}")
    _delegate_content("assignments", mapped, flags)


def _map_research(command: str, flags: list[str]) -> None:
    mapped = {
        "create": "create-research",
        "run": "run-research",
        "run-tavily-deep": "run-tavily-deep-research",
        "poll-tavily-deep": "poll-tavily-deep-research",
        "apply": "apply-research-packet",
        "process": "process-research-now",
        "packets": "research-packets",
        "process-proposals": "process-proposals",
    }.get(command)
    if not mapped:
        raise ValueError(f"Unsupported papyrus research command: {command}")
    _delegate_content("assignments", mapped, flags)


def _map_sections(command: str, flags: list[str]) -> None:
    mapped = {
        "import": "import-sections",
        "import-doctrine": "import-doctrine",
        "recount-summary": "recount-summary",
        "repair-message-status": "repair-message-status",
        "backfill-feed-fields": "backfill-feed-fields",
        "backfill-operational-indexes": "backfill-operational-indexes",
        "prune-attachments": "prune-attachments",
        "purge-planning": "purge-planning",
    }.get(command)
    if not mapped:
        raise ValueError(f"Unsupported papyrus sections command: {command}")
    _delegate_content("newsroom", mapped, flags)


def _map_procedures(command: str, flags: list[str]) -> int:
    if command == "seed-required":
        _delegate_content("newsroom", "seed-required-procedures", flags)
        return 0
    if command == "execute-tactus":
        return _delegate_newsroom(["execute-tactus", *flags])
    if command == "policy":
        if not flags:
            raise ValueError("papyrus procedures policy requires <command>.")
        _delegate_content("policy", flags[0], flags[1:])
        return 0
    raise ValueError(f"Unsupported papyrus procedures command: {command}")


def _map_assignments(command: str, flags: list[str]) -> int:
    if command == "run-story-cycle":
        return _delegate_newsroom(["assignments", "run-story-cycle", *flags])
    if command == "story-cycle-output":
        return _delegate_newsroom(["assignments", "story-cycle-output", *flags])
    if command == "build-assignment-agent-context":
        return _delegate_newsroom(["build-assignment-agent-context", *flags])
    _delegate_content("assignments", command, flags)
    return 0


def _map_references(command: str, flags: list[str]) -> int:
    newsroom_reference_commands = {
        "list",
        "curate-recent",
        "summaries",
        "summarize",
        "summarize-batch",
        "summary-cleanup-legacy",
        "quality",
        "title-subtitle",
    }
    if command in newsroom_reference_commands:
        return _delegate_newsroom(["references", command, *flags])
    _delegate_content("references", command, flags)
    return 0


def _map_knowledge(command: str, flags: list[str]) -> int:
    if command == "ontology":
        if not flags:
            raise ValueError("papyrus knowledge ontology requires <command>.")
        _delegate_content("ontology", flags[0], flags[1:])
        return 0
    if command == "query":
        return _delegate_newsroom(["knowledge-query", *flags])
    if command == "vector-index":
        return _delegate_newsroom(["knowledge-vector-index", *flags])
    if command == "signals":
        return _delegate_newsroom(["signals", *flags])
    if command == "topics":
        if not flags:
            raise ValueError("papyrus knowledge topics requires <command>.")
        _delegate_content("categories", flags[0], flags[1:])
        return 0
    if command == "concepts":
        if not flags:
            raise ValueError("papyrus knowledge concepts requires <command>.")
        _delegate_content("relations", flags[0], flags[1:])
        return 0
    raise ValueError(f"Unsupported papyrus knowledge command: {command}")


def _map_analysis(command: str, flags: list[str]) -> int:
    if command == "test":
        if not flags:
            raise ValueError("papyrus analysis test requires <command>.")
        _delegate_content("test", flags[0], flags[1:])
        return 0
    _delegate_content("analysis", command, flags)
    return 0


def _map_ops(command: str, flags: list[str]) -> int:
    if command not in {"content", "corpora", "categories", "relations", "messages"}:
        raise ValueError(f"Unsupported papyrus ops group: {command}")
    if not flags:
        raise ValueError(f"papyrus ops {command} requires <command>.")
    _delegate_content(command, flags[0], flags[1:])
    return 0


def _find_operator_repo_root(start: Path) -> Path | None:
    resolved = start.resolve()
    for candidate in [resolved, *resolved.parents]:
        if not (candidate / "pyproject.toml").exists():
            continue
        if (candidate / "src" / "papyrus").exists() and (candidate / "src" / "papyrus_content").exists():
            return candidate
    return None


def _consume_cross_root_override(args: list[str]) -> tuple[bool, list[str]]:
    allow_cross_root = str(os.environ.get("PAPYRUS_ALLOW_CROSS_ROOT", "")).strip().lower() in _TRUTHY
    filtered_args: list[str] = []
    for token in args:
        if token == _ALLOW_CROSS_ROOT_FLAG:
            allow_cross_root = True
            continue
        filtered_args.append(token)
    return allow_cross_root, filtered_args


def _command_display(args: list[str]) -> str:
    if not args:
        return "poetry run papyrus"
    return "poetry run papyrus " + " ".join(shlex.quote(value) for value in args)


def _enforce_root_guard(args: list[str], *, cwd: Path | None = None, module_root: Path | None = None) -> None:
    operator_cwd = (cwd or Path.cwd()).resolve()
    operator_root = _find_operator_repo_root(operator_cwd)
    if operator_root is None:
        return
    resolved_module_root = (module_root or PAPYRUS_ROOT).resolve()
    if operator_root == resolved_module_root:
        return
    module_file = Path(content_cli.__file__).resolve()
    recovery = f"cd {shlex.quote(str(operator_root))} && {_command_display(args)}"
    raise ValueError(
        "papyrus-root-guard\tblocked\tcross-root invocation detected\n"
        f"papyrus-root-guard\tcwd\t{operator_cwd}\n"
        f"papyrus-root-guard\toperator-root\t{operator_root}\n"
        f"papyrus-root-guard\tmodule-root\t{resolved_module_root}\n"
        f"papyrus-root-guard\tmodule-file\t{module_file}\n"
        f"papyrus-root-guard\tnext\t{recovery}\n"
        "papyrus-root-guard\toverride\tpass --allow-cross-root or set PAPYRUS_ALLOW_CROSS_ROOT=1"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    allow_cross_root, args = _consume_cross_root_override(args)
    if not args:
        _usage()
        return 1
    try:
        if not allow_cross_root:
            _enforce_root_guard(args)
        group = args[0]
        if group == "assignments":
            command, flags = _require_command(group, args)
            return _map_assignments(command, flags)
        if group == "references":
            command, flags = _require_command(group, args)
            return _map_references(command, flags)
        if group == "analysis":
            command, flags = _require_command(group, args)
            return _map_analysis(command, flags)
        if group in {"editions", "auth", "batch"}:
            command, flags = _require_command(group, args)
            _delegate_content(group, command, flags)
            return 0
        if group == "reporting":
            command, flags = _require_command(group, args)
            _map_reporting(command, flags)
            return 0
        if group == "research":
            command, flags = _require_command(group, args)
            _map_research(command, flags)
            return 0
        if group == "sections":
            command, flags = _require_command(group, args)
            _map_sections(command, flags)
            return 0
        if group == "procedures":
            command, flags = _require_command(group, args)
            return _map_procedures(command, flags)
        if group == "knowledge":
            command, flags = _require_command(group, args)
            return _map_knowledge(command, flags)
        if group == "help":
            _usage()
            return 0
        if group == "ops":
            command, flags = _require_command(group, args)
            return _map_ops(command, flags)
        if group == "videos":
            command, flags = _require_command(group, args)
            _delegate_content("videos", command, flags)
            return 0
        raise ValueError(f"Unsupported papyrus group: {group}")
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
