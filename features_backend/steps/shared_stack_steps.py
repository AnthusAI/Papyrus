"""The shared stacks (PPY-daf673): synth-level checks of the real backend and template-level checks of the foundation and the pipeline.

Nothing here calls AWS. The full backend synth takes minutes, so the three synths the scenarios read run once, in parallel, the first
time one is needed, and are removed when the run ends.
"""
import atexit
import os
import json
import importlib.util
import math
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from behave import given, when, then

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / 'infra' / 'pipeline'
FOUNDATION = REPO_ROOT / 'infra' / 'shared-stack' / 'papyrus-shared-foundation.yaml'
DOC = REPO_ROOT / 'docs' / 'shared-stack.md'
KEY_PARAMETER = 'PapyrusSharedKmsKeyArn'

_spec = importlib.util.spec_from_file_location('stack_deploy', PIPELINE / 'stack_deploy.py')
stack_deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stack_deploy)

_SYNTHS = {}
_TEMP_DIRS = []
atexit.register(lambda: None if os.environ.get('PAPYRUS_KEEP_SYNTH') else [shutil.rmtree(path, ignore_errors=True) for path in _TEMP_DIRS])


def _node(*args, timeout=900, env=None):
    return subprocess.run(['npx', 'tsx', *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})


def _shared_config(tier):
    result = _node('-e', f'import {{ sharedStackBackendConfig }} from "./amplify/shared-stack/define"; console.log(JSON.stringify(sharedStackBackendConfig("{tier}")))')
    assert result.returncode == 0, result.stderr[-1500:]
    return result.stdout.strip()


def _synth(backend_json, options_json=None, bootstrap=True):
    out = Path(tempfile.mkdtemp(prefix='papyrus-shared-stack-'))
    _TEMP_DIRS.append(out)
    args = ['scripts/synth-backend-with-options.mts', str(out), backend_json] + ([options_json] if options_json else [])
    return out, _node(*args, env={'PAPYRUS_BOOTSTRAP_STAGE': '1'} if bootstrap else {})


def _synths():
    """The shared staging backend, and the dedicated backend with and without the deny, synthesised in parallel once."""
    if not _SYNTHS:
        dedicated = json.dumps({'productionAppId': '', 'brandId': 'bootstrap-test'})
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {
                'shared': pool.submit(_synth, _shared_config('staging')),
                'dedicated': pool.submit(_synth, dedicated),
                'dedicated-without-deny': pool.submit(_synth, dedicated, json.dumps({'dedicatedSharedStackDeny': False})),
            }
            for name, job in jobs.items():
                out, result = job.result()
                assert result.returncode == 0, f'{name} synth failed: {result.stderr[-2000:]}'
                _SYNTHS[name] = out
    return _SYNTHS


def _templates(directory):
    return {path.name: json.loads(path.read_text()) for path in sorted(Path(directory).glob('*.template.json'))}


def _facts(directory):
    return json.loads((Path(directory) / 'synth-facts.json').read_text())


def _resources(templates, *types):
    return [(name, key, value) for name, template in templates.items() for key, value in template.get('Resources', {}).items() if value['Type'] in types]


def _foundation():
    return stack_deploy.parse_template(FOUNDATION.read_text())


def _statements(document):
    statements = document['Statement']
    return statements if isinstance(statements, list) else [statements]


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _pipeline_template():
    return stack_deploy.parse_template((PIPELINE / 'papyrus-stack-pipeline.yaml').read_text())


def _stacks_config():
    return json.loads((PIPELINE / 'stacks.json').read_text())


def _plans():
    result = _node('-e', 'import { sharedTierPlan, isReservedDeployment, SHARED_FAMILY_PREFIX } from "./amplify/shared-stack/names";'
                         'console.log(JSON.stringify({ production: sharedTierPlan("production"), staging: sharedTierPlan("staging"),'
                         ' reserved: ["shared", "shared-prod", "shared-staging"].map(isReservedDeployment), free: isReservedDeployment("shipped"), prefix: SHARED_FAMILY_PREFIX }))')
    assert result.returncode == 0, result.stderr[-1500:]
    return json.loads(result.stdout)


_SETTINGS = []


def _settings():
    """The tiers of amplify/shared-stack/settings.ts, as JSON."""
    if not _SETTINGS:
        result = _node('-e', 'import { SHARED_STACK_SETTINGS } from "./amplify/shared-stack/settings"; console.log(JSON.stringify(SHARED_STACK_SETTINGS.tiers))')
        assert result.returncode == 0, result.stderr[-1500:]
        _SETTINGS.append(json.loads(result.stdout.strip().splitlines()[-1]))
    return _SETTINGS[0]


def _normalised(text):
    """Mask content hashes and the two timestamps a synth stamps (asset expiry, secret update time)."""
    text = re.sub(r'[0-9a-f]{64}', '<hash>', text)
    return re.sub(r'("Expires": |"secretLastUpdated": )\d+', r'\1<time>', text)


def _is_key_reference(value):
    return isinstance(value, dict) and set(value) == {'Ref'} and KEY_PARAMETER in value['Ref']


# --- the empty shared stack --------------------------------------------------------------------------------------------------------


@given('a fresh shared stack')
def step_fresh(context):
    context.synths = _synths()


@when('any host is requested')
def step_any_host(context):
    context.templates = _templates(context.synths['shared'])


@then('the edge answers 404 and the API holds no tenant rows')
def step_empty(context):
    # The shared stack has no distribution, no alias and no host mapping, so the edge has nothing to answer with but a 404; and nothing in
    # its templates writes a row, so the tenant tables start empty.
    assert not _resources(context.templates, 'AWS::CloudFront::Distribution'), 'a distribution would serve hosts'
    text = json.dumps(context.templates)
    assert '"Aliases"' not in text and 'PAPYRUS_SITE_PUBLIC_URL' not in text and 'PAPYRUS_SITE_PROJECTOR' not in text
    # Nothing writes a row: no AwsCustomResource, no seeding function, and no model table is made with items.
    assert not _resources(context.templates, 'Custom::AWS'), 'a custom resource that calls the API could write rows'
    assert not [key for _, key, _ in _resources(context.templates, 'AWS::Lambda::Function') if 'seed' in key.lower()]
    for _, key, value in _resources(context.templates, 'Custom::AmplifyDynamoDBTable'):
        assert not {name for name in value['Properties'] if name.lower() in ('items', 'seed', 'seeddata', 'initialitems')}, key
    assert _facts(context.synths['shared'])['contentActionsSiteFiles'] == []


@given('the shared staging backend is synthesised')
def step_shared(context):
    context.synths = _synths()
    context.templates = _templates(context.synths['shared'])
    context.facts = _facts(context.synths['shared'])


@given('the shared staging backend is synthesised with the bootstrap stage on')
def step_shared_bootstrap(context):
    step_shared(context)


@then('every function carries the tenancy mode "{mode}"')
def step_tenancy(context, mode):
    owned = [value for _, _, value in _resources(context.templates, 'AWS::Lambda::Function') if 'ReservedConcurrentExecutions' in value['Properties']]
    assert len(owned) >= 15, len(owned)
    missing = [value['Properties']['FunctionName'] for value in owned if value['Properties'].get('Environment', {}).get('Variables', {}).get('PAPYRUS_TENANCY_MODE') != mode]
    assert not missing, missing


@then('the content-actions function bundles no site files')
def step_no_site_files(context):
    assert context.facts['contentActionsSiteFiles'] == []


@then('the backend configures no site host and no distribution alias')
def step_no_host(context):
    assert not _resources(context.templates, 'AWS::CloudFront::Distribution')
    assert '"Aliases"' not in json.dumps(context.templates)


@then("the root and nested templates together hold fewer than 2,500 resources")
def step_limit(context):
    total = sum(len(template.get('Resources', {})) for template in context.templates.values())
    context.resource_count = total
    assert total < 2500, f'{total} resources; CloudFormation fails an operation at 2,500'


@then('the models of the optional groups are left for the second deploy')
def step_optional(context):
    models = {name for group in context.facts['optionalModelGroups'].values() for name in group}
    stacks = {m.group(1) for name in context.templates if (m := re.search(r'PapyrusCmsApi(.+?)[0-9A-F]{8}\.nested\.template\.json$', name))}
    assert models and not (models & stacks), models & stacks


# --- names and the pipeline ----------------------------------------------------------------------------------------------------------


@given('the shared stack plans for production and staging')
def step_plans(context):
    context.plans = _plans()


@then('the production names start with "{prefix}"')
def step_production_names(context, prefix):
    plan = context.plans['production']
    assert all(plan[key].startswith(prefix) for key in ('stackPrefix', 'foundationStackName', 'boundaryPolicyName'))
    assert plan['rolePath'].startswith('/' + prefix) and plan['keyAlias'] == 'alias/' + prefix


@then('the staging names start with "{prefix}"')
def step_staging_names(context, prefix):
    plan = context.plans['staging']
    assert all(plan[key].startswith(prefix) for key in ('stackPrefix', 'foundationStackName', 'boundaryPolicyName'))
    assert plan['rolePath'].startswith('/' + prefix) and plan['keyAlias'] == 'alias/' + prefix


@then('no production name is a prefix of a staging name or the other way round')
def step_no_overlap(context):
    production, staging = context.plans['production'], context.plans['staging']
    for key in ('stackPrefix', 'foundationStackName', 'rolePath', 'keyAlias', 'boundaryPolicyName', 'ssmPrefix'):
        assert not production[key].startswith(staging[key]) and not staging[key].startswith(production[key]), key


@then('no dedicated site id can take a shared deployment tag value')
def step_reserved(context):
    assert all(context.plans['reserved']) and context.plans['free'] is False


@given("the pipeline's stack list and its roles")
def step_pipeline(context):
    context.stacks_config = _stacks_config()
    context.pipeline = _pipeline_template()


@then('both shared foundation stacks are listed in the "{group}" group with their own deploy role and service role')
def step_group(context, group):
    shared = [stack for stack in context.stacks_config['stacks'] if stack.get('group') == group]
    assert [stack['name'] for stack in shared] == ['papyrus-shared-staging-foundation', 'papyrus-shared-prod-foundation'], 'staging comes first'
    role_name = context.pipeline['Resources']['SharedCloudFormationRole']['Properties']['RoleName']
    for stack in shared:
        assert stack['serviceRoleName'] == role_name
        assert (REPO_ROOT / stack['template']).exists()
        assert str(stack['hold']).strip(), 'the first create waits for a go'
    workflow = (REPO_ROOT / '.github' / 'workflows' / 'stack-deploy.yml').read_text()
    assert 'papyrus-shared-deploy-github' in workflow and 'deploy --group shared' in workflow
    assert context.pipeline['Resources']['SharedDeployRole']['Properties']['RoleName'] == 'papyrus-shared-deploy-github'


@then('a pull request that touches a shared template prints a read-only dry run')
def step_dry_run(context):
    workflow = yaml.safe_load((REPO_ROOT / '.github' / 'workflows' / 'stack-deploy.yml').read_text())
    assert 'infra/shared-stack/**' in workflow[True]['pull_request']['paths']
    text = (REPO_ROOT / '.github' / 'workflows' / 'stack-deploy.yml').read_text()
    assert 'papyrus-shared-plan-github' in text and 'plan --group shared' in text and 'scope --plan' in text
    plan = context.pipeline['Resources']['SharedPlanRole']['Properties']
    assert plan['AssumeRolePolicyDocument']['Statement'][0]['Condition']['StringEquals']['token.actions.githubusercontent.com:sub'] == {'Fn::Sub': 'repo:${GitHubRepository}:pull_request'}
    actions = [a for s in _statements(plan['Policies'][0]['PolicyDocument']) for a in _as_list(s['Action'])]
    assert all(a.split(':')[1].startswith(('Describe', 'Get', 'List')) for a in actions), actions
    # A held stack is still planned: the dry run's scope includes it.
    config = {'stacks': [{'name': 'held', 'hold': 'wait', 'paths': ['a/'], 'template': 'x', 'group': 'shared'}, {'name': 'live', 'paths': ['a/'], 'template': 'x'}]}
    assert [s['name'] for s in stack_deploy.selected(config, None, 'shared')] == []
    assert [s['name'] for s in stack_deploy.selected(config, None, 'shared', include_held=True)] == ['held']


@then('the shared deploy role may create change sets only on stacks that start with "{prefix}"')
def step_deploy_role(context, prefix):
    role = context.pipeline['Resources']['SharedDeployRole']['Properties']
    assert role['AssumeRolePolicyDocument']['Statement'][0]['Condition']['StringEquals']['token.actions.githubusercontent.com:sub'] == {'Fn::Sub': 'repo:${GitHubRepository}:ref:refs/heads/main'}
    statements = _statements(role['Policies'][0]['PolicyDocument'])
    create = [s for s in statements if 'cloudformation:CreateChangeSet' in _as_list(s['Action'])]
    assert len(create) == 1
    assert create[0]['Condition']['StringEquals']['cloudformation:RoleArn'] == {'Fn::GetAtt': ['SharedCloudFormationRole', 'Arn']}
    for statement in statements:
        for resource in _as_list(statement['Resource']):
            if isinstance(resource, dict) and 'Fn::Sub' in resource and ':stack/' in resource['Fn::Sub'] and 'papyrus-stack-pipeline' not in resource['Fn::Sub'] and 'papyrus-monitoring' not in resource['Fn::Sub']:
                assert f'stack/{prefix}*/*' in resource['Fn::Sub'], resource
    text = json.dumps(role)
    assert 'papyrus-shared-*' in text and 'papyrus-newsletter' not in text
    passes = [s for s in statements if 'iam:PassRole' in _as_list(s['Action'])]
    assert len(passes) == 1 and passes[0]['Resource'] == {'Fn::GetAtt': ['SharedCloudFormationRole', 'Arn']}


@then('the existing per-site and monitoring deploy roles name no shared stack')
def step_not_widened(context):
    for name in ('PlanRole', 'DeployRole', 'CloudFormationRole', 'ComputeAndIdentityPolicy', 'DataAndMailPolicy'):
        assert 'papyrus-shared' not in json.dumps(context.pipeline['Resources'][name]), name
    approver = stack_deploy.parse_template((PIPELINE / 'papyrus-pipeline-approver.yaml').read_text())
    assert 'papyrus-shared-deploy-cloudformation' in json.dumps(approver['Resources']['ServiceRole']), 'the approver stack lets the roles stack create the shared roles'


# --- the key ----------------------------------------------------------------------------------------------------------------------------


@given('the shared foundation template')
def step_foundation(context):
    context.foundation = _foundation()
    context.pipeline = _pipeline_template()


@then('it creates one key with rotation on and the longest deletion window, retained when the stack is deleted')
def step_key(context):
    keys = [value for value in context.foundation['Resources'].values() if value['Type'] == 'AWS::KMS::Key']
    assert len(keys) == 1
    key = keys[0]
    assert key['DeletionPolicy'] == 'Retain' and key['UpdateReplacePolicy'] == 'Retain'
    properties = key['Properties']
    assert properties['EnableKeyRotation'] is True and properties['PendingWindowInDays'] == 30 and properties['KeyUsage'] == 'ENCRYPT_DECRYPT'


def _key_statements(context):
    key = next(value for value in context.foundation['Resources'].values() if value['Type'] == 'AWS::KMS::Key')
    return _statements(key['Properties']['KeyPolicy'])


@then("its key policy allows use only to roles on the stack's own role path and the platform operator role")
def step_key_use(context):
    use = [s for s in _key_statements(context) if s['Sid'].startswith('UseByTheStacksOwn')]
    assert len(use) == 1
    patterns = json.dumps(use[0]['Condition']['ArnLike']['aws:PrincipalArn'])
    assert 'role/${Prefix}/*' in patterns and 'PlatformOperatorRoleName' in patterns
    assert use[0]['Condition']['StringEquals']['aws:PrincipalAccount'] == {'Ref': 'AWS::AccountId'}
    assert use[0]['Principal'] == {'AWS': '*'}, 'the conditions are the whole grant'
    mapping = context.foundation['Mappings']['Tiers']
    plans = _plans()
    for tier in ('production', 'staging'):
        assert mapping[tier]['Prefix'] == plans[tier]['stackPrefix'] and mapping[tier]['Deployment'] == plans[tier]['deployment']
    # The only other principal is CloudWatch Logs, limited to the stack's own function log groups.
    logs = [s for s in _key_statements(context) if s['Sid'].startswith('EncryptTheStacksFunctionLogGroups')]
    assert len(logs) == 1 and 'log-group:/aws/lambda/${Prefix}-*' in json.dumps(logs[0]['Condition'])


@then("its key policy allows administration only to the pipeline's shared CloudFormation role")
def step_key_admin(context):
    admin = [s for s in _key_statements(context) if s['Sid'].startswith('AdministerBy')]
    assert len(admin) == 1
    default = context.foundation['Parameters']['PipelineServiceRoleName']['Default']
    assert default == context.pipeline['Resources']['SharedCloudFormationRole']['Properties']['RoleName']
    assert admin[0]['Principal']['AWS'] == {'Fn::Sub': 'arn:${AWS::Partition}:iam::${AWS::AccountId}:role/${PipelineServiceRoleName}'}
    actions = _as_list(admin[0]['Action'])
    assert not any(re.match(r'kms:(Encrypt|Decrypt|ReEncrypt|GenerateDataKey)', action) for action in actions), 'administration is not use'


@then('no statement of the key policy trusts the account root')
def step_no_root(context):
    assert ':root' not in json.dumps(_key_statements(context))
    for statement in _key_statements(context):
        assert statement['Effect'] == 'Allow'
        principal = json.dumps(statement['Principal'])
        assert not re.search(r'iam::[^"]*:root', principal)


@then('every Amplify data table, every other DynamoDB table, every S3 bucket, every queue and every function log group is encrypted with the shared key')
def step_encrypted(context):
    templates = context.templates
    amplify = _resources(templates, 'Custom::AmplifyDynamoDBTable')
    assert len(amplify) >= 25
    for _, key, value in amplify:
        spec = value['Properties']['sseSpecification']
        assert spec['sseEnabled'] in (True, 'true') and spec['sseType'] == 'KMS' and _is_key_reference(spec['kmsMasterKeyId']), key
    for _, key, value in _resources(templates, 'AWS::DynamoDB::Table'):
        assert _is_key_reference(value['Properties']['SSESpecification']['KMSMasterKeyId']), key
    buckets = _resources(templates, 'AWS::S3::Bucket')
    assert buckets
    for _, key, value in buckets:
        config = value['Properties']['BucketEncryption']['ServerSideEncryptionConfiguration'][0]
        assert config['ServerSideEncryptionByDefault']['SSEAlgorithm'] == 'aws:kms' and _is_key_reference(config['ServerSideEncryptionByDefault']['KMSMasterKeyID']) and config['BucketKeyEnabled'] is True, key
        assert 'papyrus-shared-staging' in json.dumps(value['Properties']['BucketName']), key
    for _, key, value in _resources(templates, 'AWS::SQS::Queue'):
        assert _is_key_reference(value['Properties']['KmsMasterKeyId']) and 'SqsManagedSseEnabled' not in value['Properties'], key
    functions = _resources(templates, 'AWS::Lambda::Function')
    groups = {value['Properties']['LogGroupName']: value for _, _, value in _resources(templates, 'AWS::Logs::LogGroup')}
    assert functions and len(groups) == len(functions)
    for _, key, value in functions:
        group = groups['/aws/lambda/' + value['Properties']['FunctionName']]
        assert _is_key_reference(group['Properties']['KmsKeyId']) and group['DeletionPolicy'] == 'Retain', key
    for _, key, value in _resources(templates, 'AWS::S3Vectors::VectorBucket', 'AWS::S3Vectors::Index'):
        assert _is_key_reference(value['Properties']['EncryptionConfiguration']['KmsKeyArn']), key


@then('no resource of the backend names a key other than the shared one')
def step_no_other_key(context):
    found = []

    def walk(node, where):
        if isinstance(node, dict):
            for name, value in node.items():
                if name in ('KMSMasterKeyID', 'KmsMasterKeyId', 'KmsKeyId', 'KmsKeyArn', 'kmsMasterKeyId', 'kmsKeyArn') or (name == 'KeyId'):
                    found.append((where, name, value))
                walk(value, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for name, template in context.templates.items():
        walk(template.get('Resources', {}), name)
    assert found
    others = [item for item in found if not _is_key_reference(item[2])]
    assert not others, others[:3]
    parameter = context.templates[next(name for name in context.templates if '.nested.' not in name)]['Parameters'][KEY_PARAMETER]
    assert parameter['Type'] == 'AWS::SSM::Parameter::Value<String>' and parameter['Default'] == '/papyrus/shared/staging/kms-key-arn'


@then('the backend names exactly which resources could not take the key')
def step_names_the_gaps(context):
    gaps = context.facts['resourcesThatCannotTakeTheKey']
    assert len(gaps) >= 4
    text = DOC.read_text()
    for gap in gaps:
        assert gap['resource'] in text, f"docs/shared-stack.md does not list: {gap['resource']}"


# --- the boundary and the deny ----------------------------------------------------------------------------------------------------------


@then('every role has the staging boundary policy and a path that starts with "{path}"')
def step_roles(context, path):
    roles = _resources(context.templates, 'AWS::IAM::Role')
    assert len(roles) >= 70
    for _, key, value in roles:
        properties = value['Properties']
        assert properties['Path'].startswith(path), key
        assert 'policy/papyrus-shared-staging-boundary' in json.dumps(properties['PermissionsBoundary']), key
        assert any(policy['PolicyName'] == 'papyrus-shared-staging-key-use' for policy in properties['Policies']), key


def _boundary_statements(context):
    boundary = next(value for value in context.foundation['Resources'].values() if value['Type'] == 'AWS::IAM::ManagedPolicy')
    return _statements(boundary['Properties']['PolicyDocument'])


@then('the boundary allows actions only on resources tagged with the staging deployment or named with the staging prefix')
def step_boundary(context):
    context.foundation = _foundation()
    deployment = {'Fn::FindInMap': ['Tiers', {'Ref': 'Tier'}, 'Deployment']}
    assert context.foundation['Mappings']['Tiers']['staging']['Deployment'] == 'shared-staging'
    for statement in _boundary_statements(context):
        assert statement['Effect'] == 'Allow'
        if statement['Sid'].startswith('NoResourceLevelPermission'):
            continue
        condition = statement.get('Condition', {}).get('StringEquals', {})
        tagged = condition.get('aws:ResourceTag/anthus:deployment') == deployment or condition.get('aws:RequestTag/anthus:deployment') == deployment
        resources = [json.dumps(resource) for resource in _as_list(statement['Resource'])]
        named = bool(resources) and all('${Prefix}' in resource or '${SsmName}' in resource for resource in resources)
        assert tagged or named, statement['Sid']
        assert tagged != named or statement['Sid'] == 'ActOnResourcesNamedWithThisStacksPrefix'


@then('the few actions with no resource-level permission are listed one by one in the boundary')
def step_unscoped(context):
    exceptions = [s for s in _boundary_statements(context) if s['Sid'].startswith('NoResourceLevelPermission')]
    assert exceptions
    actions = [a for s in exceptions for a in _as_list(s['Action'])]
    assert len(actions) <= 10 and not any(a.endswith('*') for a in actions), actions
    assert len(set(actions)) == len(actions)


@given('the dedicated backend is synthesised with and without the shared-stack deny')
def step_dedicated(context):
    context.synths = _synths()
    context.with_deny = _templates(context.synths['dedicated'])
    context.without_deny = _templates(context.synths['dedicated-without-deny'])
    context.facts = _facts(context.synths['dedicated'])


def _strip_deny(template):
    copy = json.loads(json.dumps(template))
    for resource in copy.get('Resources', {}).values():
        if resource['Type'] != 'AWS::IAM::Role':
            continue
        policies = [p for p in resource['Properties'].get('Policies', []) if p['PolicyName'] != 'papyrus-deny-shared-stack']
        if policies:
            resource['Properties']['Policies'] = policies
        else:
            resource['Properties'].pop('Policies', None)
    return copy


@then('the only difference is one inline policy named "{name}" on each role outside the per-model data stacks')
def step_only_difference(context, name):
    assert sorted(context.with_deny) == sorted(context.without_deny)
    added = 0
    for file, template in context.with_deny.items():
        mine, theirs = _normalised(json.dumps(_strip_deny(template), sort_keys=True, indent=1)).splitlines(), _normalised(json.dumps(context.without_deny[file], sort_keys=True, indent=1)).splitlines()
        first = next((f'{a!r} != {b!r}' for a, b in zip(mine, theirs) if a != b), 'length')
        assert mine == theirs, f'{file}: {first}'
        model_stack = re.search(r'PapyrusCmsApi(?!AmplifyTableManager|FunctionDirectiveStack|ConnectionStack)[A-Za-z]+[0-9A-F]{8}\.nested\.template\.json$', file) and 'MessageConsoleChatResponder' not in file
        for key, resource in template.get('Resources', {}).items():
            if resource['Type'] != 'AWS::IAM::Role':
                continue
            denies = [p for p in resource['Properties'].get('Policies', []) if p['PolicyName'] == name]
            assert len(denies) == (0 if model_stack else 1), f'{file} {key}'
            added += len(denies)
    assert added >= 40, added


@then('the policy denies every action on resources tagged with a shared deployment or named with the shared prefix')
def step_deny_content(context):
    deny = context.facts['denyPolicyDocument']
    tag = next(s for s in deny['Statement'] if s['Sid'] == 'DenyTaggedSharedStackResources')
    assert tag['Effect'] == 'Deny' and tag['Action'] == ['*'] and tag['Resource'] == ['*']
    assert tag['Condition'] == {'StringEquals': {'aws:ResourceTag/anthus:deployment': ['shared-prod', 'shared-staging']}}
    named = next(s for s in deny['Statement'] if s['Sid'] == 'DenyNamedSharedStackResources')
    assert named['Action'] == ['*'] and all('papyrus-shared-' in r or 'papyrus/shared' in r for r in named['Resource'])
    for template in context.with_deny.values():
        for resource in template.get('Resources', {}).values():
            for policy in resource['Properties'].get('Policies', []) if resource['Type'] == 'AWS::IAM::Role' else []:
                if policy['PolicyName'] == 'papyrus-deny-shared-stack':
                    assert policy['PolicyDocument'] == deny


@then('no resource is added to or removed from any template')
def step_no_resource_change(context):
    for file, template in context.with_deny.items():
        assert list(template.get('Resources', {})) == list(context.without_deny[file].get('Resources', {})), file


@given("a dedicated site's app shell is synthesised with and without the shared-stack deny")
def step_shell(context):
    result = subprocess.run(['node', '--import', 'tsx', 'infra/amplify-app-shell/lib/shared-stack-deny.test.ts', '--json'], cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, env=os.environ)
    assert result.returncode == 0, result.stderr[-1500:]
    context.shell = json.loads(result.stdout.strip().splitlines()[-1])


@then('the only difference is the inline policy on each role')
def step_shell_difference(context):
    assert context.shell['sameResources'] and context.shell['onlyDifferenceIsTheDeny']
    assert context.shell['roles'] >= 3 and context.shell['rolesWithTheDeny'] == context.shell['roles']


@then("the deny is identical to the one the site backend adds")
def step_shell_same_deny(context):
    assert context.shell['denyEqualsTheBackendsDeny']


# --- reserved concurrency and alarms ---------------------------------------------------------------------------------------------------------


@then("every function of the stack has reserved concurrency taken from the settings file")
def step_reserved_concurrency(context):
    settings = _settings()['staging']['reservedConcurrency']
    owned = [value for _, _, value in _resources(context.templates, 'AWS::Lambda::Function') if 'ReservedConcurrentExecutions' in value['Properties']]
    assert len(owned) >= 15
    context.reserved = [value['Properties']['ReservedConcurrentExecutions'] for value in owned]
    for value in context.reserved:
        assert value == settings['perFunction'] or value in settings['overrides'].values()
    # What has none is CDK's and Amplify's own plumbing, which runs at deploy time only.
    for _, key, value in _resources(context.templates, 'AWS::Lambda::Function'):
        if 'ReservedConcurrentExecutions' not in value['Properties']:
            assert re.search(r'(AWS[0-9a-f]{32}|framework|LogRetention|Custom|BucketNotifications|Provider|AmplifyBranchLinker|AmplifySecretFetcher|TableManager)', key), key


@then("the reserved total does not pass the tier's limit in the settings file")
def step_total(context):
    limit = _settings()['staging']['reservedConcurrency']['tierLimit']
    assert sum(context.reserved) <= limit, (sum(context.reserved), limit)


@given('the settings file has no measured reserved concurrency for production')
def step_unmeasured(context):
    assert _settings()['production'] is None
    assert 'staging traffic' in (REPO_ROOT / 'amplify' / 'shared-stack' / 'settings.ts').read_text()


@when('the shared production backend is synthesised')
def step_synth_production(context):
    _, context.result = _synth(_shared_config('production'))


@then('synthesis fails naming the production reserved concurrency and the staging traffic it must come from')
def step_production_refused(context):
    assert context.result.returncode != 0
    assert 'production' in context.result.stderr and 'reserved concurrency' in context.result.stderr and 'staging traffic' in context.result.stderr, context.result.stderr[-1500:]


@then('it has alarms on function errors, function throttles and function concurrency against the reserved share')
def step_function_alarms(context):
    context.alarms = [value['Properties'] for _, _, value in _resources(context.templates, 'AWS::CloudWatch::Alarm')]
    assert context.alarms
    reserved = {value['Properties']['FunctionName']: value['Properties']['ReservedConcurrentExecutions'] for _, _, value in _resources(context.templates, 'AWS::Lambda::Function') if 'ReservedConcurrentExecutions' in value['Properties']}
    share = _settings()['staging']['alarms']['concurrencyShareOfReserved']
    by_name = {alarm['AlarmName']: alarm for alarm in context.alarms}
    assert len(by_name) == len(context.alarms), 'alarm names are unique'
    for function, count in reserved.items():
        suffix = function.removeprefix('papyrus-shared-staging-')
        for kind in ('errors', 'throttles', 'concurrency'):
            assert f'papyrus-shared-staging-{kind}-{suffix}' in by_name, (kind, function)
        assert by_name[f'papyrus-shared-staging-concurrency-{suffix}']['Threshold'] == max(1, math.ceil(count * share)), function


@then('it has alarms on AppSync errors, DynamoDB throttles and the projection dead-letter queue')
def step_other_alarms(context):
    names = [a['AlarmName'] for a in context.alarms]
    for kind in ('appsync-5xx', 'appsync-4xx', 'dynamodb-throttles', 'projection-dlq'):
        assert any(n.startswith(f'papyrus-shared-staging-{kind}-') for n in names), kind


@then('the edge purge-count alarm is created as soon as the stack has a distribution')
def step_purge(context):
    assert not any('-purged-paths-' in a['AlarmName'] for a in context.alarms), 'there is no distribution yet'
    result = _node('-e', 'import { App, Stack } from "aws-cdk-lib"; import { Template } from "aws-cdk-lib/assertions";'
                         'import { addSharedStackAlarms } from "./amplify/shared-stack/alarms"; import { sharedTierPlan } from "./amplify/shared-stack/names"; import { sharedStackSettings } from "./amplify/shared-stack/settings";'
                         'const stack = new Stack(new App(), "S"); addSharedStackAlarms(stack, sharedTierPlan("staging"), sharedStackSettings("staging"), { functions: [], appSyncApiId: "a", tableNames: [], distributionId: "E1" });'
                         'console.log(JSON.stringify(Object.values(Template.fromStack(stack).toJSON().Resources).map((r: any) => r.Properties.AlarmName)))')
    assert result.returncode == 0, result.stderr[-1500:]
    assert any('-purged-paths-' in name for name in json.loads(result.stdout.strip().splitlines()[-1]))


@then('every alarm name starts with the staging prefix')
def step_alarm_prefix(context):
    assert all(a['AlarmName'].startswith('papyrus-shared-staging-') for a in context.alarms)
    assert not any('AlarmActions' in a for a in context.alarms), 'the default-bus listener sends them (docs/operator-alerts.md)'


# --- the budget ----------------------------------------------------------------------------------------------------------------------------------


@then('it creates one monthly budget filtered on the tag "{tag}" with the stack\'s own deployment value')
def step_budget(context, tag):
    budgets = [value for value in context.foundation['Resources'].values() if value['Type'] == 'AWS::Budgets::Budget']
    assert len(budgets) == 1
    data = budgets[0]['Properties']['Budget']
    assert data['TimeUnit'] == 'MONTHLY' and data['BudgetType'] == 'COST'
    flat = json.dumps(data['CostFilters'])
    assert f'user:{tag}$' in flat and 'Deployment' in flat
    assert data['BudgetLimit']['Amount'] == {'Ref': 'MonthlyBudgetUsd'}
    plans = _plans()
    for stack in _stacks_config()['stacks']:
        if stack.get('group') == 'shared':
            plan = plans['staging' if 'staging' in stack['name'] else 'production']
            assert stack['tags'][tag] == plan['deployment'] and stack['parameters']['Tier'] == ('staging' if 'staging' in stack['name'] else 'production')
            assert stack['parameters']['MonthlyBudgetUsd'].isdigit()


@then("the budget alerts the operator's alarm mailbox read from SSM, never an address in Git")
def step_budget_mailbox(context):
    parameter = context.foundation['Parameters']['AlertEmail']
    assert parameter['Type'] == 'AWS::SSM::Parameter::Value<String>' and parameter['NoEcho'] is True
    monitoring = stack_deploy.parse_template((REPO_ROOT / 'infra' / 'monitoring' / 'papyrus-monitoring.yaml').read_text())
    assert parameter['Default'] == monitoring['Parameters']['AlarmEmailParameter']['Default'], 'the same mailbox papyrus-monitoring alarms use'
    assert not re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', FOUNDATION.read_text()), 'no address in the template'
    budget = next(value for value in context.foundation['Resources'].values() if value['Type'] == 'AWS::Budgets::Budget')
    for notification in budget['Properties']['NotificationsWithSubscribers']:
        assert all(subscriber['Address'] == {'Ref': 'AlertEmail'} for subscriber in notification['Subscribers'])
