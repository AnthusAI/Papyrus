"""What an editor saves in Administration (mission, policy, section fields) is what both model boundaries receive."""
import asyncio
from types import SimpleNamespace

from papyrus_content.editorial_context import resolve_editorial_context
from papyrus_content.editorial_model_context import CONTEXT_HASHES, classification_model, editing_pack
from papyrus_content.site_cyclotron import section_fit_classifier_id
from procedures.newsroom.tests.test_editorial_context import Records

ENDPOINT = 'https://example.invalid/graphql'


def saved_through_administration():
    """Records shaped exactly as the newsroom Administration writes them (lib/doctrine.ts, Sections panel)."""
    database = Records()
    database.endpoint = ENDPOINT
    def doctrine(slug, text):
        return dict(id=f'item-{slug}-v1', lineageId=f'item-{slug}', versionNumber=1, versionState='current',
                    type='doctrine', status='private', typeStatus='doctrine#private', slug=slug, body=[text],
                    updatedAt='2026-10-20T00:00:00Z')
    database.records['Item']['editorial-doctrine-mission'] = [doctrine('editorial-doctrine-mission', 'ADMIN_MISSION_TEXT')]
    database.records['Item']['editorial-doctrine-policy'] = [doctrine('editorial-doctrine-policy', 'ADMIN_POLICY_TEXT')]
    database.records['NewsroomSection']['science'] = dict(
        id='science', updatedAt='2026-10-20T00:00:00Z', editorialMission='ADMIN_SECTION_MISSION',
        editorialPolicy='ADMIN_SECTION_POLICY', assignmentGuidance='ADMIN_SECTION_GUIDANCE', killCriteria='ADMIN_KILL_CRITERIA')
    return database


def test_admin_values_reach_the_effective_context_and_the_copy_edit_pack():
    database = saved_through_administration()
    context = resolve_editorial_context(database, endpoint=ENDPOINT, section_id='science')
    for value in ('ADMIN_MISSION_TEXT', 'ADMIN_POLICY_TEXT', 'ADMIN_SECTION_MISSION', 'ADMIN_SECTION_POLICY',
                  'ADMIN_SECTION_GUIDANCE', 'ADMIN_KILL_CRITERIA'):
        assert value in context['text']
    store = SimpleNamespace(list_policies=lambda: [], context_mode='cloud',
                            get_editorial_context=lambda section: resolve_editorial_context(database, endpoint=ENDPOINT, section_id=section))
    pack = editing_pack(store, 'science', {})
    assert 'ADMIN_POLICY_TEXT' in pack['guidance'] and 'ADMIN_SECTION_POLICY' in pack['guidance']
    assert pack['version'].endswith(context['contextHash'])


def test_admin_values_reach_the_cyclotron_request_with_the_same_hash_and_no_model_call():
    from decision_flywheel import Item
    from decision_flywheel.batched_classification import batch_request
    from decision_flywheel.classifier_config import ClassifierConfig
    from decision_flywheel.models import DecisionTask
    database = saved_through_administration()
    expected = resolve_editorial_context(database, endpoint=ENDPOINT, section_id='science')
    requests = []
    class Capture:  # builds the provider request; never calls a provider
        async def classify_many(self, configs, target, training, **kwargs):
            requests.append(batch_request(configs, target, training)[0])
    model = classification_model(Capture(), database, {}, [{'id': 'science'}])
    science = section_fit_classifier_id('science')
    prepared = model.prepare(Item('source', {'text': 'Synthetic'}))
    assert prepared.values[CONTEXT_HASHES][science] == expected['contextHash']
    config = ClassifierConfig(DecisionTask('decision', ('yes', 'no'), 'Relevant?'))
    asyncio.run(model.classify_many({science: config}, prepared, {science: ()}))
    rubric = requests[0]['state']['classifiers'][science]['rubric']
    for value in ('ADMIN_MISSION_TEXT', 'ADMIN_POLICY_TEXT', 'ADMIN_SECTION_POLICY', 'ADMIN_KILL_CRITERIA'):
        assert value in rubric
