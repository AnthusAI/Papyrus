"""The DMARC report record (PPY-6bcae9): template-level checks of the record and the pipeline roles.

Nothing here calls AWS, DNS or a mailbox. The report address is the placeholder dmarc-reports@example.test: the real address is an SSM parameter a person creates once.
"""
import importlib.util
import json
import re
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / 'infra' / 'pipeline'
TEMPLATE = REPO_ROOT / 'infra' / 'email' / 'papyrus-dmarc.yaml'
SPECS = [REPO_ROOT / 'features_backend' / 'references' / 'dmarc-report-record.feature', Path(__file__)]
DMARC_STACK = re.compile(r'stack/papyrus-dmarc-\*/\*')

_spec = importlib.util.spec_from_file_location('stack_deploy', PIPELINE / 'stack_deploy.py')
stack_deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stack_deploy)


def _template() -> dict:
    return stack_deploy.parse_template(TEMPLATE.read_text())


def _stacks() -> list[dict]:
    return json.loads((PIPELINE / 'stacks.json').read_text())['stacks']


def _dmarc_stack(domain: str) -> dict:
    found = [stack for stack in _stacks() if stack['name'].startswith('papyrus-dmarc-') and stack['parameters'].get('DomainName') == domain]
    assert len(found) == 1, (domain, [stack['name'] for stack in _stacks()])
    return found[0]


def _roles_text() -> str:
    return (PIPELINE / 'papyrus-stack-pipeline.yaml').read_text()


def _role_block(name: str) -> str:
    text = _roles_text()
    start = text.index(f'\n  {name}:\n')
    following = re.search(r'\n  [A-Z][A-Za-z]+:\n', text[start + 1:])
    return text[start:start + 1 + following.start()] if following else text[start:]


@given('the DMARC template')
def dmarc_template(context):
    context.template = _template()


@when('it is rendered for the domain "{domain}" with the report address "{address}"')
def render(context, domain, address):
    resource = context.template['Resources']['DmarcRecord']['Properties']
    text = resource['ResourceRecords'][0]
    assert isinstance(text, dict) and 'Fn::Sub' in text, text
    values = {'DomainName': domain, 'ReportAddress': address, 'DmarcPolicy': context.template['Parameters']['DmarcPolicy']['Default']}
    render_sub = lambda template: re.sub(r'\$\{(\w+)\}', lambda match: values[match.group(1)], template)  # noqa: E731
    context.record = {'Type': resource['Type'], 'Name': render_sub(resource['Name']['Fn::Sub']), 'Text': render_sub(text['Fn::Sub']).strip('"')}


@then('the record is a TXT record named "{name}"')
def record_named(context, name):
    assert context.record['Type'] == 'TXT' and context.record['Name'] == name, context.record


@then('the record reads "{text}"')
def record_reads(context, text):
    assert context.record['Text'] == text, context.record


@then('the policy parameter defaults to "{policy}"')
def policy_default(context, policy):
    assert context.template['Parameters']['DmarcPolicy']['Default'] == policy


@then('the policy parameter allows only "none", "quarantine" and "reject"')
def policy_allowed(context):
    assert context.template['Parameters']['DmarcPolicy']['AllowedValues'] == ['none', 'quarantine', 'reject']


@then('the report address parameter is an SSM parameter value, so CloudFormation reads it at deploy time')
def address_is_ssm(context):
    assert context.template['Parameters']['ReportAddress']['Type'] == 'AWS::SSM::Parameter::Value<String>'
    assert context.template['Parameters']['ReportAddress'].get('NoEcho') is True


@then('its default is a parameter name that starts with a slash, not an address')
def address_default(context):
    default = context.template['Parameters']['ReportAddress']['Default']
    assert default.startswith('/') and '@' not in default, default


@then("the template says a mailbox on another domain needs an authorization record in that domain's zone")
def says_authorization(context):
    description = context.template['Parameters']['ReportAddress']['Description']
    assert '_report._dmarc' in description and "that domain's zone" in description, description


@then('the template creates no authorization record')
def no_authorization(context):
    assert list(context.template['Resources']) == ['DmarcRecord'], list(context.template['Resources'])


@given('the release stack list')
def release_configuration(context):
    context.stacks = _stacks()


@then('there is a DMARC stack for the domain "{first}" and one for the domain "{second}"')
def dmarc_stacks(context, first, second):
    context.domains = [first, second]
    for domain in context.domains:
        _dmarc_stack(domain)


@then('both use the DMARC template and look up the zone "{zone}"')
def both_use_template(context, zone):
    for domain in context.domains:
        stack = _dmarc_stack(domain)
        assert stack['template'] == 'infra/email/papyrus-dmarc.yaml', stack
        assert stack['lookups'] == {'HostedZoneId': {'hostedZone': zone}}, stack


@then('both start at the policy "{policy}"')
def both_policy(context, policy):
    assert all(_dmarc_stack(domain)['parameters']['DmarcPolicy'] == policy for domain in context.domains)


@then('both name the report address by its SSM parameter, never by an address')
def both_name_parameter(context):
    for domain in context.domains:
        name = _dmarc_stack(domain)['parameters']['ReportAddress']
        assert name.startswith('/') and '@' not in name, name


@given('the release roles template')
def roles_template(context):
    context.roles = _roles_text()


@then('the plan role may read the DMARC stacks')
def plan_reads(context):
    assert DMARC_STACK.search(_role_block('PlanRole')), 'PlanRole'


@then('the deploy role may drive the DMARC stacks only through the service role')
def deploy_drives(context):
    block = _role_block('DeployRole')
    assert len(DMARC_STACK.findall(block)) == 2, 'the stacks are named once for driving a change set and once for creating it'
    creating = block[block.index('CreateChangeSetsOnlyThroughTheServiceRole'):]
    assert DMARC_STACK.search(creating) and 'cloudformation:RoleArn' in creating[:creating.index('HandOverTheServiceRoleToCloudFormationOnly')]


@then('the deploy role may resolve the report address parameter under /papyrus/')
def deploy_resolves(context):
    block = _role_block('DeployRole')
    statement = block[block.index('ResolveSsmParameterTypedParameters'):]
    assert 'ssm:GetParameters' in statement[:400] and 'parameter/papyrus/*' in statement[:400]
    default = _template()['Parameters']['ReportAddress']['Default']
    assert default.startswith('/papyrus/'), default


@given('the DMARC template, its stacks and its specs')
def files_in_scope(context):
    context.files = [TEMPLATE, PIPELINE / 'stacks.json', *SPECS]


@then('none contains an email address other than the example.test placeholder')
def no_real_address(context):
    pattern = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
    for path in context.files:
        found = [address for address in pattern.findall(path.read_text()) if not address.endswith('@example.test')]
        assert not found, (path.name, found)
