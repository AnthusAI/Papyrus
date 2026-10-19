import json
from behave import given, when, then
from procedures.newsroom.tests.test_newsroom_publication_root import publication_fixture, read_publication_context


@given('an explicit publication root containing storage configuration')
def selected_publication(context):
    fixture = publication_fixture()
    context.publication_root, context.publication_environment = fixture.__enter__()
    context.add_cleanup(fixture.__exit__, None, None, None)


@given('the assignment attachment download is denied')
def denied_publication_attachment(context):
    context.publication_environment['DENY_ATTACHMENT_READ'] = '1'


@when('the newsroom runtime reads the stored assignment brief and instructions')
def read_assignment_text(context):
    context.publication_completed = read_publication_context(context.publication_root, context.publication_environment)


@then('the selected publication text is returned')
def selected_text(context):
    assert context.publication_completed.returncode == 0, context.publication_completed.stderr
    result = json.loads(context.publication_completed.stdout)
    context.publication_result = result
    assert result['instructions'] == 'Selected instructions'
    assert result['brief'] == 'Selected brief'


@then('the configured knowledge work directory is preserved')
def selected_knowledge_directory(context):
    assert context.publication_result['knowledgeRoot'] == str(context.publication_root/'knowledge')


@then('the assignment context read fails with the download error')
def denied_read_failure(context):
    assert context.publication_completed.returncode != 0
    assert 'Attachment read denied' in context.publication_completed.stderr
