from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

_ALLOW_CROSS_ROOT_FLAG = "--allow-cross-root"
_TRUTHY = {"1", "true", "yes", "on"}


def _bootstrap_import_path() -> None:
    src_root = Path(__file__).resolve().parents[1]
    repo_root = src_root.parent
    for candidate in (str(src_root), str(repo_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)


_bootstrap_import_path()

from papyrus_content import cli as content_cli  # noqa: E402
from papyrus_content.env import PAPYRUS_ROOT  # noqa: E402
from papyrus_content.operator_errors import (  # noqa: E402
    OperatorError,
    run_with_operator_error_handling,
)
from papyrus_newsroom import cli as newsroom_cli  # noqa: E402
from papyrus.operator.group_commands import REPORTING_COMMANDS, RESEARCH_COMMANDS, SECTIONS_COMMANDS  # noqa: E402
from papyrus.operator.help_text import TOP_LEVEL_HELP, print_group_help  # noqa: E402
from papyrus.operator.runtime import (  # noqa: E402
    dispatch_operator_command,
    is_operator_command,
    print_top_level_help,
)


def _usage() -> None:
    print_top_level_help()


def _delegate_content(group: str, command: str, flags: list[str]) -> None:
    content_cli.load_dotenv()
    content_cli.dispatch(group, command, flags)


def _delegate_newsroom(argv: list[str]) -> int:
    return newsroom_cli.main(argv)


def _operator_groups_with_help() -> set[str]:
    return {"references", "assignments", "knowledge"}


def _consume_global_flags(args: list[str]) -> tuple[list[str], list[str]]:
    if not args:
        return [], []
    if args[0] in {"--help", "-h"} and len(args) == 1:
        return ["--help"], []
    if args[0] == "--version":
        return ["--version"], []
    remaining = list(args)
    passthrough: list[str] = []
    if len(args) >= 3 and args[2] == "--backend":
        if len(args) < 4:
            raise OperatorError("--backend requires a value: local or cloud.")
        passthrough.extend(["--backend", args[3]])
        remaining = [args[0], args[1], *args[4:]]
    return remaining, passthrough


def _map_reporting(command: str, flags: list[str]) -> None:
    mapped = REPORTING_COMMANDS.get(command)
    if not mapped:
        raise ValueError(f"Unsupported papyrus reporting command: {command}")
    _delegate_content("assignments", mapped, flags)


def _map_research(command: str, flags: list[str]) -> None:
    mapped = RESEARCH_COMMANDS.get(command)
    if not mapped:
        raise ValueError(f"Unsupported papyrus research command: {command}")
    _delegate_content("assignments", mapped, flags)


def _map_sections(command: str, flags: list[str]) -> None:
    mapped = SECTIONS_COMMANDS.get(command)
    if not mapped:
        raise ValueError(f"Unsupported papyrus sections command: {command}")
    _delegate_content("newsroom", mapped, flags)


def _map_procedures(command: str, flags: list[str]) -> int:
    if command == "seed-required":
        _delegate_content("newsroom", "seed-required-procedures", flags)
        return 0
    if command == "register":
        _delegate_content("newsroom", "register-procedure", flags)
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
    if command == "list":
        return dispatch_operator_command("assignments", "list", flags)
    if command == "run-story-cycle":
        return _delegate_newsroom(["assignments", "run-story-cycle", *flags])
    if command == "story-cycle-output":
        return _delegate_newsroom(["assignments", "story-cycle-output", *flags])
    if command == "build-assignment-agent-context":
        return _delegate_newsroom(["build-assignment-agent-context", *flags])
    _delegate_content("assignments", command, flags)
    return 0


def _map_references(command: str, flags: list[str]) -> int:
    if command in {"list", "show", "register"}:
        return dispatch_operator_command("references", command, flags)
    newsroom_reference_commands = {
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
    if command in {"publish-run", "snapshot"}:
        _delegate_content("knowledge", command, flags)
        return 0
    if command == "entities":
        if not flags or flags[0].startswith("-"):
            raise ValueError("papyrus knowledge entities requires <command>: list, accept, reject, rename or describe.")
        _delegate_content("knowledge", f"entities-{flags[0]}", flags[1:])
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
    return run_with_operator_error_handling(lambda: _run_with_arguments(argv))


def _run_with_arguments(argv: list[str] | None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    allow_cross_root, args = _consume_cross_root_override(args)
    args, global_flags = _consume_global_flags(args)

    if not args or args == ["--help"] or (len(args) == 1 and args[0] in {"--help", "-h"}):
        _usage()
        return 0
    if args[0] == "--version":
        from papyrus import __version__

        print(__version__)
        return 0

    if args[0] in {"login", "logout", "whoami", "auth"}:
        from papyrus_content.cli_user_auth import command as auth_command
        return auth_command(args)

    if not allow_cross_root:
        _enforce_root_guard(args)
    group = args[0]
    if group == "monitors":
        from papyrus_content.monitoring_commands import command as monitor_command
        return monitor_command(args[1:])
    command = args[1] if len(args) > 1 else None
    flags = [*global_flags, *(args[2:] if len(args) > 2 else [])]

    if command in {"--help", "-h"}:
        print_group_help(group)
        return 0

    if command is None and group in _operator_groups_with_help():
        print_group_help(group)
        return 0

    if group == "assignments":
        if command is None:
            print_group_help(group)
            return 0
        return _map_assignments(command, flags)
    if group == "stories":
        if command is None:
            print_group_help(group)
            return 0
        _delegate_content("stories", command, flags)
        return 0
    if group == "references":
        if command is None:
            print_group_help(group)
            return 0
        return _map_references(command, flags)
    if group == "analysis":
        if command is None:
            print_group_help(group)
            return 0
        return _map_analysis(command, flags)
    if group in {"editions", "batch", "messages", "reader"}:
        if command is None:
            print_group_help(group)
            return 0
        _delegate_content(group, command, flags)
        return 0
    if group == "reporting":
        if command is None:
            print_group_help(group)
            return 0
        _map_reporting(command, flags)
        return 0
    if group == "research":
        if command is None:
            print_group_help(group)
            return 0
        _map_research(command, flags)
        return 0
    if group == "sections":
        if command is None:
            print_group_help(group)
            return 0
        _map_sections(command, flags)
        return 0
    if group == "procedures":
        if command is None:
            print_group_help(group)
            return 0
        return _map_procedures(command, flags)
    if group == "knowledge":
        if command is None:
            print_group_help(group)
            return 0
        return _map_knowledge(command, flags)
    if group == "site":
        if command is None:
            print_group_help(group)
            return 0
        from papyrus.operator.site_google_secrets import site_command

        return site_command(command, flags)
    if group == "help":
        _usage()
        return 0
    if group == "ops":
        if command is None:
            print_group_help(group)
            return 0
        return _map_ops(command, flags)
    if group == "videos":
        if command is None:
            print_group_help(group)
            return 0
        _delegate_content("videos", command, flags)
        return 0
    if group == "publication":
        if command is None:
            print_group_help(group)
            return 0
        if command != "init":
            raise ValueError("papyrus publication requires <command>: init --key <key> --name <name>.")
        from papyrus_content.publication import publication_init_command

        publication_init_command(flags)
        return 0
    if group == "editorial" and command == "context":
        from papyrus_content.editorial_context import editorial_context_command

        editorial_context_command(flags)
        return 0
    if group == "editorial":
        if command is None:
            print_group_help(group)
            return 0
        _delegate_content("editorial", command, flags)
        return 0
    raise ValueError(f"Unsupported papyrus group: {group}")


if __name__ == "__main__":
    raise SystemExit(main())
