"""Every `papyrus <group>` prints its own subcommands for `--help` and when given no command."""
import io
from contextlib import redirect_stdout

import pytest

from papyrus import cli
from papyrus.operator import help_text
from papyrus.operator.group_commands import group_subcommands

PARSER_GROUPS = {
    "references": help_text.build_references_parser,
    "assignments": help_text.build_assignments_parser,
    "knowledge": help_text.build_knowledge_parser,
    "editorial": help_text.build_editorial_parser,
}
GENERIC_GROUPS = ["reporting", "research", "sections", "procedures", "stories", "editions", "batch", "videos", "analysis", "ops", "publication"]


def run(args):
    out = io.StringIO()
    with redirect_stdout(out):
        assert cli.main(args) == 0
    return out.getvalue()


def subcommands(group):
    if group in PARSER_GROUPS:
        parser = PARSER_GROUPS[group]()
        return sorted(next(a for a in parser._actions if a.dest == "command").choices)
    return group_subcommands(group)


@pytest.mark.parametrize("group", [*PARSER_GROUPS, *GENERIC_GROUPS])
@pytest.mark.parametrize("form", ["--help", None])
def test_group_help_lists_its_subcommands(group, form):
    text = run([group, form] if form else [group])
    assert f"papyrus {group}" in text
    names = subcommands(group)
    assert names, group
    for name in names:
        assert name in text, (group, name)


def test_group_help_is_not_the_top_level_help():
    for group in GENERIC_GROUPS:
        assert "Operator groups:" not in run([group, "--help"])


def test_stories_create_is_a_command_with_its_flags():
    text = run(["stories", "--help"])
    assert "create" in text and "--stage" in text and "--with-assignment" in text
