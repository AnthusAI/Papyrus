import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from papyrus_content.editorial_context import resolve_editorial_context


class Records:
    def __init__(self):
        self.corpora = [dict(id='knowledge-corpus-example', name='Example', role='canonical')]
        self.records = {
            'Item': {
                'editorial-doctrine-mission': [dict(id='mission-v2', lineageId='mission', versionNumber=2, versionState='current', type='doctrine', status='private', body=['Current mission'])],
                'editorial-doctrine-policy': [dict(id='policy-v1', lineageId='policy', versionNumber=1, versionState='superseded', type='doctrine', status='private', body=['Old policy']), dict(id='policy-v2', lineageId='policy', versionNumber=2, versionState='current', type='doctrine', status='private', body=['Distinguish evidence and inference'])],
            },
            'NewsroomSection': {'science': dict(id='science', updatedAt='2026-10-18', editorialMission='Explain research', editorialPolicy='Use primary sources', assignmentGuidance='Check replication', killCriteria='Unsupported claims')},
            'Assignment': {'a1': dict(id='a1', sectionKey='science', itemLineageId='story', summary='Investigate', metadata=json.dumps({'sectionPolicies':['Old snapshot']}))},
        }
        self.stories = [dict(id='story-v2', lineageId='story', versionNumber=2, versionState='current', section='science')]

    def list_by_index(self, index, key):
        if index == 'knowledgeCorporaByRoleAndName': return copy.deepcopy(self.corpora)
        if index == 'itemBySlug': return copy.deepcopy(self.records['Item'].get(key, []))
        if index == 'modelAttachmentsByOwnerRoleAndSortKey': return []
        if index == 'itemsByLineageAndVersion': return copy.deepcopy(self.stories if key == 'story' else [])
        raise AssertionError(index)

    def get_record(self, kind, key): return copy.deepcopy(self.records.get(kind, {}).get(key))


class EditorialContextTests(unittest.TestCase):
    def resolve(self, **kwargs):
        return resolve_editorial_context(Records(), endpoint='https://example.invalid/graphql', **kwargs)

    def test_current_revisions_and_one_shared_text(self):
        pack = self.resolve(assignment_id='a1')
        self.assertIn('Distinguish evidence and inference', pack['text'])
        self.assertIn('Check replication', pack['text'])
        self.assertNotIn('Old policy', pack['text'])
        self.assertNotIn('Old snapshot', pack['text'])
        self.assertEqual(pack['scope']['storyLineageId'], 'story')
        self.assertEqual(pack['sources'][1]['versionNumber'], 2)
        self.assertTrue(pack['warnings'])
        self.assertEqual(pack['sourceMode'], 'cloud')

    def test_scope_conflict_is_error(self):
        with self.assertRaisesRegex(ValueError, 'section'):
            self.resolve(assignment_id='a1', section_id='business')

    def test_missing_required_policy_is_error(self):
        client = Records(); client.records['Item']['editorial-doctrine-policy'] = []
        with self.assertRaisesRegex(ValueError, 'policy'):
            resolve_editorial_context(client, endpoint='https://example.invalid')

    def test_denied_read_does_not_become_empty_policy(self):
        class Denied(Records):
            def list_by_index(self, *args): raise PermissionError('denied')
        with self.assertRaisesRegex(PermissionError, 'denied'):
            resolve_editorial_context(Denied(), endpoint='https://example.invalid')

    def test_required_policy_is_not_truncated_for_budget(self):
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.resolve(max_characters=10)

    def test_publication_identity_changes_hash(self):
        first = self.resolve()
        client = Records(); client.corpora[0].update(id='knowledge-corpus-other', name='Other')
        other = resolve_editorial_context(client, publication_key='other', endpoint='https://other.invalid')
        self.assertNotEqual(first['contextHash'], other['contextHash'])

    def test_publication_binding_rejects_wrong_or_ambiguous_backend(self):
        for corpora in ([], [dict(id='knowledge-corpus-other')], [dict(id='knowledge-corpus-example')] * 2):
            client = Records(); client.corpora = corpora
            with self.assertRaisesRegex(ValueError, 'publication'):
                resolve_editorial_context(client, endpoint='https://example.invalid')

    def test_tenant_binding_is_explicit_for_policy_story_and_section(self):
        for kind in ('policy', 'story', 'section'):
            client = Records()
            record = {'policy':client.records['Item']['editorial-doctrine-policy'][-1],
                      'story':client.stories[-1], 'section':client.records['NewsroomSection']['science']}[kind]
            record['tenantId'] = 'other'
            with self.assertRaisesRegex(ValueError, 'tenant'):
                resolve_editorial_context(client, endpoint='https://example.invalid', assignment_id='a1')

    def test_configured_tenant_cannot_consume_unscoped_records(self):
        client = Records(); client.tenant_id = 'example'
        with self.assertRaisesRegex(ValueError, 'tenant'):
            resolve_editorial_context(client, endpoint='https://example.invalid')

    def test_missing_section_is_not_an_empty_intentional_section(self):
        with self.assertRaisesRegex(ValueError, 'section'):
            self.resolve(section_id='absent')

    def test_ambiguous_current_versions_fail(self):
        client = Records(); client.records['Item']['editorial-doctrine-policy'].append(dict(client.records['Item']['editorial-doctrine-policy'][-1], id='other-current'))
        with self.assertRaisesRegex(ValueError, 'current'):
            resolve_editorial_context(client, endpoint='https://example.invalid')

    def test_optional_doctrine_reports_a_missing_mission_instead_of_failing(self):
        # PPY-2c4b56: the editorial check asks for optional doctrine; nobody else does.
        client = Records(); client.records['Item']['editorial-doctrine-mission'] = []
        with self.assertRaisesRegex(ValueError, 'Publication mission: expected exactly one current record, found 0'):
            resolve_editorial_context(client, endpoint='https://example.invalid')
        pack = resolve_editorial_context(client, endpoint='https://example.invalid', optional_publication_doctrine=True)
        self.assertEqual(pack['missingPublicationDoctrine'], ['mission'])
        self.assertEqual([(entry['scope'], entry['kind']) for entry in pack['entries']], [('publication', 'policy')])

    def test_optional_doctrine_with_one_current_mission_is_unchanged(self):
        default = self.resolve()
        optional = self.resolve(optional_publication_doctrine=True)
        self.assertNotIn('missingPublicationDoctrine', optional)
        self.assertEqual(optional['contextHash'], default['contextHash'])

    def test_optional_doctrine_still_rejects_ambiguous_missions(self):
        client = Records(); client.records['Item']['editorial-doctrine-mission'].append(dict(client.records['Item']['editorial-doctrine-mission'][0], id='mission-other'))
        with self.assertRaisesRegex(ValueError, 'found 2'):
            resolve_editorial_context(client, endpoint='https://example.invalid', optional_publication_doctrine=True)

    def test_publication_comes_from_the_hosted_canonical_corpus(self):
        pack = resolve_editorial_context(Records(), endpoint='https://example.invalid/graphql')
        self.assertEqual(pack['publication']['key'], 'example')
        self.assertEqual(pack['publication']['name'], 'Example')
        self.assertEqual(pack['publication']['corpusId'], 'knowledge-corpus-example')

    def test_requested_publication_is_only_an_assertion_about_the_backend(self):
        resolve_editorial_context(Records(), publication_key='example', endpoint='https://example.invalid')
        with self.assertRaisesRegex(ValueError, 'publication'):
            resolve_editorial_context(Records(), publication_key='another', endpoint='https://example.invalid')

    def test_section_overlays_come_from_backend_records_without_any_steering_file(self):
        from unittest.mock import patch
        import papyrus_content.editorial_context as module
        client = Records()
        client.records['NewsroomSection']['distinctive'] = dict(id='distinctive', editorialMission='Backend mission overlay', editorialPolicy='Backend policy overlay')
        with tempfile.TemporaryDirectory() as empty_root, patch.dict(os.environ, {'PAPYRUS_ROOT': empty_root}), \
                patch('papyrus_content.graphql_authoring.create_authoring_client', return_value=(client, None)), \
                patch.object(module, 'graphql_endpoint', return_value='https://example.invalid'), patch.object(module, 'load_dotenv'):
            self.assertEqual(os.listdir(empty_root), [])
            pack = module.configured_context(section_id='distinctive')
        self.assertIn('Backend mission overlay', pack['text'])
        self.assertIn('Backend policy overlay', pack['text'])
        self.assertEqual(pack['publication']['key'], 'example')
        self.assertEqual(pack['sourceMode'], 'cloud')

    def test_no_runtime_reader_of_steering_or_seed_files_remains(self):
        source = (Path(__file__).resolve().parents[3] / 'src/papyrus_content/editorial_context.py').read_text()
        for forbidden in ('papyrus-steering', 'publication-doctrine.yml', 'newsroom-sections.yml', 'yaml'):
            self.assertNotIn(forbidden, source)


class EditorialWorkerTests(unittest.TestCase):
    def test_dispatch_uses_resolver_and_replaces_untrusted_supplied_text(self):
        from unittest.mock import patch
        from papyrus_content.editorial_context import prepare_editorial_worker_input
        payload = {'assignment_item_id':'a1', 'editorial_context_text':'untrusted'}
        with patch('papyrus_content.editorial_context.graphql_endpoint', return_value='https://example.invalid'):
            result = prepare_editorial_worker_input(Records(), 'assignments.run-research', payload)
        self.assertIn('Distinguish evidence', result['editorial_context_text'])
        self.assertEqual(payload['editorial_context_text'], 'untrusted')
        self.assertTrue(result['editorial_context_hash'])

    def test_unrelated_procedure_does_not_load_editorial_policy(self):
        from papyrus_content.editorial_context import prepare_editorial_worker_input
        self.assertEqual(prepare_editorial_worker_input(None, 'references.summarize', {'x':1}), {'x':1})

    def test_missing_policy_stops_dispatch_before_model_execution(self):
        from unittest.mock import patch
        from papyrus_content.cloud_procedures import start_cloud_procedure_run
        client = Records(); client.records['Item']['editorial-doctrine-policy'] = []
        with patch('papyrus_content.editorial_context.graphql_endpoint', return_value='https://example.invalid'), patch('papyrus_content.cloud_procedures.get_cloud_procedure_definition_by_key') as lookup:
            with self.assertRaisesRegex(ValueError, 'policy'):
                start_cloud_procedure_run(client=client, alias='assignments.run-research', actor_label='Agent', title='test', summary='test', input_payload={'assignment_item_id':'a1'})
            lookup.assert_not_called()

    def test_compactor_cannot_drop_required_policy(self):
        from unittest.mock import patch
        from biblicus.api import ContextPackBuildBlocksResponse
        from papyrus_content.biblicus_runner import BiblicusRunner
        from papyrus_newsroom.newsroom import _build_biblicus_block_context_pack
        pack = ContextPackBuildBlocksResponse(text='evidence only', total_tokens=2, total_characters=13)
        runner = patch.object(BiblicusRunner, 'from_environment', return_value=Mock(build_context_pack_from_blocks=Mock(return_value=pack)))
        with runner:
            with self.assertRaisesRegex(ValueError, 'required editorial context'):
                _build_biblicus_block_context_pack(blocks=[{'block_id':'policy','section':'doctrine','required':True,'text':'Publication policy'}], profile_key='reporting', max_tokens=20)

    def test_runtime_exposes_same_context_resolver(self):
        from unittest.mock import patch
        from papyrus_newsroom import tactus_runtime
        # Invoke the registered host operation without a model or Lua runtime.
        with patch('papyrus_newsroom.newsroom.papyrus_editorial_context', return_value={'text':'resolved','contextHash':'hash'}) as resolve:
            result = tactus_runtime.API_METHODS[('editorial','context')]({'assignment_id':'a1'})
            self.assertEqual(result['text'], 'resolved')
            resolve.assert_called_once_with(assignment_id='a1',section_id='',story_lineage_id='')


class AssignmentAttachmentTests(unittest.TestCase):
    def test_same_generated_contract_as_graphql_including_unicode_and_hashes(self):
        from unittest.mock import patch
        fixture = json.loads((Path(__file__).parent / 'fixtures/editorial_context_contract.json').read_text())
        client = Records(); client.records = fixture['records']; client.stories = fixture['stories']; client.corpora = fixture['corpora']
        original = client.list_by_index
        client.list_by_index = lambda index, key: fixture['attachments'] if index == 'modelAttachmentsByOwnerRoleAndSortKey' else original(index, key)
        with patch('papyrus_content.model_attachments.download_attachment_buffer', return_value=b'Investigate primary evidence'):
            pack = resolve_editorial_context(client, endpoint='https://example.invalid/graphql', assignment_id='a1')
        pack.pop('resolvedAt')
        self.assertEqual(pack, fixture['pack'])

    def test_attachment_without_storage_and_wrong_owner_fail_explicitly(self):
        from unittest.mock import patch
        class Attached(Records):
            def list_by_index(self, index, key):
                if index == 'modelAttachmentsByOwnerRoleAndSortKey':
                    return [dict(id='brief', ownerKind='assignment', ownerId='a1', role='assignment_brief', status='ready')]
                return super().list_by_index(index, key)
        with patch('papyrus_content.model_attachments.download_attachment_buffer', return_value=None):
            with self.assertRaisesRegex(ValueError, 'storage path'):
                resolve_editorial_context(Attached(), endpoint='https://example.invalid', assignment_id='a1')
        client = Attached()
        original = client.list_by_index
        def wrong_owner(index, key):
            rows = original(index, key)
            if index == 'modelAttachmentsByOwnerRoleAndSortKey': rows[0]['ownerId'] = 'another'
            return rows
        client.list_by_index = wrong_owner
        with self.assertRaisesRegex(ValueError, 'owner'):
            resolve_editorial_context(client, endpoint='https://example.invalid', assignment_id='a1')

    def test_private_assignment_instructions_are_resolved_and_provenanced(self):
        from unittest.mock import patch
        class Attached(Records):
            def list_by_index(self, index, key):
                if index == 'modelAttachmentsByOwnerRoleAndSortKey':
                    return [dict(id='instructions-v1', ownerKind='assignment', ownerId='a1', role='assignment_instructions', status='ready')]
                return super().list_by_index(index,key)
        with patch('papyrus_content.model_attachments.download_attachment_buffer', return_value=b'Investigate the competing explanations'):
            pack = resolve_editorial_context(Attached(), endpoint='https://example.invalid', assignment_id='a1')
        self.assertIn('Investigate the competing explanations',pack['text'])
        self.assertIn('instructions-v1',[source['id'] for source in pack['sources']])

    def test_attachment_read_failure_is_explicit(self):
        from unittest.mock import patch
        class Attached(Records):
            def list_by_index(self,index,key):
                if index == 'modelAttachmentsByOwnerRoleAndSortKey':return [dict(id='brief',ownerKind='assignment',ownerId='a1',role='assignment_brief',status='ready')]
                return super().list_by_index(index,key)
        with patch('papyrus_content.model_attachments.download_attachment_buffer',side_effect=PermissionError('private attachment denied')):
            with self.assertRaisesRegex(PermissionError,'denied'):
                resolve_editorial_context(Attached(),endpoint='https://example.invalid',assignment_id='a1')
