import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from papyrus_content.editorial_context import build_context
from papyrus_content.editorial_model_context import ContextualDecisionModel


def context(section=None, policy='PUBLICATION_RULE'):
    entries = [{'scope': 'publication', 'kind': 'policy', 'text': policy, 'source': {'id': 'policy-v1'}}]
    if section:
        entries.append({'scope': 'section', 'kind': 'policy', 'text': section.upper() + '_RULE', 'source': {'id': section}})
    return build_context({'key': 'example', 'tenantId': None}, {'sectionId': section}, entries, mode='cloud')


def test_native_batched_request_receives_current_scoped_policy_and_keeps_other_desk_out():
    from decision_flywheel import Item
    from decision_flywheel.models import DecisionTask
    from decision_flywheel.classifier_config import ClassifierConfig
    from decision_flywheel.batched_classification import batch_request
    captured = []
    class Capture:
        async def classify_many(self, configs, target, training, **kwargs):
            captured.append(batch_request(configs, target, training)[0])
    current = {'fit-a': context('a'), 'fit-b': context('b')}
    model = ContextualDecisionModel(Capture(), lambda: copy.deepcopy(current))
    config = ClassifierConfig(DecisionTask('decision', ('yes', 'no'), 'Choose.'), 'Learned rubric')
    source = Item('source', {'text': 'Synthetic candidate'})
    prepared = model.prepare(source)
    asyncio.run(model.classify_many({'fit-a': config, 'fit-b': config}, prepared, {'fit-a': (), 'fit-b': ()}))
    scopes = captured[0]['state']['classifiers']
    assert 'PUBLICATION_RULE' in scopes['fit-a']['rubric'] and 'A_RULE' in scopes['fit-a']['rubric']
    assert 'B_RULE' not in scopes['fit-a']['rubric'] and 'A_RULE' not in scopes['fit-b']['rubric']
    assert 'Learned rubric' in scopes['fit-a']['rubric']
    current['fit-a'] = context('a', 'UPDATED_RULE')
    assert model.prepare(source).values != prepared.values
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(model.classify_many({'fit-a': config}, prepared, {'fit-a': ()}))
    assert len(captured) == 1


def test_missing_or_local_context_stops_classification_before_model_call():
    from decision_flywheel import Item
    class Forbidden:
        async def classify_many(self, *args, **kwargs):
            raise AssertionError('model called')
    model = ContextualDecisionModel(Forbidden(), lambda: {})
    with pytest.raises(ValueError, match='context'):
        model.prepare(Item('source', {'text': 'Synthetic'}))


def test_policy_update_invalidates_actual_cyclotron_stable_decision(tmp_path):
    from decision_flywheel import Cyclotron, ClassifierSpec, CyclotronDefinition, Item
    from decision_flywheel.adapters.jev import JevAdapter
    requests = []
    class Client:
        def system_one(self, **request):
            requests.append(request)
            return SimpleNamespace(answers={key: {'choice': 'yes', 'probabilities': {'yes': 0.9, 'no': 0.1}}
                                            for key in request['questions']}, model='synthetic', usage={})
    current = [context()]
    model = ContextualDecisionModel(JevAdapter(Client()), lambda: {'relevant': copy.deepcopy(current[0])})
    definition = CyclotronDefinition('synthetic-policy', (ClassifierSpec('relevant', ('yes', 'no'), 'Relevant?'),))
    engine = Cyclotron.open(tmp_path / 'engine', definition, model)
    source = Item('same-source', {'text': 'Synthetic candidate'})
    try:
        first = asyncio.run(engine.decide(model.prepare(source)))
        repeated = asyncio.run(engine.decide(model.prepare(source)))
        assert first.decision_id == repeated.decision_id and len(requests) == 1
        assert 'PUBLICATION_RULE' in json.dumps(requests[0]['questions'])
        current[0] = context(policy='UPDATED_DATABASE_RULE')
        changed = asyncio.run(engine.decide(model.prepare(source)))
        assert changed.decision_id != first.decision_id and len(requests) == 2
        assert 'UPDATED_DATABASE_RULE' in json.dumps(requests[-1]['questions'])
    finally:
        engine.close()


def policy(key, scope, guidance):
    return dict(id=scope + '#' + key, policyKey=key, scope=scope, version=1, title=key,
                guidance=guidance, severity='warn', enabled=True,
                detectors=[{'id': 'judge', 'lane': 'classifier', 'scope': 'sentence',
                            'question': {'type': 'noul', 'instructions': 'Is this compliant?'},
                            'violation': {'answer': 'no'}, 'threshold': 0.8}])


def test_actual_limatus_check_and_rewrite_prompts_receive_doctrine_and_rule_overlay():
    from papyrus_content.editorial_checks import Services, check_editorial, suggest_rewrite
    from limatus.classifier_lane import DecisionAnswers
    calls, prompts = [], []
    current = [context('a')]
    rows = [policy('shared', 'publication', 'BASE_RULE'), policy('shared', 'a', 'OVERRIDE_RULE'),
            policy('addition', 'a', 'ADDED_RULE'), policy('other', 'b', 'OTHER_DESK_RULE')]
    store = SimpleNamespace(list_policies=lambda: copy.deepcopy(rows), get_settings=lambda: None,
                            list_feedback=lambda: [], get_editorial_context=lambda section: copy.deepcopy(current[0]))
    class Decision:
        async def ask(self, state, questions, model):
            calls.append(json.dumps(questions))
            return DecisionAnswers({name: {'noul': 0.9}
                                    for name in questions}, 1)
    class Generator:
        def generate(self, **kwargs):
            prompts.append(kwargs['user_prompt'])
            return {'options': [{'replacement': 'Synthetic replacement.', 'rationale': 'Clearer.',
                                 'factVerificationRequired': False, 'unresolvedQuestions': []}]}
    services = Services(store, decision_model=Decision(), generator=Generator())
    check_editorial({'body': 'Synthetic sentence.', 'section': 'a'}, services)
    suggest_rewrite({'body': 'Synthetic sentence.', 'section': 'a', 'selection': {'start': 0, 'end': 19}}, services)
    assert calls and prompts
    for text in [calls[-1], prompts[-1]]:
        assert 'PUBLICATION_RULE' in text and 'A_RULE' in text
        assert 'OTHER_DESK_RULE' not in text and 'B_RULE' not in text
    assert 'OVERRIDE_RULE' in prompts[-1] and 'ADDED_RULE' in prompts[-1] and 'BASE_RULE' not in prompts[-1]
    version = services.last_check_request['pack']['version']
    current[0] = context('a', 'UPDATED_RULE')
    check_editorial({'body': 'Synthetic sentence.', 'section': 'a'}, services)
    assert services.last_check_request['pack']['version'] != version
    assert 'UPDATED_RULE' in calls[-1]


@pytest.mark.parametrize('fault', ['denied', 'publication', 'section', 'tenant', 'fingerprint', 'ambiguous'])
def test_private_graphql_context_refuses_denied_or_wrong_scope(fault, monkeypatch):
    from papyrus_content.editorial_checks import GraphQLEditorialStore
    from papyrus_content.editorial_context import _digest
    monkeypatch.delenv('PAPYRUS_TENANT_ID', raising=False)
    seen = []
    def execute(query, variables):
        seen.append(query)
        if fault == 'denied':
            raise PermissionError('not authorized')
        if 'CanonicalEditorialPublication' in query:
            rows = [{'id': 'knowledge-corpus-example', 'name': 'Example', 'role': 'canonical'}]
            return {'listKnowledgeCorporaByRoleAndName': {'items': rows * (2 if fault == 'ambiguous' else 1), 'nextToken': None}}
        pack = context('b' if fault == 'section' else 'a')
        if fault == 'publication': pack['publication']['key'] = 'other'
        if fault == 'tenant': pack['publication']['tenantId'] = 'other'
        pack['contextHash'] = _digest({k: v for k, v in pack.items() if k not in ('contextHash', 'resolvedAt')})
        if fault == 'fingerprint': pack['text'] += 'tampered'
        return {'getEditorialContext': json.dumps(pack)}
    with pytest.raises((PermissionError, ValueError)):
        GraphQLEditorialStore(execute).get_editorial_context('a')
    assert len(seen) == (1 if fault in ('denied', 'ambiguous') else 2)


def test_missing_context_stops_both_edit_operations_before_provider():
    from papyrus_content.editorial_checks import Services, check_editorial, suggest_rewrite
    def denied(section):
        raise PermissionError('private context denied')
    store = SimpleNamespace(get_settings=lambda: None, get_editorial_context=denied)
    for operation in (check_editorial, suggest_rewrite):
        with pytest.raises(PermissionError):
            operation({'body': 'Synthetic.', 'section': 'a'}, Services(store, decision_model=None, generator=None))


def test_graphql_edit_context_is_reloaded_and_bound_to_backend_publication(monkeypatch):
    from papyrus_content.editorial_checks import GraphQLEditorialStore
    monkeypatch.delenv('PAPYRUS_TENANT_ID', raising=False)
    current, seen = [context('a')], []
    def execute(query, variables):
        seen.append(variables)
        if 'CanonicalEditorialPublication' in query:
            return {'listKnowledgeCorporaByRoleAndName': {'items': [
                {'id': 'knowledge-corpus-example', 'name': 'Example', 'role': 'canonical'}], 'nextToken': None}}
        assert variables == {'publicationKey': 'example', 'sectionId': 'a'}
        return {'getEditorialContext': json.dumps(current[0])}
    store = GraphQLEditorialStore(execute)
    first = store.get_editorial_context('a')
    current[0] = context('a', 'UPDATED_RULE')
    second = store.get_editorial_context('a')
    assert first['contextHash'] != second['contextHash'] and len(seen) == 4
