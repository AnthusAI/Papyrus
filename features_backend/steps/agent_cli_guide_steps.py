"""The agent CLI guide and the usage `--help` prints (features_backend/agent-cli-guide.feature). No network, login or AWS."""
from __future__ import annotations

import io
import os
import re
import shlex
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus import cli  # noqa: E402


def _run(context, line: str) -> None:
    arguments = shlex.split(line)[1:]
    out, err = io.StringIO(), io.StringIO()
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("PAPYRUS_", "AWS_"))}
    with patch.dict(os.environ, environment, clear=True), redirect_stdout(out), redirect_stderr(err):
        try:
            context.status = cli.main(arguments)
        except SystemExit as stop:
            context.status = int(stop.code or 0)
    context.guide_output, context.guide_error = out.getvalue(), err.getvalue()


@when('an agent runs "{line}"')
def agent_runs(context, line):
    _run(context, line)


@when('an agent runs "{line}" with no site and no arguments')
def agent_runs_bare(context, line):
    _run(context, line)


@then("the command succeeded")
def exit_zero(context):
    assert context.status == 0, (context.status, context.guide_error)


@then("the command failed")
def exit_not_zero(context):
    assert context.status != 0, context.guide_output


@then('the printed text names the tasks {names}')
def output_names_tasks(context, names):
    for name in re.findall(r'"([^"]+)"', names):
        assert re.search(rf"^\s+{re.escape(name)}\s", context.guide_output, re.MULTILINE), (name, context.guide_output)


@then('the printed text starts with "{text}"')
def output_starts_with(context, text):
    assert context.guide_output.startswith(text), context.guide_output[:200]


@then('the printed text contains "{text}"')
def output_contains(context, text):
    assert text in context.guide_output, context.guide_output


@then('the printed text has a line for "{name}" followed by its description')
def output_has_line(context, name):
    assert re.search(rf"^\s+{re.escape(name)}\s+\S", context.guide_output, re.MULTILINE), context.guide_output


@then('the printed text says "{name}" is for the local pod only')
def output_local_pod(context, name):
    assert name in context.guide_output and "local pod only" in context.guide_output, context.guide_output


@then('the printed error has the usage of "{command}" before the error')
def usage_before_error(context, command):
    assert context.guide_error.startswith(f"Usage: {command}"), context.guide_error
    assert "Lane:" in context.guide_error and "Writes:" in context.guide_error


@then('the printed error contains "{text}"')
def error_contains(context, text):
    assert text in context.guide_error, context.guide_error


@when("the guide's fenced commands are checked against the CLI")
def check_guide(context):
    import test_agent_cli_guide as guide

    context.guide_module = guide


@then("every command is a route of the CLI")
def every_command_is_a_route(context):
    guide = context.guide_module
    for number, _pending, line in guide.COMMANDS:
        words = []
        for token in shlex.split(line)[1:]:
            if token.startswith("-"):
                break
            words.append(token)
        assert not words or guide.resolve(words) is not None, (number, line)


@then("every flag it uses appears in that command's help")
def every_flag_is_in_help(context):
    guide = context.guide_module
    for number, pending, line in guide.COMMANDS:
        guide.test_every_fenced_command_exists_with_the_flags_it_uses(number, pending, line)


@then("every recipe for an unmerged pull request is marked pending")
def pending_marked(context):
    context.guide_module.test_pending_marks_and_the_pending_list_agree()


@when('every route is asked for "--help"')
def every_route_help(context):
    import test_agent_cli_guide as guide

    context.guide_module = guide
    context.help_results = [(route, *guide.run_help(route)) for route in guide.all_routes()]


@then('each prints usage that begins with "Usage"')
def each_prints_usage(context):
    for route, status, out, _err in context.help_results:
        assert status == 0 and out.lstrip().lower().startswith("usage"), route


@then("each command says its lane and whether it writes")
def each_says_lane(context):
    guide = context.guide_module
    for route, _status, out, _err in context.help_results:
        node = guide.route_tree()
        for word in route:
            node = node[word]
        if not node and route[0] not in {"images", "monitors"}:
            assert "Lane:" in out and "Writes:" in out, route
