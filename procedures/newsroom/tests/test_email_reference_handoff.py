"""Only explicitly selected imported References enter the cloud prediction queue."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from papyrus_content.email_reference_handoff import queue_email_reference
from papyrus_content.reference_intake_validation import IntakeError
from papyrus_content.monitoring_view import TableViewStore, Forbidden
from papyrus_content.monitoring_router import RouterStore, CyclotronClient, run_router, validate_router_config, item_id_for
from procedures.newsroom.tests.test_email_submission_intake import shared_fixture, AccountCyclotron
from procedures.newsroom.tests.email_submission_fixture import collect_email
from procedures.newsroom.tests.test_reference_intake import IDENTITY, ENV


def fixture():
    f = shared_fixture()
    f.event['Records'][0]['ses']['receipt']['dmarcVerdict']['status'] = 'FAIL'
    assert collect_email(f)['status'] == 'pending_review'
    store = TableViewStore(f.table, 'email-publication')
    receipt = f.table.by_prefix('EMAIL#')[0]
    request = {'receiptId': receipt['sk'], 'candidateIndex': 0, 'source_uri': 'https://example.org/alpha', 'referenceId': 'reference-selected'}
    endpoint = f.router['publications'][0]['appsyncEndpoint']
    return f, store, request, endpoint


def queue(store, request, endpoint, identity=IDENTITY):
    with patch.dict('os.environ', ENV):
        return queue_email_reference(store, request, identity, endpoint=endpoint)


def test_exact_candidate_queue_is_idempotent_and_does_not_import_or_vote():
    f, store, request, endpoint = fixture()
    first = queue(store, request, endpoint)
    before = deepcopy(f.table.items)
    assert queue(store, request, endpoint) == first
    assert f.table.items == before
    rows = f.table.by_prefix('DISC#')
    assert len(rows) == 1 and rows[0]['canonicalUrl'] == request['source_uri']
    assert rows[0]['emailDestinationPublicationIds'] == ['publication']
    assert rows[0]['emailProvenance']['sesDiagnostics']['warnings']
    assert rows[0]['editorSelectedReference']['subject'] == IDENTITY['sub']


@pytest.mark.parametrize('change', [dict(candidateIndex=99), dict(source_uri='https://other.example/story'), dict(referenceId=''), dict(receiptId='EMAIL#'+'f'*64)])
def test_invalid_exact_candidate_never_queues(change):
    f, store, request, endpoint = fixture()
    with pytest.raises((IntakeError, Forbidden)):
        queue(store, {**request, **change}, endpoint)
    assert not f.table.by_prefix('DISC#')


def test_operator_identity_cannot_queue():
    f, store, request, endpoint = fixture()
    with pytest.raises(IntakeError):
        queue(store, request, endpoint, {})
    assert not f.table.by_prefix('DISC#')


def test_selected_negative_prediction_is_delivered_once_without_procedures():
    f, store, request, endpoint = fixture()
    queued = queue(store, request, endpoint)
    class Model(AccountCyclotron):
        def http(self, method, url, headers, body, timeout):
            if url.endswith('/machine/decisions'):
                return 404, {}
            return super().http(method, url, headers, body, timeout)
    model = Model()
    model.labels[(item_id_for('email-publication', queued['sourceId']), 'publication')] = 'exclude'
    client = CyclotronClient(validate_router_config(f.router), sign=lambda *_: {}, http=model.http, sleep=lambda _: None, clock=lambda: 0)
    class AppSync:
        def get_record(self, name, ident):
            assert name == 'Reference' and ident == request['referenceId']
            return {'id': ident, 'sourceUri': request['source_uri'], 'versionState': 'current', 'corpusId': 'knowledge-corpus-publication'}
    delivered, started = [], []
    def deliver(_client, pub, disc, decision, config):
        delivered.append(decision)
        return {'referenceId': request['referenceId']}
    def run():
        return run_router(RouterStore(f.table), 'email-publication', now=2000000000,
            task='email-references', source_ids=[queued['sourceId']], cyclotron=client, appsync=lambda _: AppSync(), deliver=deliver,
            context_receipt=lambda *_: {}, start_procedure=started.append)
    result = run()
    assert result['counts']['delivered'] == 1, result
    assert delivered[0]['label'] == 'exclude'
    assert not started
    run()
    assert len(delivered) == 1 and len(model.posts()) == 1
