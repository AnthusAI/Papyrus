from pathlib import Path
import subprocess

from behave import given, then, when

ROOT = Path(__file__).resolve().parents[2]

CASES = {
    ("separate", "expand"): "callback_urls_include_both_origins",
    ("separate", "plan"): "broker_origin_is_the_console_origin",
    ("separate", "discovery"): "discovery_names_the_console_origin_on_both_hosts",
    ("same", "plan"): "broker_origin_is_the_site_origin_without_a_console_origin",
    ("same", "discovery"): "discovery_is_unchanged_without_a_console_origin",
}


def _run(context, action):
    case = CASES[(context.console_origin_arrangement, action)]
    context.console_origin_result = subprocess.run(
        ["node", "--import", "tsx", "scripts/test-console-origin.ts", case],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def _assert_passed(context):
    result = context.console_origin_result
    assert result.returncode == 0, result.stdout + result.stderr


@given('a site whose public origin and console origin differ')
def separate_console_origin(context):
    context.console_origin_arrangement = "separate"


@given('a site with no console origin')
def no_console_origin(context):
    context.console_origin_arrangement = "same"


@when('the sign-in return URLs are expanded')
def expand_return_urls(context):
    _run(context, "expand")


@when('remote CLI login is planned')
def plan_remote_login(context):
    _run(context, "plan")


@when('the CLI login file is fetched from the console host and from the public host')
@when('the CLI login file is fetched from the public host')
def fetch_login_file(context):
    _run(context, "discovery")


@then('both origins are sign-in return URLs, each with its newsroom path and its root')
@then('the approval page and the callback are on the console origin')
@then('the approval page and the callback are on the site origin')
@then('both hosts return the same file, which names the console origin and its callback')
@then('it names the site origin and its callback')
def case_passed(context):
    _assert_passed(context)
