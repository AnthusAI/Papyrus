"""Editorial checks are core: on by default, configured by stored settings data, never by repo configuration."""
import json
from types import SimpleNamespace

import pytest

from papyrus_content import editorial_checks as editorial
from papyrus_content.editorial_context import build_context


def store(settings=None):
    policy = editorial.record_from_policy({
        'id': 'no-hype', 'version': 1, 'title': 'No hype', 'guidance': 'Avoid hype.', 'severity': 'warn',
        'detectors': [{'id': 'p', 'lane': 'rules', 'kind': 'phrase', 'phrases': ['game-changing']}],
    }, scope='publication', source='test')
    policy['detectors'] = json.dumps(policy['detectors'])
    context = build_context({'key': 'example'}, {'sectionId': None}, [
        {'scope': 'publication', 'kind': 'policy', 'text': 'Synthetic', 'source': {'id': 'p'}}], mode='cloud')
    return SimpleNamespace(
        get_settings=lambda: None if settings is None else {'id': 'settings', 'settings': json.dumps(settings)},
        list_policies=lambda: [policy], list_feedback=lambda: [], get_editorial_context=lambda section: context)


def services(settings=None):
    return editorial.Services(store=store(settings), decision_model=None, generator=None)


def test_checks_run_by_default_when_no_settings_record_exists():
    result = editorial.check_editorial({'body': 'A game-changing release.'}, services())
    assert [finding['policyId'] for finding in result['findings']] == ['no-hype']


def test_disabling_through_the_stored_setting_stops_checks_and_rewrites():
    off = services({'enabled': False})
    with pytest.raises(editorial.EditorialChecksDisabled):
        editorial.check_editorial({'body': 'A game-changing release.'}, off)
    with pytest.raises(editorial.EditorialChecksDisabled):
        editorial.suggest_rewrite({'body': 'x', 'selection': {'start': 0, 'end': 1}}, off)
    assert off.last_check_request is None


def test_options_come_from_the_stored_settings():
    configured = services({'classifierModel': 'stored-model', 'deadlineSeconds': 9, 'lanes': {'rules': True, 'classifier': False}})
    editorial.check_editorial({'body': 'A game-changing release.'}, configured)
    options = configured.last_check_request['options']
    assert options['classifier']['model'] == 'stored-model' and options['classifier']['deadlineSeconds'] == 9
    assert options['lanes'] == {'rules': True, 'classifier': False}


def test_enabled_again_after_the_setting_is_restored():
    assert editorial.settings_from(store({'enabled': True}))['enabled'] is True
