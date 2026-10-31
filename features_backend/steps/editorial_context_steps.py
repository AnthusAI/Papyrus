from unittest.mock import patch

from behave import given, when, then

from papyrus_content.editorial_context import resolve_editorial_context, prepare_editorial_worker_input
from procedures.newsroom.tests.test_editorial_context import Records


@given('editorial records with current publication and section policies')
def editorial_records(context):
    context.editorial_records = Records()


@given('editorial records with no required publication policy')
def editorial_missing(context):
    editorial_records(context)
    context.editorial_records.records['Item']['editorial-doctrine-policy'] = []


@given('the hosted canonical corpus belongs to another publication')
def editorial_other_publication(context):
    context.editorial_records.corpora = [{'id':'knowledge-corpus-other', 'name':'Other', 'role':'canonical'}]


@given('the publication policy belongs to a tenant outside the configured scope')
def editorial_other_tenant(context):
    context.editorial_records.records['Item']['editorial-doctrine-policy'][-1]['tenantId'] = 'another'


@given('editorial records whose reads are denied')
def editorial_denied(context):
    class Denied(Records):
        def list_by_index(self, *args):
            raise PermissionError('denied')
    context.editorial_records = Denied()


def resolve(context, **kwargs):
    context.editorial_error = None
    try:
        context.editorial_pack = resolve_editorial_context(context.editorial_records, publication_key='example',
            endpoint='https://example.invalid', **kwargs)
    except (ValueError, PermissionError) as error:
        context.editorial_error = str(error)


@when('the agent resolves editorial context for assignment "{assignment}"')
def editorial_resolve(context, assignment):
    resolve(context, assignment_id=assignment)


@when('the agent requests section "{section}" for assignment "{assignment}"')
def editorial_section(context, section, assignment):
    resolve(context, assignment_id=assignment, section_id=section)


@when('the agent resolves editorial context with a budget of {budget:d} characters')
def editorial_budget(context, budget):
    resolve(context, max_characters=budget)


@then('editorial context fails with "{message}"')
def editorial_failure(context, message):
    assert context.editorial_error and message in context.editorial_error, context.editorial_error


@then('the editorial context includes the current policy and source revisions')
def editorial_current(context):
    assert context.editorial_error is None, context.editorial_error
    assert 'Distinguish evidence and inference' in context.editorial_pack['text']
    assert context.editorial_pack['sources'][1]['versionNumber'] == 2


@then('the editorial context excludes old policy snapshots')
def editorial_no_snapshot(context):
    assert 'Old snapshot' not in context.editorial_pack['text']
    assert 'Old policy' not in context.editorial_pack['text']


@when('the research worker is prepared with caller-supplied policy text')
def editorial_worker(context):
    with patch('papyrus_content.editorial_context.graphql_endpoint', return_value='https://example.invalid'):
        context.editorial_worker = prepare_editorial_worker_input(context.editorial_records,
            'assignments.run-research', {'assignment_item_id':'a1', 'editorial_context_text':'Old snapshot'})


@then('the worker receives the current resolved policy before dispatch')
def editorial_worker_current(context):
    assert 'Distinguish evidence and inference' in context.editorial_worker['editorial_context_text']
    assert 'Old snapshot' not in context.editorial_worker['editorial_context_text']
    assert context.editorial_worker['editorial_context_hash']


@given('editorial records with two current missions')
def editorial_two_missions(context):
    editorial_records(context)
    missions = context.editorial_records.records['Item']['editorial-doctrine-mission']
    context.editorial_records.records['Item']['editorial-doctrine-mission'] = missions + [dict(missions[0], id='mission-copy')]


@given('editorial records with two sections called "{name}"')
def editorial_twin_sections(context, name):
    editorial_records(context)
    sections = context.editorial_records.records['NewsroomSection']
    sections['culture-a'] = dict(id='culture-a', title=name, editorialMission='A')
    sections['culture-b'] = dict(id='culture-b', title=name, editorialMission='B')


def resolve_optionally(context, **kwargs):
    context.editorial_error = None
    with patch('papyrus_content.editorial_context.LOGGER') as logger:
        try:
            context.editorial_pack = resolve_editorial_context(context.editorial_records, publication_key='example',
                endpoint='https://example.invalid', optional_publication_doctrine=True, **kwargs)
        except (ValueError, PermissionError) as error:
            context.editorial_error = str(error)
    context.editorial_warnings = [call.args[0] % call.args[1:] for call in logger.warning.call_args_list]


@when('editorial checks resolve context optionally')
def editorial_optional(context):
    resolve_optionally(context)


@when('editorial checks resolve context optionally for section "{section}"')
def editorial_optional_section(context, section):
    resolve_optionally(context, section_id=section)


@then('the editorial context is resolved without the "{kind}" and a warning names the publication')
def editorial_without_doctrine(context, kind):
    assert context.editorial_error is None, context.editorial_error
    assert context.editorial_pack['missingPublicationDoctrine'] == [kind], context.editorial_pack
    assert any('example' in line and kind in line for line in context.editorial_warnings), context.editorial_warnings


@then('the editorial context is resolved without section guidance and a warning names the publication')
def editorial_without_section(context):
    assert context.editorial_error is None, context.editorial_error
    assert context.editorial_pack['missingSectionConfiguration'] == ['Culture Desk'], context.editorial_pack
    assert not [e for e in context.editorial_pack['entries'] if e['scope'] == 'section']
    assert any('example' in line for line in context.editorial_warnings), context.editorial_warnings
