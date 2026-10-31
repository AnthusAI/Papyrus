from pathlib import Path
import subprocess

from behave import given, then, when

ROOT = Path(__file__).resolve().parents[2]

CASES = {
    ("separate", "console"): "the console origin is accepted when configured",
    ("separate", "foreign"): "a foreign origin is still refused",
    ("same", "console"): "without a console origin only the site origin is accepted",
}


def _run(context, action):
    name = CASES[(context.console_origin_arrangement, action)]
    context.origin_check_result = subprocess.run(
        ["node", "--import", "tsx", "--test", "--test-name-pattern", name, "scripts/test-allowed-origins.ts"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


@when('a request arrives from the console origin')
def from_console_origin(context):
    _run(context, "console")


@when('a request arrives from a foreign origin')
def from_foreign_origin(context):
    _run(context, "foreign")


@when("a request arrives from the console host's would-be origin")
def from_would_be_console_origin(context):
    _run(context, "console")


@then('the same-origin check accepts it')
@then('the same-origin check refuses it')
def check_passed(context):
    result = context.origin_check_result
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# pass 1" in result.stdout, result.stdout
