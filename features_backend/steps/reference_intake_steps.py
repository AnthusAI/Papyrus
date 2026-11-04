import copy
import json
from behave import given, when, then
from procedures.newsroom.tests.test_reference_intake import IntakeClient, submit, payload, IDENTITY
from papyrus_content.reference_intake import IntakeError
from papyrus_content.story_reporting import link_reference_to_story, story_references
from procedures.newsroom.tests.test_story_reporting import LINEAGE


@given('an isolated publication intake backend')
def isolated(context):
    context.intake_client = IntakeClient()
    context.intake_before = copy.deepcopy(context.intake_client.tables)


def _backend_env(context):
    return getattr(context, 'intake_env', None)


@given('the backend carries a tenant and declares that it serves a single publication')
def single_publication(context):
    context.intake_env = {'PAPYRUS_TENANT_ID': 'tenant-a', 'PAPYRUS_SINGLE_PUBLICATION_BACKEND': 'true'}


@given('the backend carries a tenant and does not declare that it serves a single publication')
def undeclared(context):
    context.intake_env = {'PAPYRUS_TENANT_ID': 'tenant-a', 'PAPYRUS_SINGLE_PUBLICATION_BACKEND': ''}


@given('the backend carries a tenant and declares "{value}" for the single publication setting')
def declared_value(context, value):
    context.intake_env = {'PAPYRUS_TENANT_ID': 'tenant-a', 'PAPYRUS_SINGLE_PUBLICATION_BACKEND': value}


@when('its editor registers a reporting source')
def register(context):
    context.intake_result = submit(context.intake_client, env=_backend_env(context))


@then('the source is pending with attributable provenance')
def pending(context):
    ref = context.intake_client.tables['Reference'][context.intake_result['references'][0]['id']]
    assert ref['curationStatus'] == 'pending'
    assert ref['versionCreatedBy'] == 'user:editor-sub'
    provenance = json.loads(next(iter(context.intake_client.uploads.values())))
    assert provenance['actorSub'] == 'editor-sub'
    assert provenance['rationale'] == 'Primary reporting source'


@then('its returned record can be linked as consulted without changing the story')
def linked(context):
    c = context.intake_client
    link_reference_to_story(c, LINEAGE, context.intake_result['references'][0]['id'], role='consulted', actor='ChatGPT')
    assert story_references(c, LINEAGE)[0]['role'] == 'consulted'
    assert c.tables['Item'] == context.intake_before['Item']
    assert not c.tables.get('Message')
    assert not c.tables.get('PublishedItem')


@when('its editor repeats intake using a canonical equivalent URL')
def repeat(context):
    c = context.intake_client
    context.first_intake = submit(c)
    context.first_state = copy.deepcopy(c.tables)
    context.intake_result = submit(c, payload('HTTPS://EXAMPLE.TEST:443/report#different'))


@then('the same immutable source and provenance are returned')
def repeated(context):
    assert context.intake_result['references'] == context.first_intake['references']
    assert context.intake_client.tables == context.first_state
    assert len(context.intake_client.uploads) == 1


@when('intake is requested with a valid editor session')
def valid_editor(context):
    _attempt(context, payload(), copy.deepcopy(IDENTITY))


@when('intake is requested with an editor session whose token has the "{claim}" claim')
def tenant_token(context, claim):
    identity = copy.deepcopy(IDENTITY)
    identity['claims'][claim] = 'tenant-a'
    _attempt(context, payload(), identity)


@then('the refusal names the setting that declares a single publication')
def names_setting(context):
    assert 'PAPYRUS_SINGLE_PUBLICATION_BACKEND=true' in context.intake_refusal


def _attempt(context, data, identity):
    try:
        submit(context.intake_client, data, identity, env=_backend_env(context))
    except IntakeError as error:
        context.intake_rejected = True
        context.intake_refusal = str(error)
    else:
        raise AssertionError('Unauthorized intake succeeded')


@when('intake is requested with {violation}')
def rejected(context, violation):
    identity = copy.deepcopy(IDENTITY)
    data = payload()
    if violation == 'no identity': identity = {}
    if violation == 'a reader role': identity['claims']['cognito:groups'] = ['reader']
    if violation == 'another issuer': identity['claims']['iss'] = 'https://other/pool'
    if violation == 'another publication': data['publicationEndpoint'] = 'https://other/graphql'
    if violation == 'another corpus': data['corpusId'] = 'foreign-corpus'
    if violation == 'a caller selected tenant': data['tenantId'] = 'foreign'
    _attempt(context, data, identity)


@then('no intake data is written')
def untouched(context):
    assert context.intake_rejected
    assert context.intake_client.tables == context.intake_before
    assert not context.intake_client.uploads
