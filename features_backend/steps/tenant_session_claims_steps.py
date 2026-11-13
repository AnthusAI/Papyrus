"""Tenant session claims (PPY-0bb0fd): drive the real pre-token-generation handler with stubbed Cognito version 2 events and an
in-memory copy of the TenantMembership and TenantSelection models (no AWS: decision D9), and read the synthesised templates for the
wiring scenarios."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from behave import given, register_type, then, when
import parse

from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, TENANT_ID_ENVIRONMENT_VARIABLE
from papyrus_content.tenant_records import membership_record, tenant_selection_record

register_type(Tenant=parse.with_pattern(r'[a-z0-9][a-z0-9-]*')(lambda text: text))
register_type(Role=parse.with_pattern(r'admin|editor|curator|member')(lambda text: text))

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_CLAIMS = ('papyrus_tenant_admin', 'papyrus_tenant_editor', 'papyrus_tenant_curator', 'papyrus_tenant_member')
GRANTED_AT = '2026-11-13T00:00:00Z'

HANDLER_RUNNER = """
import { createHandler } from './amplify/functions/tenant-claims/handler';
import { buildTenantContext } from './amplify/functions/shared/tenant-context';
const { tables, environment, event, context } = JSON.parse(process.argv[1]);
(async () => {
  const handler = createHandler(async (model, id) => tables[model]?.[id] ?? null, () => environment);
  const result = await handler(event);
  let refusal = null;
  if (context) {
    try { buildTenantContext({ claims: { sub: 'x', ...(result.response.claimsAndScopeOverrideDetails?.accessTokenGeneration?.claimsToAddOrOverride ?? {}) } }, { environment }); }
    catch (error) { refusal = (error as { reason?: string }).reason ?? String(error); }
  }
  console.log(JSON.stringify({ event: result, refusal }));
})();
"""


def _sub(person):
    return f'sub-{person.lower()}'


def _world(context, *, mode='shared', tenant=None, tables=True):
    context.world = {'mode': mode, 'tenant': tenant, 'tables': tables, 'membership': {}, 'selection': {}, 'groups': {}}


def _world_of(context):
    return context.world


def _membership(context, person, tenant, role, status='active'):
    row = membership_record(tenant, _sub(person), role, 'ops', GRANTED_AT, status=status)
    context.world['membership'][row['id']] = row


def _select(context, person, tenant):
    row = tenant_selection_record(_sub(person), tenant, GRANTED_AT)
    context.world['selection'][row['id']] = row


def _environment(world):
    environment = {TENANCY_MODE_ENVIRONMENT_VARIABLE: world['mode']}
    if world['tenant']:
        environment[TENANT_ID_ENVIRONMENT_VARIABLE] = world['tenant']
    if world['tables']:
        environment['PAPYRUS_TENANT_RECORDS_DEPLOYED'] = 'true'
    return environment


def _event(person, groups, trigger_source):
    return {
        'triggerSource': trigger_source,
        'request': {'userAttributes': {'sub': _sub(person)}, 'groupConfiguration': {'groupsToOverride': list(groups)}},
        'response': {'claimsAndScopeOverrideDetails': {}},
    }


def _run(context, person, *, trigger_source='TokenGeneration_HostedAuth', build_context=False):
    world = context.world
    payload = {
        'tables': {'TenantMembership': world['membership'], 'TenantSelection': world['selection']},
        'environment': _environment(world),
        'event': _event(person, world['groups'].get(person, []), trigger_source),
        'context': build_context,
    }
    result = subprocess.run(['npx', 'tsx', '-e', HANDLER_RUNNER, json.dumps(payload)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    details = out['event']['response'].get('claimsAndScopeOverrideDetails', {})
    context.access_claims = (details.get('accessTokenGeneration') or {}).get('claimsToAddOrOverride', {})
    context.id_claims = (details.get('idTokenGeneration') or {}).get('claimsToAddOrOverride', {})
    context.group_override = details.get('groupOverrideDetails')
    context.refusal = out['refusal']
    context.person = person


def _tenant_claims(claims):
    return {name: value for name, value in claims.items() if name in ROLE_CLAIMS}


@given('Ada is an editor of "{alpha:Tenant}" and a member of "{beta:Tenant}" on a shared stack')
def given_ada_two_sites(context, alpha, beta):
    _world(context)
    _membership(context, 'Ada', alpha, 'editor')
    _membership(context, 'Ada', beta, 'member')


@given('Bo has a Google account and no TenantMembership on a shared stack')
def given_bo(context):
    _world(context)


@given('Ada is an editor of "{tenant:Tenant}" on a shared stack and has selected "{selected:Tenant}"')
def given_ada_editor_selected(context, tenant, selected):
    _world(context)
    _membership(context, 'Ada', tenant, 'editor')
    _select(context, 'Ada', selected)


@given('Ada has an editor membership of "{tenant:Tenant}" with status "{status}" on a shared stack and has selected "{selected:Tenant}"')
def given_ada_pending(context, tenant, status, selected):
    _world(context)
    _membership(context, 'Ada', tenant, 'editor', status)
    _select(context, 'Ada', selected)


@given('Cy belongs to the Cognito group "{group}" and has no TenantMembership on a shared stack')
def given_cy(context, group):
    _world(context)
    context.world['groups']['Cy'] = [group]


@given('a dedicated stack for tenant "{tenant:Tenant}" and Dee in the Cognito groups "{first}" and "{second}"')
def given_dee_two_groups(context, tenant, first, second):
    _world(context, mode='dedicated', tenant=tenant)
    context.world['groups']['Dee'] = [first, second]


@given('a dedicated stack for tenant "{tenant:Tenant}" and Dee in the Cognito group "{group}"')
def given_dee_group(context, tenant, group):
    _world(context, mode='dedicated', tenant=tenant)
    context.world['groups']['Dee'] = [group]


@given('a dedicated stack for tenant "{tenant:Tenant}" and Eli with an active member membership of "{member_of:Tenant}" and no group')
def given_eli(context, tenant, member_of):
    _world(context, mode='dedicated', tenant=tenant)
    _membership(context, 'Eli', member_of, 'member')


@given('Dee has selected "{tenant:Tenant}" and holds an admin membership of "{member_of:Tenant}"')
def given_dee_selected_elsewhere(context, tenant, member_of):
    _select(context, 'Dee', tenant)
    _membership(context, 'Dee', member_of, 'admin')


@given('a dedicated stack with no tenant and Dee in the Cognito group "{group}"')
def given_dedicated_none(context, group):
    _world(context, mode='dedicated')
    context.world['groups']['Dee'] = [group]


@given('a dedicated stack for tenant "{tenant:Tenant}" whose tenancy models are not deployed and Dee in the Cognito group "{group}"')
def given_dedicated_no_tables(context, tenant, group):
    _world(context, mode='dedicated', tenant=tenant, tables=False)
    context.world['groups']['Dee'] = [group]


@given('a shared stack whose tenancy models are not deployed and Ada in the Cognito group "{group}"')
def given_shared_no_tables(context, group):
    _world(context, tables=False)
    context.world['groups']['Ada'] = [group]


@given('her token carries papyrus_tenant_editor "{tenant:Tenant}"')
def given_token_before(context, tenant):
    _run(context, 'Ada')
    assert _tenant_claims(context.access_claims) == {'papyrus_tenant_editor': tenant}, context.access_claims


@when('she signs in and selects "{tenant:Tenant}"')
def when_selects(context, tenant):
    _select(context, 'Ada', tenant)
    _run(context, 'Ada')


@when('she switches to "{tenant:Tenant}"')
def when_switches(context, tenant):
    _select(context, 'Ada', tenant)
    _run(context, 'Ada', trigger_source='TokenGeneration_RefreshTokens')


@when('she signs in without having selected a site')
def when_no_selection(context):
    _run(context, 'Ada')


@when('he signs in to the newsroom')
def when_bo_signs_in(context):
    _run(context, 'Bo', build_context=True)


@when('he selects "{tenant:Tenant}" and signs in')
def when_bo_selects(context, tenant):
    _select(context, 'Bo', tenant)
    _run(context, 'Bo')


@when('Ada is removed from the Account that owns "{tenant:Tenant}" and her membership is revoked')
def when_removed(context, tenant):
    # The Prospectus membership-removed event marks the TenantMembership row revoked (PPY-31c45c models the row; the event consumer follows).
    row = context.world['membership'][f'{tenant}#{_sub("Ada")}']
    row['status'] = 'revoked'


@when('her TenantMembership row is deleted and her token is next refreshed')
def when_row_deleted(context):
    context.world['membership'].clear()
    _run(context, 'Ada', trigger_source='TokenGeneration_RefreshTokens')


@when('her token is next refreshed')
def when_refreshed(context):
    _run(context, 'Ada', trigger_source='TokenGeneration_RefreshTokens')


@when('{name} signs in')
def when_signs_in(context, name):
    _run(context, name)


@then('her access token carries papyrus_tenant_{role:Role} "{tenant:Tenant}" and no claim for "{other:Tenant}"')
def then_access_claims(context, role, tenant, other):
    claims = _tenant_claims(context.access_claims)
    assert claims == {f'papyrus_tenant_{role}': tenant}, claims
    assert other not in claims.values()


@then('her ID token carries the same claims')
def then_id_claims(context):
    assert _tenant_claims(context.id_claims) == _tenant_claims(context.access_claims), context.id_claims


@then('her access token carries papyrus_tenant_{role:Role} "{tenant:Tenant}" and no editor claim')
def then_member_only(context, role, tenant):
    claims = _tenant_claims(context.access_claims)
    assert claims == {f'papyrus_tenant_{role}': tenant}, claims
    assert 'papyrus_tenant_editor' not in claims


@then('his token has no tenant claim')
@then('her token has no tenant claim')
def then_none(context):
    assert _tenant_claims(context.access_claims) == {}, context.access_claims
    assert _tenant_claims(context.id_claims) == {}, context.id_claims


@then('a function that builds its tenant context from that token refuses the call as "{reason}"')
def then_refused(context, reason):
    assert context.refusal == reason, context.refusal


@then('it carries no "{tenant:Tenant}" claim')
def then_no_tenant_value(context, tenant):
    assert tenant not in _tenant_claims(context.access_claims).values(), context.access_claims
    assert tenant not in _tenant_claims(context.id_claims).values(), context.id_claims


@then('his Cognito groups are left as they were')
@then('her Cognito groups are left as they were')
def then_groups_untouched(context):
    assert context.group_override is None, context.group_override


@then('her token carries papyrus_tenant_editor "{tenant:Tenant}" and papyrus_tenant_curator "{same:Tenant}" only')
def then_two_roles(context, tenant, same):
    assert _tenant_claims(context.access_claims) == {'papyrus_tenant_editor': tenant, 'papyrus_tenant_curator': same}, context.access_claims


@then('her token carries no admin or member claim')
def then_no_admin_member(context):
    assert 'papyrus_tenant_admin' not in context.access_claims and 'papyrus_tenant_member' not in context.access_claims


@then('his token carries papyrus_tenant_{role:Role} "{tenant:Tenant}"')
@then('her token carries papyrus_tenant_{role:Role} "{tenant:Tenant}"')
def then_single(context, role, tenant):
    assert _tenant_claims(context.access_claims) == {f'papyrus_tenant_{role}': tenant}, context.access_claims


@then('her token carries papyrus_tenant_editor "{tenant:Tenant}" and no claim for "{other:Tenant}"')
def then_editor_not_other(context, tenant, other):
    claims = _tenant_claims(context.access_claims)
    assert claims == {'papyrus_tenant_editor': tenant}, claims
    assert other not in claims.values()


# --- Wiring: read the synthesised templates --------------------------------------------------------------------------------


def _synth(context, backend):
    if getattr(context, 'synth_key', None) == backend:
        return
    directory = Path(tempfile.mkdtemp(prefix='papyrus-claims-synth-'))
    context.add_cleanup(shutil.rmtree, directory, True)
    env = dict(os.environ)
    env.pop('PAPYRUS_BOOTSTRAP_STAGE', None)
    if 'bootstrap' in backend:
        env['PAPYRUS_BOOTSTRAP_STAGE'] = '1'
    config = {'productionAppId': '', 'brandId': 'claims-test'}
    if 'shared' in backend:
        config['tenancy'] = {'mode': 'shared'}
        # Only the tenancy model group is needed to read the wiring; leaving the other optional groups out makes the synth faster.
        config['excludeModelGroups'] = ['editions', 'knowledge', 'semantic', 'review', 'procedures', 'editorial', 'steering', 'variations', 'localization']
    result = subprocess.run(['npx', 'tsx', 'scripts/synth-site-backend.mts', str(directory), json.dumps(config)], cwd=REPO_ROOT,
                            env=env, capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stdout + result.stderr
    templates = {}
    for file in directory.glob('*.template.json'):
        templates[file.name] = json.loads(file.read_text())
    context.templates = templates
    context.synth_key = backend


def _resources(context, resource_type):
    found = []
    for name, template in context.templates.items():
        for logical_id, resource in template.get('Resources', {}).items():
            if resource.get('Type') == resource_type:
                found.append((name, logical_id, resource))
    return found


def _pool(context):
    pools = _resources(context, 'AWS::Cognito::UserPool')
    assert len(pools) == 1, pools
    return pools[0][2]['Properties']


def _claims_function(context):
    functions = [(n, i, r) for n, i, r in _resources(context, 'AWS::Lambda::Function') if 'tenantclaims' in i.lower()]
    assert len(functions) == 1, [i for _, i, _ in functions]
    return functions[0]


@when('the site backend is synthesised with a shared tenancy stack')
def when_synth_shared(context):
    _synth(context, 'shared')


@when('the site backend is synthesised for the bootstrap stage')
def when_synth_bootstrap(context):
    _synth(context, 'bootstrap')


def _trigger_arn(context):
    config = _pool(context)['LambdaConfig']['PreTokenGenerationConfig']
    return config


@then('the user pool\'s pre-token-generation trigger is the tenant claims function at event version "{version}"')
def then_trigger(context, version):
    config = _trigger_arn(context)
    assert config['LambdaVersion'] == version, config
    _, logical_id, _ = _claims_function(context)
    assert logical_id in json.dumps(config['LambdaArn']), (logical_id, config)


@then("the user pool has no version one pre-token-generation trigger")
def then_no_v1(context):
    assert 'PreTokenGeneration' not in _pool(context)['LambdaConfig'], _pool(context)['LambdaConfig']


@then('the user pool plan is "{plan}"')
def then_plan(context, plan):
    assert _pool(context)['UserPoolTier'] == plan, _pool(context).get('UserPoolTier')


@then('the tenant claims function can query the data API and cannot write to it')
def then_grants(context):
    _, _, function = _claims_function(context)
    role_name = function['Properties']['Role']['Fn::GetAtt'][0][:-8]  # the logical id without its 8-character hash
    statements = []
    # The AppSync grant is created in the data stack, on the function's role (which the auth stack exports under a name of its own).
    for _, _, policy in _resources(context, 'AWS::IAM::Policy'):
        if role_name in json.dumps(policy['Properties'].get('Roles', [])):
            statements.extend(policy['Properties']['PolicyDocument']['Statement'])
    graphql = [s for s in statements if 'appsync:GraphQL' in _listed(s['Action'])]
    assert len(graphql) == 1, 'the function should have exactly one AppSync grant: %s' % statements
    resource = json.dumps(graphql[0]['Resource'])
    assert '/types/Query/*' in resource, resource
    assert 'Mutation' not in resource and 'Subscription' not in resource, 'the function can write: ' + resource
    assert not [s for s in statements if any(a.startswith('dynamodb:') for a in _listed(s['Action']))], 'the function names a table directly'


@then('the auth stack does not depend on the data stack')
def then_no_cycle(context):
    root = next(t for n, t in context.templates.items() if not n.endswith('.nested.template.json'))
    stacks = {k: r for k, r in root['Resources'].items() if r['Type'] == 'AWS::CloudFormation::Stack'}
    auth = next(r for k, r in stacks.items() if k.startswith('auth'))
    data_ids = [k for k in stacks if k.startswith('data')]
    parameters = json.dumps(auth['Properties'].get('Parameters', {}))
    assert not any(data_id in parameters for data_id in data_ids), 'the auth stack takes a value from the data stack (a CloudFormation cycle)'
    assert not any(data_id in json.dumps(auth.get('DependsOn', [])) for data_id in data_ids)


@then('the tenant claims function is told the tenancy models are deployed')
def then_flag(context):
    _, _, function = _claims_function(context)
    env = function['Properties'].get('Environment', {}).get('Variables', {})
    assert env.get('PAPYRUS_TENANT_RECORDS_DEPLOYED') == 'true', env


@then('the tenant claims function is not told the tenancy models are deployed')
def then_no_flag(context):
    _, _, function = _claims_function(context)
    env = function['Properties'].get('Environment', {}).get('Variables', {})
    assert 'PAPYRUS_TENANT_RECORDS_DEPLOYED' not in env, env


def _listed(value):
    return value if isinstance(value, list) else [value]
