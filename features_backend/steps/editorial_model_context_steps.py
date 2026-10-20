import asyncio
import copy
import json

from behave import given, when, then

from papyrus_content.editorial_context import resolve_editorial_context
from papyrus_content.editorial_model_context import ContextualDecisionModel, CONTEXT_HASHES


@given('current synthetic publication doctrine and two independent desks')
def editorial_database(context):
    from procedures.newsroom.tests.test_editorial_context import Records
    context.editorial_database = Records()
    context.editorial_database.records['NewsroomSection']['business'] = {
        'id': 'business', 'editorialMission': 'Business mission', 'editorialPolicy': 'BUSINESS_ONLY_POLICY'}
    context.editorial_requests = []
    from decision_flywheel.batched_classification import batch_request
    class Capture:
        async def classify_many(self, configs, target, training, **kwargs):
            context.editorial_requests.append(batch_request(configs, target, training)[0])
    def resolve():
        pack = resolve_editorial_context(context.editorial_database, publication={'key': 'example'},
                                         endpoint='https://example.invalid/graphql', section_id='science')
        return {'fit-science': pack}
    context.editorial_model = ContextualDecisionModel(Capture(), resolve)


@when('a classification request is prepared for the science desk')
def prepare_editorial_request(context):
    from decision_flywheel import Item
    from decision_flywheel.classifier_config import ClassifierConfig
    from decision_flywheel.models import DecisionTask
    context.editorial_source = Item('synthetic', {'text': 'Synthetic candidate'})
    context.editorial_prepared = context.editorial_model.prepare(context.editorial_source)
    context.editorial_configs = {'fit-science': ClassifierConfig(DecisionTask('decision', ('yes', 'no'), 'Relevant?'))}
    asyncio.run(context.editorial_model.classify_many(context.editorial_configs, context.editorial_prepared, {'fit-science': ()}))


@then('its request contains publication and science policy without business policy')
def scoped_editorial_request(context):
    text = json.dumps(context.editorial_requests[-1])
    assert 'Distinguish evidence and inference' in text and 'Check replication' in text
    assert 'BUSINESS_ONLY_POLICY' not in text


@when('the current publication policy is updated in the database')
def update_editorial_database(context):
    context.editorial_database.records['Item']['editorial-doctrine-policy'][-1]['body'] = ['UPDATED_DATABASE_POLICY']


@then('the old prepared request is refused before model transmission')
def stale_editorial_request(context):
    before = len(context.editorial_requests)
    try:
        asyncio.run(context.editorial_model.classify_many(context.editorial_configs, context.editorial_prepared, {'fit-science': ()}))
    except ValueError as error:
        assert 'changed' in str(error)
    else:
        raise AssertionError('stale policy reached the model')
    assert len(context.editorial_requests) == before


@then('a fresh request contains the updated policy and a different context identity')
def refreshed_editorial_request(context):
    fresh = context.editorial_model.prepare(context.editorial_source)
    assert fresh.values[CONTEXT_HASHES] != context.editorial_prepared.values[CONTEXT_HASHES]
    asyncio.run(context.editorial_model.classify_many(context.editorial_configs, fresh, {'fit-science': ()}))
    assert 'UPDATED_DATABASE_POLICY' in json.dumps(context.editorial_requests[-1])
