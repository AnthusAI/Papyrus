"""The fixed registration helper's real local planning/persistence path needs only the declared fields."""
import pathlib
import re

from papyrus_content.catalog import build_reference_catalog_registration_records
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.newsroom_summary import update_newsroom_summary_after_reference_registration
from papyrus_content.records import build_record_changes, apply_record_changes


def test_reference_registration_and_provenance_operations_fit_assignment_access(monkeypatch):
    policy = (pathlib.Path(__file__).resolve().parents[3]
              / 'amplify/functions/assignment-action/data-access.ts').read_text()
    allowed = set(re.findall(r'"((?:Query|Mutation)/fields/\w+)"', policy))
    calls = []

    class Client(PapyrusGraphQLAuthoringClient):
        def __init__(self):
            self.tenant_id = None
            self._connection = None

        def graphql(self, query, variables):
            field = re.search(r'\{\s*(\w+)\s*\(', query).group(1)
            kind = 'Mutation' if query.lstrip().startswith('mutation') else 'Query'
            operation = f'{kind}/fields/{field}'
            calls.append(operation)
            assert operation in allowed, f'Fixed helper needs an unlisted operation: {operation}'
            if field == 'createModelAttachmentUpload':
                return {field: {'uploadId': 'synthetic-upload', 'uploadUrl': 'https://example.invalid/upload',
                                'storagePath': 'newsroom/synthetic', 'requiredHeaders': {}}}
            if field == 'completeModelAttachmentUpload':
                return {field: {'status': 'active'}}
            if field.startswith('list'):
                return {field: {'items': [], 'nextToken': None}}
            if field.startswith('get'):
                return {field: None}
            return {field: {'id': (variables.get('input') or {}).get('id'), 'ok': True}}

    class UploadResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr('papyrus_content.model_attachments.urllib.request.urlopen', lambda request: UploadResponse())
    plan = build_reference_catalog_registration_records(
        {'schema_version': 1, 'items': [{'id': 'synthetic-source', 'title': 'Synthetic source',
          'source_uri': 'https://example.invalid/article', 'ingestion_rationale': 'Synthetic intake reason'}]},
        {'corpusConfig': {'key': 'example', 'name': 'Example', 'role': 'canonical'},
         'status': 'pending', 'importedAt': '2026-10-20T00:00:00Z'})
    client = Client()
    changes = build_record_changes(client, plan['records'])
    apply_record_changes(client, changes)
    update_newsroom_summary_after_reference_registration(client, changes, plan)
    assert {'Query/fields/listReferences', 'Mutation/fields/createReference',
            'Mutation/fields/createKnowledgeImportRun', 'Mutation/fields/createModelAttachmentUpload',
            'Mutation/fields/completeModelAttachmentUpload', 'Mutation/fields/updateNewsroomSummary'} <= set(calls)
    assert not any('/delete' in operation or 'EditorialPolicy' in operation or 'UserRole' in operation for operation in calls)
