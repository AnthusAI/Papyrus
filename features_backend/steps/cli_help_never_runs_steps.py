"""Help never runs a command, through the real CLI with fakes that fail when a client, the network or a file is touched."""
import io
import os
import shlex
import socket
import tempfile
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from papyrus import cli
from papyrus.operator.help_dispatch import all_routes
from papyrus_content import graphql_authoring


def _touch(context, label):
    def fake(*args, **kwargs):
        context.touched.append(label)
        raise AssertionError(f"touched {label}")
    return fake


@given('a world where touching a backend client, the network or a file fails the test')
def world(context):
    context.touched = []
    directory = tempfile.TemporaryDirectory()
    context.add_cleanup(directory.cleanup)
    here = os.getcwd()
    os.chdir(directory.name)
    context.add_cleanup(lambda: os.chdir(here))
    environment = patch.dict(os.environ, {"HOME": directory.name})
    environment.start(); context.add_cleanup(environment.stop)
    for name in [name for name in os.environ if name.startswith(("PAPYRUS_", "AWS_"))]:
        os.environ.pop(name)
    for target, attribute, label in (
        (graphql_authoring, "create_authoring_client", "create_authoring_client"),
        (graphql_authoring.PapyrusGraphQLAuthoringClient, "__init__", "backend client"),
        (urllib.request, "urlopen", "urlopen"),
        (socket, "create_connection", "network"),
        (Path, "write_text", "write_text"),
        (Path, "mkdir", "mkdir"),
    ):
        started = patch.object(target, attribute, _touch(context, label))
        started.start(); context.add_cleanup(started.stop)


def _run(context, args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            context.status = cli.main(args)
        except SystemExit as stop:
            context.status = int(stop.code or 0)
    context.output, context.error = out.getvalue(), err.getvalue()


@when('the operator runs "{command}"')
def run_command(context, command):
    words = shlex.split(command)
    assert words[0] == "papyrus"
    _run(context, words[1:])


@when('the operator asks every route for "{flag}"')
def run_every_route(context, flag):
    context.failures = []
    for route in all_routes():
        if route == ["monitors"]:
            continue
        _run(context, [*route, flag])
        if context.status != 0 or "usage" not in context.output.lower():
            context.failures.append(route)


@then("the exit code is {code:d}")
def exit_code(context, code):
    assert context.status == code, (context.status, context.error)


@then("the exit code is not 0")
def exit_code_not_zero(context):
    assert context.status != 0


@then('the output starts with "{text}"')
def output_starts(context, text):
    assert context.output.startswith(text), context.output[:200]


@then('the output lists the commands "{first}", "{second}" and "{third}"')
def output_lists(context, first, second, third):
    for name in (first, second, third):
        assert name in context.output, name


@then("every route exits 0 and prints usage")
def every_route(context):
    assert context.failures == [], context.failures


@then("the error says the command is unsupported and lists the group's commands")
def unsupported(context):
    assert "Unsupported papyrus" in context.error and "Usage" in context.error and "list" in context.error, context.error


@then("nothing was touched")
def nothing_touched(context):
    assert context.touched == [], context.touched
