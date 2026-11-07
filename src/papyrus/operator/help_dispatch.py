"""`papyrus ... --help` / `-h`, answered before anything else runs.

`route_tree()` is every command the `papyrus` entry point routes, as nested dicts (a leaf is `{}`). `answer_help` walks the
words before the help flag down that tree and prints the usage of the node it ends on: a group lists its commands, a command
prints its usage. It runs ahead of sign-in, the root guard, backend selection and every command, so no command (and no write,
because mutation commands write by default) is reached by `--help`. A word the tree does not know is an unsupported command,
printed with its group's usage.

New commands join the tree from the same tables that route them, so they inherit this for free.
"""
from __future__ import annotations

import sys

from papyrus_content.command_help import HELP_FLAGS, ported_commands, wants_help

Tree = dict[str, "Tree"]

CONTENT_GROUPS = ("stories", "editions", "batch", "messages", "reader", "proposals", "ideas", "cyclotron", "items", "home-page",
                  "automations", "reviews", "videos")
LEAF_GROUPS = ("doctor", "login", "logout", "whoami", "auth", "help")
REFERENCE_EXTRAS = ("list", "show", "register", "search", "capture-transcripts", "repair-titles", "capture-thumbnails",
                    "curate-recent", "summaries", "summarize", "summarize-batch", "summary-cleanup-legacy", "quality", "title-subtitle")
ASSIGNMENT_EXTRAS = ("list", "run-story-cycle", "story-cycle-output", "build-assignment-agent-context")
KNOWLEDGE_EXTRAS = ("query", "vector-index", "signals", "publish-run", "snapshot", "archive", "topic-config", "extract-entities",
                    "cloud-run", "runs")
KNOWLEDGE_PREFIXED = ("entities", "clusters", "relations", "run", "wiki")


def _leaves(names) -> Tree:
    return {name: {} for name in sorted(names)}


def route_tree() -> Tree:
    from papyrus.operator.group_commands import PROCEDURES_COMMANDS, REPORTING_COMMANDS, RESEARCH_COMMANDS, SECTIONS_COMMANDS
    from papyrus_content.images.cli import route_tree as images_route_tree

    knowledge_names = ported_commands("knowledge")
    knowledge: Tree = _leaves(KNOWLEDGE_EXTRAS)
    knowledge["ontology"] = _leaves(ported_commands("ontology"))
    knowledge["topics"] = _leaves(ported_commands("categories"))
    knowledge["concepts"] = _leaves(ported_commands("relations"))
    knowledge["corpus"] = {"export": {}}
    for prefix in KNOWLEDGE_PREFIXED:
        knowledge[prefix] = _leaves(name[len(prefix) + 1:] for name in knowledge_names if name.startswith(prefix + "-"))
    tree: Tree = {
        "references": _leaves({*REFERENCE_EXTRAS, *ported_commands("references")}),
        "assignments": _leaves({*ASSIGNMENT_EXTRAS, *ported_commands("assignments")}),
        "knowledge": knowledge,
        "reporting": _leaves(REPORTING_COMMANDS),
        "research": _leaves(RESEARCH_COMMANDS),
        "sections": _leaves(SECTIONS_COMMANDS),
        "procedures": {**_leaves(PROCEDURES_COMMANDS), "policy": _leaves(ported_commands("policy"))},
        "analysis": {**_leaves(ported_commands("analysis")), "test": _leaves(ported_commands("test"))},
        "ops": {
            "content": _leaves(ported_commands("content")),
            "corpora": _leaves(ported_commands("corpora")),
            "categories": _leaves(ported_commands("categories")),
            "relations": _leaves(ported_commands("relations")),
            "messages": _leaves(ported_commands("messages")),
            "site": {"copy": {}},
        },
        "site": {"google-secrets": {}},
        "publication": {"init": {}},
        "editorial": _leaves({*ported_commands("editorial"), "context"}),
        "monitors": {},
        "images": images_route_tree(),
    }
    for group in CONTENT_GROUPS:
        tree[group] = _leaves(ported_commands(group))
    for group in LEAF_GROUPS:
        tree[group] = {}
    return tree


def all_routes() -> list[list[str]]:
    """Every route, as the list of words that names it (groups and nested groups included)."""
    routes: list[list[str]] = []

    def visit(node: Tree, prefix: list[str]) -> None:
        for name, child in node.items():
            routes.append([*prefix, name])
            visit(child, [*prefix, name])

    visit(route_tree(), [])
    return routes


def _words_before_help(args: list[str]) -> list[str]:
    words: list[str] = []
    for token in args:
        if token in HELP_FLAGS or token.startswith("-"):
            break
        words.append(token)
    return words


def _resolve(words: list[str]) -> tuple[list[str], str | None]:
    """The words that name a node, and the first unknown word under a group (None when every word resolved)."""
    tree = route_tree()
    node = tree
    resolved: list[str] = []
    for word in words:
        if resolved and not node:
            break  # a command's own positional arguments
        if word not in node:
            return resolved, word
        node = node[word]
        resolved.append(word)
    return resolved, None


def _group_text(path: list[str], node: Tree) -> str:
    from papyrus.operator.group_commands import COMMAND_USAGE

    lines = [f"Usage: papyrus {' '.join(path)} <command> [options]", "", "Commands:"]
    for name in node:
        usage = COMMAND_USAGE.get((path[-1], name))
        lines.append(f"  {name}" + (f"  {usage}" if usage else ""))
    return "\n".join(lines)


def _top_level_line(group: str) -> str:
    from papyrus.operator.help_text import TOP_LEVEL_HELP

    for line in TOP_LEVEL_HELP.splitlines():
        if line.split(None, 1)[:1] == [group]:
            return line.strip()
    return ""


def _command_text(path: list[str]) -> str:
    from papyrus.operator.group_commands import COMMAND_USAGE

    if path[0] == "images":
        from papyrus_content.images.cli import usage_for

        found = usage_for(path[1:])
        if found:
            return found

    lines = [f"Usage: papyrus {' '.join(path)} [options]"]
    usage = COMMAND_USAGE.get((path[-2], path[-1])) if len(path) > 1 else None
    if usage:
        lines.append(f"  {usage}")
    elif len(path) == 1 and _top_level_line(path[0]):
        lines.append(f"  {_top_level_line(path[0])}")
    return "\n".join(lines)


def _print_parser_command_help(path: list[str]) -> bool:
    """The argparse usage of `references list` and friends, where the group has a parser."""
    from papyrus.operator import help_text

    builders = {"references": help_text.build_references_parser, "assignments": help_text.build_assignments_parser,
                "knowledge": help_text.build_knowledge_parser, "editorial": help_text.build_editorial_parser}
    builder = builders.get(path[0])
    if builder is None or len(path) != 2:
        return False
    parser = builder()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if choices and path[1] in choices:
            choices[path[1]].print_help()
            return True
    return False


def answer_help(args: list[str]) -> int | None:
    """Print usage and return the exit status when `args` asks for help; None when it does not."""
    if not wants_help(args):
        return None
    from papyrus.operator.help_text import TOP_LEVEL_HELP, print_group_help

    words = _words_before_help(args)
    if not words:
        print(TOP_LEVEL_HELP)
        return 0
    if words[0] == "monitors":
        # argparse owns monitors: its --help prints and exits before any command runs.
        from papyrus_content.monitoring_commands import command as monitor_command

        try:
            return monitor_command([*words[1:], "--help"])
        except SystemExit as stop:
            return int(stop.code or 0)
    resolved, unknown = _resolve(words)
    if unknown is not None:
        if resolved:
            node = route_tree()
            for word in resolved:
                node = node[word]
            print(_group_text(resolved, node), file=sys.stderr)
            raise ValueError(f"Unsupported papyrus command: {' '.join([*resolved, unknown])}")
        print(TOP_LEVEL_HELP, file=sys.stderr)
        raise ValueError(f"Unsupported papyrus group: {unknown}")  # no site hint: that reads the sign-in registry
    node = route_tree()
    for word in resolved:
        node = node[word]
    if node:
        if len(resolved) == 1:
            print_group_help(resolved[0])
        else:
            print(_group_text(resolved, node))
        return 0
    if not _print_parser_command_help(resolved):
        print(_command_text(resolved))
    return 0
