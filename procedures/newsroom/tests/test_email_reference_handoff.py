"""Only explicitly selected imported References enter the cloud prediction queue."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from papyrus_content.email_reference_handoff import queue_email_reference
from papyrus_content.reference_intake_validation import IntakeError
from papyrus_content.monitoring_view import TableViewStore, Forbidden
from papyrus_content.monitoring_router import RouterStore, CyclotronClient, run_router, validate_router_config, item_id_for
from procedures.newsroom.tests.test_email_submission_intake import shared_fixture, AccountCyclotron
from procedures.newsroom.tests.email_submission_fixture import accept_held_email, collect_email
from procedures.newsroom.tests.test_reference_intake import IDENTITY, ENV


def fixture():
    f = shared_fixture()
    f.event['Records'][0]['ses']['receipt']['dmarcVerdict']['status'] = 'FAIL'
    assert collect_email(f)['status'] == 'pending_review'
    accept_held_email(f)
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


@pytest.mark.parametrize("initially_not_ready", [False, True])
def test_selected_negative_prediction_is_delivered_once_without_procedures(initially_not_ready):
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
    def run(now=2000000000):
        return run_router(RouterStore(f.table), 'email-publication', now=now,
            task='email-references', source_ids=[queued['sourceId']], cyclotron=client, appsync=lambda _: AppSync(), deliver=deliver,
            context_receipt=lambda *_: {}, start_procedure=started.append)
    if initially_not_ready:
        model.post_override['publication'] = (409, {'detail': 'publication criteria are pending'})
        waiting = run()
        assert waiting['counts']['parked'] == 1
        assert not delivered
        disc = f.table.by_prefix('DISC#')[0]
        assert disc['gsi1pk'] == 'ROUTING#email-publication#email-references'
        assert queue(store, request, endpoint) == queued
        # No ordinary backfill entry exists; retries use only the selected job.
        assert all(not park.get('items') for park in f.table.by_prefix('PARK#'))
        model.post_override.clear()
    result = run(2000010000)
    assert result['counts']['delivered'] == 1, result
    assert delivered[0]['label'] == 'exclude'
    assert not started
    run(2000010010)
    assert len(delivered) == 1 and len(model.posts()) == (2 if initially_not_ready else 1)


def test_legacy_branded_tracking_receipt_resolves_imports_and_queues_only_clean_article():
    import json
    from papyrus_content.monitoring_view import monitoring_email_submission, monitoring_email_resolve_article_link
    from papyrus_content.reference_intake import intake_email_submission_references
    from procedures.newsroom.tests.test_reference_intake import IntakeClient
    f, store, request, endpoint = fixture()
    receipt = store.get(request['receiptId'])
    receipt['ttl'] = 4_000_000_000
    f.table.put_item(Item=receipt)
    tracker = 'https://news.example.org/ss/c/u001.synthetic-Recipient.Route'
    details = f.table.by_prefix('EMAILDETAIL#')
    link_row = next(row for row in details if '#LINKS#' in row['sk'])
    links = json.loads(link_row['json'])
    links[0] = {'url': tracker, 'title': 'Article'}  # Legacy receipt: no resolutionStatus.
    link_row['json'] = json.dumps(links)
    f.table.put_item(Item=link_row)
    original = deepcopy(f.table.by_prefix('EMAILDETAIL#'))
    client = IntakeClient()
    corpus_id = 'knowledge-corpus-publication'
    f.router['publications'][0]['corpusId'] = corpus_id
    f.table.put_item(Item=f.router)
    client.tables['KnowledgeCorpus'][corpus_id] = {'id': corpus_id}
    env = {**ENV, 'PAPYRUS_GRAPHQL_ENDPOINT': endpoint}
    def import_url(url):
        with patch.dict('os.environ', env), patch('papyrus_content.reference_intake.upload_attachment_body', client.upload):
            return intake_email_submission_references(client, {
                'receiptId': request['receiptId'], 'items': [{'candidateIndex': 0, 'source_uri': url}]
            }, IDENTITY, env=env, receipt_store=store)
    detail = monitoring_email_submission(store, groups=['editor'], site_endpoint=endpoint, receipt_id=request['receiptId'])
    assert detail['candidateLinks'][0]['resolutionStatus'] == 'unresolved'
    with pytest.raises(IntakeError):
        import_url(tracker)
    assert client.tables['Reference'] == {}
    resolved = monitoring_email_resolve_article_link(store, groups=['editor'], site_endpoint=endpoint,
        receipt_id=request['receiptId'], candidate_index=0, resolver=lambda _url: request['source_uri'])
    imported = import_url(resolved['url'])
    reference_id = imported['references'][0]['id']
    ref = client.tables['Reference'][reference_id]
    assert ref['sourceUri'] == request['source_uri'] and ref['curationStatus'] == 'pending'
    assert import_url(resolved['url'])['references'][0]['id'] == reference_id
    with pytest.raises(IntakeError):
        import_url(tracker)
    queued = queue(store, {**request, 'referenceId': reference_id}, endpoint)
    assert queue(store, {**request, 'referenceId': reference_id}, endpoint) == queued
    disc = f.table.by_prefix('DISC#')[0]
    assert disc['canonicalUrl'] == request['source_uri']
    assert disc['editorSelectedReference']['referenceId'] == reference_id
    assert len(client.tables['Reference']) == 1
    assert f.table.by_prefix('EMAILDETAIL#') == original
    assert tracker not in repr(client.uploads)
