"""Release and branch rules that keep red changes out (reads the workflow files and the protect-branches script; calls no GitHub API)."""
import json
import subprocess
from pathlib import Path

import yaml
from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / '.github' / 'workflows'
PROTECT_BRANCHES_SCRIPT = REPO_ROOT / 'infra' / 'pipeline' / 'protect-branches.sh'


def _workflow(file_name):
    return yaml.safe_load((WORKFLOWS / file_name).read_text(encoding='utf-8'))


@given('the release workflow')
def release_workflow_loaded(context):
    context.workflow = _workflow('release.yml')


@when('its release job is read')
def release_job_read(context):
    context.release_job = context.workflow['jobs']['release']


@then('it needs the jobs smoke and tests')
def release_needs_smoke_and_tests(context):
    assert set(context.release_job['needs']) == {'smoke', 'tests'}, context.release_job['needs']


@then('the tests job calls the test workflow tests.yml')
def tests_job_calls_test_workflow(context):
    assert context.workflow['jobs']['tests']['uses'] == './.github/workflows/tests.yml'


@given('the test workflow tests.yml')
def test_workflow_loaded(context):
    context.workflow = _workflow('tests.yml')


@when('its concurrency group is read')
def concurrency_group_read(context):
    context.concurrency_group = context.workflow['concurrency']['group']


@then('the group includes the name of the calling workflow')
def group_includes_workflow_name(context):
    assert '${{ github.workflow }}' in context.concurrency_group, context.concurrency_group


@given('the branch ruleset the protect-branches script would create')
def ruleset_from_script(context):
    output = subprocess.run(['bash', str(PROTECT_BRANCHES_SCRIPT), '--dry-run'], capture_output=True, text=True, check=True).stdout
    context.ruleset = json.loads(output)


@when('its rules are read')
def ruleset_rules_read(context):
    context.rules_by_type = {rule['type']: rule.get('parameters', {}) for rule in context.ruleset['rules']}


@then('main and develop are covered')
def ruleset_covers_both_branches(context):
    assert context.ruleset['conditions']['ref_name']['include'] == ['refs/heads/main', 'refs/heads/develop']
    assert context.ruleset['enforcement'] == 'active'


@then('the required checks are ts and python')
def ruleset_requires_ts_and_python(context):
    checks = context.rules_by_type['required_status_checks']['required_status_checks']
    assert sorted(check['context'] for check in checks) == ['python', 'ts']


@then('a pull request is required with no approving reviews')
def ruleset_requires_pull_request_without_approvals(context):
    assert context.rules_by_type['pull_request']['required_approving_review_count'] == 0


@then('force pushes and deletion are refused')
def ruleset_refuses_force_push_and_deletion(context):
    assert {'non_fast_forward', 'deletion'} <= set(context.rules_by_type)


@then('only the GitHub Actions app may bypass it')
def ruleset_bypass_is_actions_app_only(context):
    assert [(actor['actor_type'], actor['actor_id']) for actor in context.ruleset['bypass_actors']] == [('Integration', 15368)]


@given('the workflow tests-board-only.yml')
def board_only_workflow_loaded(context):
    context.workflow = _workflow('tests-board-only.yml')


@when('its jobs are read')
def board_only_jobs_read(context):
    context.jobs = context.workflow['jobs']


@then('it reports checks named ts and python')
def board_only_reports_both_checks(context):
    assert {'ts', 'python'} <= set(context.jobs)


@then('it runs them only for pull requests whose every changed file is under project')
def board_only_checks_are_conditional(context):
    for name in ('ts', 'python'):
        assert "board_only == 'true'" in context.jobs[name]['if']
    assert context.workflow[True]['pull_request']['paths'] == ['project/**']
