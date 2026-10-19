"""Publication selection and authorized attachment reads through assignment context."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parents[3] / 'src'
CHECK = r'''
import json, os
from pathlib import Path
from unittest.mock import patch
from papyrus_content import env
from papyrus_newsroom import newsroom
reads = []
class Downloads:
    def create_model_attachment_download(self, attachment_id):
        if os.environ.get('DENY_ATTACHMENT_READ'):
            raise PermissionError('Attachment read denied')
        reads.append(attachment_id)
        filename = 'brief.txt' if 'assignment-brief' in attachment_id else 'instructions.txt'
        return {'downloadUrl':(env.PAPYRUS_ROOT/filename).as_uri(), 'method':'GET'}
def graphql(query, variables):
    if 'GetAssignment(' in query:
        return {'getAssignment': {'id':'assignment-one', 'summary':'Research', 'status':'open'}}
    if 'GetModelAttachment(' in query:
        attachment_id = variables['id']
        for role, filename in [('assignment-brief','brief.txt'), ('assignment-instructions','instructions.txt')]:
            if role in attachment_id:
                return {'getModelAttachment': {'id':attachment_id, 'storagePath':'newsroom/payloads/'+filename, 'status':'active', 'mediaType':'text/plain'}}
        return {'getModelAttachment':None}
    raise AssertionError(query)
with patch.object(newsroom, 'execute_graphql', side_effect=graphql), \
     patch('papyrus_content.graphql_authoring.create_authoring_client', return_value=(Downloads(), {})), \
     patch.object(newsroom.subprocess, 'run', side_effect=AssertionError('Direct S3 is not permitted for this reader')), \
     patch.object(newsroom, '_assignment_relations_for_assignment', return_value=[]), \
     patch.object(newsroom, '_assignment_doctrine_context', return_value=[]), \
     patch.object(newsroom, '_assignment_events_for_assignments', return_value=[]):
    assignment = newsroom.papyrus_get_assignment_context('assignment-one')['assignment_context']['assignment']
print(json.dumps({'root':str(newsroom.PAPYRUS_ROOT), 'contentRoot':str(env.PAPYRUS_ROOT),
    'knowledgeRoot':str(newsroom.BIBLICUS_ROOT), 'steering':str(newsroom.STEERING_CONFIG_PATH),
    'brief':assignment.get('brief'), 'instructions':assignment.get('instructions'), 'reads':reads}))
'''


@contextmanager
def publication_fixture():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root/'amplify_outputs.json').write_text(json.dumps({'storage':{'bucket_name':'selected-publication-bucket'}}))
        (root/'brief.txt').write_text('Selected brief')
        (root/'instructions.txt').write_text('Selected instructions')
        environment = dict(os.environ, PAPYRUS_ROOT=str(root), BIBLICUS_WORKDIR=str(root/'knowledge'),
                           PYTHONPATH=str(SOURCE_ROOT), PYTHONDONTWRITEBYTECODE='1', AWS_EC2_METADATA_DISABLED='true')
        yield root, environment


def read_publication_context(root, environment):
    return subprocess.run([sys.executable, '-c', CHECK], cwd=root, env=environment, text=True, capture_output=True)


def configured_publication_context():
    with publication_fixture() as (root, environment):
        completed = read_publication_context(root, environment)
        assert completed.returncode == 0, completed.stderr
        return root, json.loads(completed.stdout)


def test_assignment_text_uses_supported_download_without_direct_s3_access():
    root, result = configured_publication_context()
    assert result['instructions'] == 'Selected instructions'
    assert result['brief'] == 'Selected brief'
    assert result['reads'] == ['model-attachment-assignment-assignment-one-assignment-brief-brief',
                               'model-attachment-assignment-assignment-one-assignment-instructions-instructions']
    assert result['root'] == result['contentRoot'] == str(root)
    assert result['steering'] == str(root/'corpora/papyrus-steering.yml')


def test_configured_knowledge_work_directory_is_preserved():
    root, result = configured_publication_context()
    assert result['knowledgeRoot'] == str(root/'knowledge')


def test_denied_attachment_does_not_become_missing_guidance():
    with publication_fixture() as (root, environment):
        environment['DENY_ATTACHMENT_READ'] = '1'
        completed = read_publication_context(root, environment)
    assert completed.returncode != 0
    assert 'Attachment read denied' in completed.stderr


def test_default_root_uses_existing_content_resolution():
    environment = dict(os.environ, PYTHONPATH=str(SOURCE_ROOT), PYTHONDONTWRITEBYTECODE='1')
    environment.pop('PAPYRUS_ROOT', None)
    environment.pop('BIBLICUS_WORKDIR', None)
    completed = subprocess.run([sys.executable, '-c', 'from papyrus_content import env; from papyrus_newsroom import newsroom; assert newsroom.PAPYRUS_ROOT == env.PAPYRUS_ROOT; assert newsroom.BIBLICUS_ROOT == env.BIBLICUS_ROOT'], env=environment, cwd=SOURCE_ROOT.parent, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
