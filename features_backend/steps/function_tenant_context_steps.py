"""One tenant context builder: run the Python builder in process and the TypeScript builder through tsx."""
import json
import os
import subprocess
from pathlib import Path

from behave import given, when, then

from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE
from papyrus_content.tenant_context import TenantContextRefusal, build_tenant_context

REPO_ROOT = Path(__file__).resolve().parents[2]
IAM = {'accountId': '000000000000', 'userArn': 'arn:aws:iam::000000000000:role/operator'}
TS_RUNNER = """
import { buildTenantContext } from './amplify/functions/shared/tenant-context';
const [identity, explicitTenant, environment] = JSON.parse(process.argv[1]);
try { console.log(JSON.stringify({ ok: buildTenantContext(identity, { explicitTenant, environment }) })); }
catch (error) { console.log(JSON.stringify({ refused: (error as { reason?: string }).reason })); }
"""


def _set(context, mode, tenant, identity):
    context.environment = {TENANCY_MODE_ENVIRONMENT_VARIABLE: mode}
    if tenant:
        context.environment[TENANT_ID_ENVIRONMENT_VARIABLE] = tenant
    context.identity = identity


def _user(**claims):
    return {'claims': {'sub': 'user-1', **claims}}


@given('tenancy mode shared and an IAM event with no tenant')
def step_iam(context):
    _set(context, 'shared', None, IAM)


@given('tenancy mode shared and a signed-in event whose member claim is "{tenant}"')
def step_member(context, tenant):
    _set(context, 'shared', None, _user(papyrus_tenant_member=tenant))


@given('tenancy mode shared and a signed-in event with an admin claim "{admin}" and a member claim "{member}"')
def step_two(context, admin, member):
    _set(context, 'shared', None, _user(papyrus_tenant_admin=admin, papyrus_tenant_member=member))


@given('a dedicated stack for tenant "{tenant}" and a signed-in event whose editor claim is "{claim}"')
def step_dedicated(context, tenant, claim):
    _set(context, 'dedicated', tenant, _user(papyrus_tenant_editor=claim))


@given('a dedicated stack with no tenant and a signed-in event with no claims')
def step_dedicated_none(context):
    _set(context, 'dedicated', None, _user())


@when('the context is built')
def step_build(context):
    saved = {k: os.environ.get(k) for k in (TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE)}
    for key in saved:
        os.environ.pop(key, None)
    os.environ.update(context.environment)
    try:
        built = build_tenant_context(context.identity)
        context.python = {'ok': {'tenantId': built.tenant_id, 'roles': list(built.roles)}}
    except TenantContextRefusal as refusal:
        context.python = {'refused': refusal.reason}
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
    result = subprocess.run(
        ['npx', 'tsx', '-e', TS_RUNNER, json.dumps([context.identity, None, context.environment])],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    ts = json.loads(result.stdout.strip().splitlines()[-1])
    context.typescript = {'ok': {'tenantId': ts['ok']['tenantId'], 'roles': ts['ok']['roles']}} if 'ok' in ts else ts


@then('it raises a refusal before any read')
def step_refused(context):
    assert 'refused' in context.python, context.python
    assert 'refused' in context.typescript, context.typescript


@then('the refusal reason is "{reason}" in Python and in TypeScript')
def step_reason(context, reason):
    assert context.python['refused'] == reason, context.python
    assert context.typescript['refused'] == reason, context.typescript


@then('the tenant is "{tenant}" with the roles "{roles}" in Python and in TypeScript')
def step_tenant(context, tenant, roles):
    expected = {'ok': {'tenantId': tenant, 'roles': roles.split(',')}}
    assert context.python == expected, context.python
    assert context.typescript == expected, context.typescript


@then('the tenant is none with no roles in Python and in TypeScript')
def step_none(context):
    expected = {'ok': {'tenantId': None, 'roles': []}}
    assert context.python == expected, context.python
    assert context.typescript == expected, context.typescript
