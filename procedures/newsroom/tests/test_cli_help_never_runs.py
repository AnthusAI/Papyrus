"""`--help` and `-h` on every command, subcommand and group print usage and exit 0, and touch nothing.

Mutation commands write by default, so a `--help` that reached one would perform the write. These tests walk every route the
`papyrus` entry point knows and run it with a help flag inside a world that fails the moment anything is touched: no backend
client, no sign-in, no network, no subprocess, no file written.
"""
import builtins
import io
import os
import socket
import subprocess
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from papyrus import cli
from papyrus.operator.help_dispatch import all_routes, route_tree
from papyrus_content import cli as content_cli

HELP_FLAGS = ["--help", "-h"]


class Touched(BaseException):
    """Raised by a fake. A BaseException, so no `except Exception` in a command can swallow it."""


@pytest.fixture
def forbidden_world(monkeypatch, tmp_path):
    touched: list[str] = []

    def forbid(label):
        def fake(*args, **kwargs):
            touched.append(label)
            raise Touched(label)
        return fake

    from papyrus_content import graphql_authoring, monitoring_router, monitoring_view_cli
    from papyrus_content.knowledge_snapshot import commands as knowledge_commands

    monkeypatch.setattr(graphql_authoring, "create_authoring_client", forbid("create_authoring_client"))
    monkeypatch.setattr(graphql_authoring.PapyrusGraphQLAuthoringClient, "__init__", forbid("PapyrusGraphQLAuthoringClient"))
    monkeypatch.setattr(monitoring_router, "make_appsync_client", forbid("make_appsync_client"))
    monkeypatch.setattr(monitoring_view_cli, "_client", forbid("monitoring view client"))
    monkeypatch.setattr(knowledge_commands, "new_client", forbid("knowledge new_client"))
    monkeypatch.setattr(knowledge_commands, "authoring_client", forbid("knowledge authoring_client"))
    try:
        import boto3
    except ImportError:
        boto3 = None
    if boto3 is not None:
        for name in ("client", "resource"):
            monkeypatch.setattr(boto3, name, forbid(f"boto3.{name}"))
        monkeypatch.setattr(boto3, "Session", forbid("boto3.Session"))
    monkeypatch.setattr(urllib.request, "urlopen", forbid("urlopen"))
    monkeypatch.setattr(socket, "create_connection", forbid("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", forbid("socket.getaddrinfo"))
    monkeypatch.setattr(socket.socket, "connect", forbid("socket.connect"))
    monkeypatch.setattr(subprocess, "Popen", forbid("subprocess.Popen"))
    monkeypatch.setattr(os, "system", forbid("os.system"))

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and any(flag in mode for flag in "wax+"):
            touched.append(f"open({file!r}, {mode!r})")
            raise Touched(f"write {file}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "write_text", forbid("Path.write_text"))
    monkeypatch.setattr(Path, "write_bytes", forbid("Path.write_bytes"))
    monkeypatch.setattr(Path, "mkdir", forbid("Path.mkdir"))

    for name in list(os.environ):
        if name.startswith(("PAPYRUS_", "AWS_", "AMPLIFY_")):
            monkeypatch.delenv(name)
    # `--site` sets PAPYRUS_SITE directly in os.environ; registering it here makes teardown remove it, so it cannot leak into other tests.
    monkeypatch.setenv("PAPYRUS_SITE", "unused.example")
    monkeypatch.delenv("PAPYRUS_SITE")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return touched


def run(entry, args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = entry(args)
    return status, out.getvalue(), err.getvalue()


def test_the_tree_knows_the_groups_and_nested_commands():
    routes = {" ".join(route) for route in all_routes()}
    assert {"references list", "knowledge entities accept", "ops content list", "ops content publish", "stories create",
            "procedures policy", "analysis test", "site google-secrets", "editorial check"} <= routes


@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_every_route_answers_help_with_usage_and_touches_nothing(forbidden_world, flag):
    failures = []
    for route in all_routes():
        if route == ["monitors"]:
            continue
        status, out, err = run(cli.main, [*route, flag])
        if status != 0 or "usage" not in out.lower():
            failures.append((route, status, out[:80], err[:80]))
    assert not failures
    assert forbidden_world == []


@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_help_after_other_arguments_is_still_help(forbidden_world, flag):
    for args in (
        ["ops", "content", "list", "articles", flag],
        ["ops", "content", "list", "articles", "--limit", "5", flag],
        ["references", "backfill-feed-keys", "--site", "a.anth.us", flag],
        ["references", "list", "--backend", "cloud", flag],
        ["--site", "a.anth.us", "stories", "move", "--story", "x", "--stage", "idea", flag],
    ):
        status, out, _ = run(cli.main, args)
        assert status == 0, args
        assert "papyrus" in out.lower()
    assert forbidden_world == []


def test_the_reported_cases(forbidden_world):
    status, out, _ = run(cli.main, ["ops", "content", "list", "articles", "--help"])
    assert status == 0 and out.startswith("Usage: papyrus ops content list")
    status, out, _ = run(cli.main, ["ops", "content", "--help"])
    assert status == 0 and "Commands:" in out and "list" in out and "publish" in out
    assert forbidden_world == []


def test_a_group_lists_its_commands(forbidden_world):
    for group, expected in (("ops", ["content", "corpora", "site"]), ("knowledge", ["entities", "wiki", "query"]),
                            ("references", ["list", "search", "approve"])):
        status, out, _ = run(cli.main, [group, "--help"])
        assert status == 0
        for name in expected:
            assert name in out, (group, name)


def test_monitors_answer_help_without_running(forbidden_world):
    for args in (["monitors", "--help"], ["monitors", "status", "--help"], ["monitors", "run", "-h"]):
        status, out, _ = run(cli.main, args)
        assert status == 0 and "usage" in out.lower()
    assert forbidden_world == []


def test_help_needs_no_checkout_root(forbidden_world):
    status, out, _ = run(cli.main, ["stories", "list", "--help"])
    assert status == 0 and "Usage" in out


@pytest.mark.parametrize("args", [["references", "bogus", "--help"], ["ops", "content", "bogus", "-h"], ["nonsense", "--help"],
                                  ["ops", "nonsense", "--help"]])
def test_unknown_commands_still_say_so_with_the_group_usage(forbidden_world, args):
    status, out, err = run(cli.main, args)
    assert status != 0
    assert "Unsupported papyrus" in err
    assert ("Usage" in err) and (args[0] != "references" or "list" in err)
    assert forbidden_world == []


@pytest.mark.parametrize("flag", HELP_FLAGS)
def test_the_content_dispatcher_answers_help_for_every_ported_route(forbidden_world, flag):
    for route in sorted(content_cli.PORTED_COMMANDS):
        group, command = route.split(":", 1)
        status, out, _ = run(content_cli.main, [group, command, flag])
        assert status == 0 and out.startswith(f"Usage: papyrus {group} {command}"), route
        content_cli.dispatch(group, command, [flag])
        content_cli.dispatch(group, flag, [])
    assert forbidden_world == []


def test_a_new_command_cannot_be_reached_by_help(forbidden_world, monkeypatch):
    """Even a command nobody taught about help never runs on `--help`: the dispatcher answers first."""
    ran = []
    monkeypatch.setattr(content_cli, "PORTED_COMMANDS", frozenset({*content_cli.PORTED_COMMANDS, "content:brand-new-write"}))
    monkeypatch.setattr(content_cli, "content_list", lambda *a, **k: ran.append("list"))
    for args in (["content", "brand-new-write", "--help"], ["content", "list", "articles", "--help"]):
        status, out, _ = run(content_cli.main, args)
        assert status == 0 and "Usage" in out
    assert ran == [] and forbidden_world == []


def test_without_help_the_command_still_runs(forbidden_world, monkeypatch):
    ran = []
    monkeypatch.setattr(content_cli, "content_list", lambda target, flags: ran.append(target))
    content_cli.dispatch("content", "list", ["articles"])
    assert ran == ["articles"]


def test_the_tree_names_every_ported_route_reachable_through_papyrus():
    tree = route_tree()
    for group in ("stories", "editions", "proposals", "automations", "reviews", "videos", "cyclotron"):
        assert set(tree[group]) == {r.split(":", 1)[1] for r in content_cli.PORTED_COMMANDS if r.startswith(group + ":")}
