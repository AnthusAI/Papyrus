"""Amplify cost-check behaviour through the real papyrus-infra CLI and a fake aws command that fails on any write."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / 'packages' / 'papyrus' / 'bin' / 'papyrus-infra.mjs'
FIXTURES = REPO_ROOT / 'features_backend' / 'fixtures' / 'amplify-cost'
THROUGH_OCTOBER = ['cost', 'amplify', '--months', '3', '--through', '2026-10']


def _run(context, scenario_name, arguments):
    bin_directory = tempfile.TemporaryDirectory()
    context.add_cleanup(bin_directory.cleanup)
    fake = Path(bin_directory.name) / 'aws'
    fake.write_text((FIXTURES / 'fake-aws.mjs').read_text())
    fake.chmod(0o755)
    environment = dict(os.environ, PATH=f'{bin_directory.name}:{os.environ["PATH"]}',
                       FAKE_AWS_SCENARIO=str(FIXTURES / f'{scenario_name}.json'))
    result = subprocess.run(['node', str(CLI), *arguments], capture_output=True, text=True, env=environment, timeout=60)
    assert result.returncode == 0, result.stderr
    return result


def _limit(result):
    return re.search(r'"Amount": "([\d.]+)"', result.stdout).group(1)


@given('an account whose Amplify bill has risen for four months')
def step_rising(context):
    context.rising = 'rising-history'


@given("a second account whose Amplify bill has been flat for four months")
def step_flat(context):
    context.flat = 'flat-history'


@when('the operator checks the Amplify cost for the three months through October')
def step_check(context):
    context.result = _run(context, context.rising, THROUGH_OCTOBER)


@when('the operator plans the budget for each account')
def step_plan_each(context):
    context.rising_result = _run(context, context.rising, [*THROUGH_OCTOBER, '--no-apps', '--plan-budget'])
    context.flat_result = _run(context, context.flat, [*THROUGH_OCTOBER, '--no-apps', '--plan-budget'])


@when('the operator plans the budget for the account')
def step_plan(context):
    context.result = _run(context, context.rising, [*THROUGH_OCTOBER, '--no-apps', '--plan-budget'])


@then("October's build duration is listed in minutes with its cost")
def step_build_duration(context):
    assert re.search(r'2026-10\s+111111111111\s+USE1-BuildDuration\s+7,076\.8\s+Minutes\s+70\.77', context.result.stdout), context.result.stdout


@then("October's total cost is listed")
def step_total(context):
    assert re.search(r'2026-10\s+total\s+70\.97', context.result.stdout), context.result.stdout


@then('each app that built in October is listed with its build minutes and build count')
def step_apps(context):
    assert re.search(r'example-cms\s+21 min\s+2 builds', context.result.stdout), context.result.stdout


@then('an app that did not build in October is not listed')
def step_quiet_app(context):
    assert 'quiet-site' not in context.result.stdout


@then('the two thresholds differ')
def step_differ(context):
    assert _limit(context.rising_result) != _limit(context.flat_result)


@then("the flat account's threshold equals its monthly cost")
def step_flat_equals_cost(context):
    assert _limit(context.flat_result) == '20.20', _limit(context.flat_result)


@then('the budget commands are printed for review')
def step_printed(context):
    assert 'Not run by this command' in context.result.stdout
    assert 'aws budgets create-budget --account-id 111111111111' in context.result.stdout


@then('the commands name the alert address by its parameter and never print an address')
def step_no_address(context):
    assert '/papyrus/cost/amplify-alert-email' in context.result.stdout
    assert '@' not in context.result.stdout
