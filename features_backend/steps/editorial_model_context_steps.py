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
        pack = resolve_editorial_context(context.editorial_database, 
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


@when('a model request is made without choosing a model')
def request_without_model(context):
    from papyrus_content import model_defaults
    context.default_models = [
        model_defaults.DEFAULT_REFERENCE_FILTER_MODEL,
        model_defaults.DEFAULT_REFERENCE_SUMMARY_MODEL,
        model_defaults.DEFAULT_EDITORIAL_REWRITE_MODEL,
        model_defaults.DEFAULT_LLM_MODEL,
        model_defaults.DEFAULT_SMALL_LLM_MODEL,
    ]


@then('the model used for the reference filter, the reference summary, the editorial rewrite and the general and small roles is "{model}"')
def default_models_are(context, model):
    assert context.default_models == [model] * 5, context.default_models


@then('the reader extraction setup asks "{model}"')
def extraction_setup_model(context, model):
    from papyrus_content.reader_steering.extraction import ExtractionSetup
    assert ExtractionSetup.__dataclass_fields__['model_name'].default == model


@when('the priming spending gateway is read')
def priming_gateway_read(context):
    from papyrus_content import priming_provider_budget
    context.priming_gateway = priming_provider_budget


@then('the only model it admits is "{model}"')
def priming_gateway_model(context, model):
    assert context.priming_gateway.MODEL == model


@then('each request reserves its full maximum at $0.10 per million input tokens and $0.50 per million output tokens')
def priming_gateway_reservation(context):
    gateway = context.priming_gateway
    microdollars = gateway.MAX_INPUT_TOKENS * 0.10 + gateway.MAX_OUTPUT_TOKENS * 0.50
    assert gateway.RESERVATION_MICRODOLLARS == round(microdollars)


@when('the product code of the repository is read for OpenAI model identifiers')
def product_code_read(context):
    from procedures.newsroom.tests import test_luna_only_models as guard
    context.model_guard = guard
    context.other_models = {
        str(path.relative_to(guard.REPOSITORY_ROOT)): guard.other_models(path.read_text(encoding='utf-8', errors='ignore'))
        for path in guard.product_files()
    }


@then('the only language model it names is "{model}"')
def only_language_model(context, model):
    assert model == context.model_guard.LUNA
    assert not {path: models for path, models in context.other_models.items() if models}, context.other_models


@then('speech synthesis models are the only other model identifiers allowed')
def only_speech_allowed(context):
    assert set(context.model_guard.ALLOWED_MODEL_IDENTIFIERS) == {context.model_guard.LUNA, 'gpt-4o-mini-tts'}
