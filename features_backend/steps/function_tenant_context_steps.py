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


# --- the real content-actions handler on an in-memory backend that holds two tenants' rows ---------------------------------------------------

import importlib.util  # noqa: E402
import sys  # noqa: E402
from unittest import mock  # noqa: E402

for _entry in (REPO_ROOT / 'src', REPO_ROOT):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from papyrus_content.tenancy import row_belongs_to_tenant  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

HANDLER = REPO_ROOT / 'amplify/functions/content-actions/handler.py'
EDITOR_ROLES = {'editor': 'papyrus_tenant_editor'}


class BackendLog:
    """What the function received from the backend and what it wrote."""

    def __init__(self):
        self.served = []
        self.writes = []
        self.clients = []


class TenantClient(FakeAuthoringClient):
    """The in-memory authoring client of one tenant over tables shared by every tenant, answering as the real tenant client does."""

    def __init__(self, tables, tenant_id, log):
        super().__init__()
        self.tables, self.tenant_id, self.log = tables, tenant_id, log
        log.clients.append(self)

    def get_record(self, model_name, record_id):
        row = super().get_record(model_name, record_id)
        if row is not None and not row_belongs_to_tenant(model_name, self.tenant_id, row):
            return None
        if row is not None:
            self.log.served.append(row)
        return row

    def create_record(self, model_name, payload):
        self.log.writes.append((model_name, payload['id'], payload.get('tenantId')))
        super().create_record(model_name, {**payload, **({'tenantId': self.tenant_id} if self.tenant_id and model_name == 'Item' else {})})

    def update_record(self, model_name, payload):
        self.log.writes.append((model_name, payload['id'], payload.get('tenantId')))
        super().update_record(model_name, payload)

    def upsert(self, model_name, payload):
        self.log.writes.append((model_name, payload['id'], payload.get('tenantId')))
        return super().upsert(model_name, {**payload, **({'tenantId': self.tenant_id} if self.tenant_id and model_name == 'Item' else {})})


def _handler_module():
    specification = importlib.util.spec_from_file_location('content_actions_tenant_context_steps', HANDLER)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _backend(context, mode, fixed=None):
    environment = {TENANCY_MODE_ENVIRONMENT_VARIABLE: mode}
    if fixed:
        environment[TENANT_ID_ENVIRONMENT_VARIABLE] = fixed
    patcher = mock.patch.dict(os.environ, environment)
    patcher.start()
    for key in (TENANT_ID_ENVIRONMENT_VARIABLE,) if not fixed else ():
        os.environ.pop(key, None)
    context.add_cleanup(patcher.stop)
    context.log, context.tables, context.module = BackendLog(), {}, _handler_module()
    context.module.create_authoring_client = lambda tenant_id=None, **_: (TenantClient(context.tables, tenant_id, context.log), {})
    context.foreign_ids, context.story_ids = set(), {}


def _story(context, tenant):
    story_id = f'{tenant}.item-story'
    context.tables.setdefault('Item', {})[story_id] = {
        'id': story_id, 'tenantId': tenant, 'lineageId': story_id, 'versionNumber': 1, 'versionState': 'current', 'type': 'article',
        'slug': f'{tenant}-story', 'section': 'articles', 'status': 'draft', 'title': f'The {tenant} story', 'contentHash': f'{tenant}-hash'}
    context.story_ids[tenant] = story_id
    if tenant == 'beta':
        context.foreign_ids.add(story_id)


@given('a shared stack with tenants "{first}" and "{second}"')
def step_shared_stack(context, first, second):
    assert (first, second) == ('alpha', 'beta')
    _backend(context, 'shared')


@given('a dedicated stack for the tenant "{tenant}" with an "{story_tenant}" story')
def step_dedicated_stack(context, tenant, story_tenant):
    _backend(context, 'dedicated', tenant)
    _story(context, story_tenant)


@given('a "{tenant}" story')
@given('an "{tenant}" story')
def step_story(context, tenant):
    _story(context, tenant)


@given('an "{tenant}" editor')
@given('a "{tenant}" editor')
def step_editor(context, tenant):
    context.identity = _user(**{EDITOR_ROLES['editor']: tenant})


@given('an editor whose token carries no tenant claim')
def step_untenanted_editor(context):
    context.identity = _user()


@given('the platform operator role')
def step_operator(context):
    context.identity = IAM


def _save_payload(story_id, **extra):
    return {'id': story_id, 'type': 'article', 'slug': 'a-story', 'section': 'articles', 'frontMatterYaml': 'title: Hello\n',
            'bodyMarkus': 'Hello\n', 'aliases': [], **extra}


def _invoke(context, payload):
    event = {'fieldName': 'saveItemDraft', 'arguments': {'input': json.dumps(payload)}, 'identity': context.identity}
    context.response, context.refusal = None, None
    try:
        context.response = context.module.handler(event, None)
    except TenantContextRefusal as refusal:
        context.refusal = refusal


@when('the editor calls saveItemDraft with the id of the "{tenant}" story')
def step_save(context, tenant):
    _invoke(context, _save_payload(context.story_ids[tenant]))


@when('the editor calls saveItemDraft with the id of the "{tenant}" story and a body that names the tenant "{named}"')
def step_save_naming(context, tenant, named):
    _invoke(context, _save_payload(context.story_ids[tenant], tenantId=named))


@when('it invokes content-actions without naming a tenant')
def step_iam_without_tenant(context):
    _invoke(context, _save_payload(None))


@when('it invokes content-actions for the tenant "{named}" with the id of the "{tenant}" story')
def step_iam_naming(context, named, tenant):
    _invoke(context, _save_payload(context.story_ids[tenant], tenantId=named))


@then('the call is refused with "not found" and nothing of "{tenant}" is read or written')
def step_not_found(context, tenant):
    assert context.refusal is None, context.refusal
    assert context.response['ok'] is False and 'not found' in context.response['errors'][0]['message'], context.response
    step_nothing_of(context, tenant)


@then('nothing of "{tenant}" is read or written')
def step_nothing_of(context, tenant):
    assert [row['id'] for row in context.log.served if row.get('tenantId') == tenant] == [], context.log.served
    assert [write for write in context.log.writes if write[1] in context.foreign_ids or write[2] == tenant] == [], context.log.writes


@then('the call is refused before any read')
def step_refused_before_read(context):
    assert context.refusal is not None, context.response
    assert context.log.clients == [] and context.log.served == [] and context.log.writes == [], (context.log.clients, context.log.served)


@then('the draft is saved as a story of "{tenant}"')
def step_saved(context, tenant):
    assert context.refusal is None, context.refusal
    assert context.response['ok'] is True, context.response
    assert context.response['item']['id'] == context.story_ids[tenant]
    assert [client.tenant_id for client in context.log.clients] and {client.tenant_id for client in context.log.clients} == {tenant}


@then('the function acted for the fixed tenant "{tenant}"')
def step_fixed(context, tenant):
    assert {client.tenant_id for client in context.log.clients} == {tenant}
