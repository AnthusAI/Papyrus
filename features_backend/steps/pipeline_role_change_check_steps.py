"""The automatic check on the pipeline roles' template (reads the template and role_stack.py; calls no AWS)."""
import importlib.util
import sys
import tempfile
from pathlib import Path

import yaml
from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / 'infra' / 'pipeline'
ROLES_TEMPLATE = PIPELINE / 'papyrus-stack-pipeline.yaml'
ROLES_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'role-stack-deploy.yml'
EXTRA_PERMISSION = 'cloudformation:DeleteStack'
EXISTING_PERMISSION = 'cloudformation:DeleteChangeSet'

sys.path.insert(0, str(PIPELINE))
_stack_deploy_spec = importlib.util.spec_from_file_location('stack_deploy', PIPELINE / 'stack_deploy.py')
stack_deploy = importlib.util.module_from_spec(_stack_deploy_spec)
sys.modules['stack_deploy'] = stack_deploy
_stack_deploy_spec.loader.exec_module(stack_deploy)
_role_stack_spec = importlib.util.spec_from_file_location('role_stack', PIPELINE / 'role_stack.py')
role_stack = importlib.util.module_from_spec(_role_stack_spec)
_role_stack_spec.loader.exec_module(role_stack)


def _write_changed_template(context, changed_text):
    directory = Path(tempfile.mkdtemp(prefix='papyrus-role-change-'))
    context.changed_template_path = directory / 'papyrus-stack-pipeline.yaml'
    context.changed_template_path.write_text(changed_text, encoding='utf-8')
    context.base_template_text = ROLES_TEMPLATE.read_text(encoding='utf-8')
    context.changed_template = stack_deploy.parse_template(changed_text)


@given('the deploy roles template with one extra permission on the deploy role')
def template_with_extra_permission(context):
    _write_changed_template(context, ROLES_TEMPLATE.read_text(encoding='utf-8').replace(EXISTING_PERMISSION, EXTRA_PERMISSION, 1))


@given('the deploy roles template with the AdministratorAccess policy attached to the deploy role')
def template_with_administrator_policy(context):
    changed = stack_deploy.parse_template(ROLES_TEMPLATE.read_text(encoding='utf-8'))
    changed['Resources']['DeployRole']['Properties']['ManagedPolicyArns'] = ['arn:aws:iam::aws:policy/AdministratorAccess']
    _write_changed_template(context, yaml.safe_dump(changed))


@given('an empty list of allowed role changes')
def empty_allowed_list(context):
    context.allowed_role_changes = []


def _fingerprints_of_every_changed_statement(context):
    base = stack_deploy.parse_template(context.base_template_text)
    return [{'fingerprint': role_stack.role_statement_fingerprint(line), 'reason': 'listed in the scenario'} for _, line in role_stack.role_change_lines(base, context.changed_template)]


@given('the extra permission listed by its fingerprint')
def extra_permission_listed(context):
    context.allowed_role_changes = _fingerprints_of_every_changed_statement(context)


@given('every changed statement listed by its fingerprint')
def every_changed_statement_listed(context):
    context.allowed_role_changes = _fingerprints_of_every_changed_statement(context)


@when('the automatic check runs on the pull request')
def run_check(context):
    context.check_output = []
    context.check_exit_code = role_stack.check(context.base_template_text, context.changed_template_path, context.allowed_role_changes, out=context.check_output.append)


@then('the automatic check fails')
def check_fails(context):
    assert context.check_exit_code == 2, context.check_output


@then('the automatic check passes')
def check_passes(context):
    assert context.check_exit_code == 0, context.check_output


@then('the output names the extra permission and its fingerprint')
def output_names_permission_and_fingerprint(context):
    output = '\n'.join(context.check_output)
    assert EXTRA_PERMISSION in output and 'fingerprint' in output


@then('the output says a hard rule is broken')
def output_says_hard_rule(context):
    assert 'breaks a hard rule' in '\n'.join(context.check_output)


@given('the deploy roles template in the repository')
def repository_template(context):
    context.changed_template = stack_deploy.parse_template(ROLES_TEMPLATE.read_text(encoding='utf-8'))


@when('the hard rules are read')
def hard_rules_read(context):
    context.hard_rule_problems = role_stack.hard_rule_violations(context.changed_template)


@then('no rule is broken')
def no_rule_broken(context):
    assert context.hard_rule_problems == []


@given('the role deploy workflow')
def role_workflow_loaded(context):
    context.workflow_text = ROLES_WORKFLOW.read_text(encoding='utf-8')
    context.workflow = yaml.safe_load(context.workflow_text)


@when('its apply job is read')
def apply_job_read(context):
    context.apply_job = context.workflow['jobs']['apply']


@then('the apply job needs the plan job')
def apply_needs_plan(context):
    assert context.apply_job['needs'] == 'plan'


@then('the workflow says no person approves a change')
def workflow_says_no_approval(context):
    assert 'Nobody clicks anything' in context.workflow_text and 'required reviewers' not in context.workflow_text.lower()
