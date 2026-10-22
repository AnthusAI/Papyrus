from __future__ import annotations

import pytest

from papyrus import cli
from papyrus.operator import help_text


@pytest.mark.parametrize(
    ("command", "flags", "routed"),
    [
        ("entities", ["accept", "--key", "k", "--actor", "ai"], "entities-accept"),
        ("clusters", ["accept", "--uid", "u", "--actor", "ai"], "clusters-accept"),
        ("clusters", ["list"], "clusters-list"),
        ("relations", ["reject", "--id", "r", "--actor", "human"], "relations-reject"),
        ("publish-run", ["--identity", "f"], "publish-run"),
    ],
)
def test_knowledge_review_groups_route_to_the_content_commands(monkeypatch, command, flags, routed):
    seen = []
    monkeypatch.setattr(cli, "_delegate_content", lambda group, name, rest: seen.append((group, name, rest)))
    assert cli._map_knowledge(command, flags) == 0
    assert seen[0][:2] == ("knowledge", routed)


@pytest.mark.parametrize("command", ["entities", "clusters", "relations"])
def test_a_review_group_without_a_command_says_what_it_takes(command):
    with pytest.raises(ValueError, match=f"papyrus knowledge {command} requires <command>"):
        cli._map_knowledge(command, [])


def test_the_knowledge_help_lists_the_review_groups_and_the_actor_rule():
    text = help_text.build_knowledge_parser().format_help()
    for group in ("entities", "clusters", "relations"):
        assert group in text
    assert "--actor ai|human required" in text
