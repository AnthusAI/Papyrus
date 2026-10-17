"""Disposable review boundaries. No real session, provider or source is used."""
from contextlib import ExitStack
from pathlib import Path
from threading import Lock
from unittest.mock import patch
import hashlib
import json

import httpx
from decision_flywheel import Cyclotron
from decision_flywheel.batched_classification import BatchedAnswers
from decision_flywheel.embedded_cyclotron import ClassifierSpec, CyclotronDefinition
from decision_flywheel.models import DecisionResult
from decision_flywheel.priming import HTTPTransformer, PrimingService
from decision_flywheel.publication_lab import (PublicationAccess, PublicationActor, PublicationBinding,
    PublicationError, PublicationLab, HTTPPublicationClient, create_publication_host)
from decision_flywheel.publication_records import PublicationRecords
from decision_flywheel.publication_steering import PublicationSteering
from decision_flywheel.web_store import WebStore
from papyrus_content.curation_host import (CurationContext, EmbeddedPublicationTransport,
    GuardedPrimingService, RemotePrimingTransport, RemotePublicationTransport, create_curation_host)
from papyrus_content.priming_curation import PapyrusPrimingCuration
from papyrus_content.priming_http import CurationJobs, create_transformer_app
from papyrus_content.publication_bff import PublicationBFF, PublicationSelection

ACCOUNTS = ('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222')
PUBLICATION = 'synthetic-threat-intelligence'
BINDING = 'review-binding-1'
ITEM = {'id': 'synthetic-reference-1', 'values': {'title': 'Synthetic reference for publication review',
        'text': 'Synthetic evidence for a deliberate human scope judgment.',
        'abstract': 'This fixture is not a real source or a model evaluation.',
        'source_uri': 'https://example.invalid/paper'}}


class OfflineModel:
    model_identity = 'explicit-offline-curation-review-fixture'
    def __init__(self):
        self.calls = 0

    async def classify_many(self, configs, target, training, **kwargs):
        self.calls += 1
        return BatchedAnswers({cid: {'decision': DecisionResult('publish', {'publish': .8, 'not publish': .2})}
                               for cid in configs}, 'synthetic-provider', {}, 1)


class OfflineCuration:
    """Actual Papyrus preparation with only external boundaries substituted."""
    def __init__(self):
        self.lock = Lock()
        self.processor = PapyrusPrimingCuration(corpus={'key': 'offline-review', 'name': 'Offline review',
            'path': 'offline-review', 's3Prefix': 'corpora/offline-review'},
            classifier_id='editorial', publication_name='Synthetic publication')

    def prepare(self, inputs, previous, feedback):
        if previous is None and not str(inputs.get('url', '')).startswith('https://example.invalid/'):
            raise ValueError('Offline review accepts example.invalid fixture URLs only')
        research = previous.get('processing_path') == 'research' if previous else 'paper' in inputs['url']
        title = 'Synthetic paper extracted from URL' if research else 'Synthetic web source prepared from URL'
        abstract = 'Synthetic source text prepared by the real Papyrus curation orchestration; external extraction and generation are fixtures.'
        from papyrus_content import reference_url_text as extraction
        from papyrus_newsroom import reference_curation_signals as signals
        with self.lock, ExitStack() as stack:
            stack.enter_context(patch.object(extraction, 'resolve_source_site_enrichment', return_value={
                'pluginKey': 'offline-fixture', 'canonicalSourceUri': 'https://example.invalid/paper.pdf' if research else 'https://example.invalid/web',
                'metadata': {'abstract': abstract}, 'identifiers': {}, 'sourceVariants': {}}))
            stack.enter_context(patch.object(extraction, '_download_source_attachment_from_uri', return_value=b'%PDF synthetic source'))
            stack.enter_context(patch.object(extraction, '_extract_url_text', return_value={'text': abstract, 'markdown': abstract,
                'title': title, 'sourceKind': 'pdf' if research else 'web', 'contentType': 'application/pdf' if research else 'text/html',
                'structured': {'authors': [], 'citations': [], 'summary': {}} if research else None,
                'grobid': {}, 'method': 'offline-fixture', 'attempts': []}))
            stack.enter_context(patch.object(extraction, '_filter_article_text', return_value={'status': 'ok', 'text': abstract, 'warnings': [], 'spanCount': 1}))
            stack.enter_context(patch.object(extraction, '_plan_grobid_citation_graph_records', return_value={'records': [], 'referenceRecords': [],
                'authorsParsed': 0, 'authorsLinked': 0, 'citationsParsed': 0, 'citationsUpserted': 0, 'citationsSkippedLowConfidence': 0,
                'citationRelationsCreated': 0, 'warnings': []}))
            stack.enter_context(patch.object(signals, 'estimate_tokens', return_value=16))
            for name, value in [('generate_title_from_reference_text', {'title': title}),
                                ('generate_subtitle_from_reference_text', {'subtitle': 'Synthetic subtitle'}),
                                ('generate_summary_from_reference_text', {'summary': abstract})]:
                stack.enter_context(patch.object(signals, name, return_value={**value, 'promptVersion': 'offline-fixture', 'mapReduce': {}}))
            return self.processor.prepare(inputs, previous, feedback)


class OfflineEvaluator:
    """Steering receipt/ownership is real; optimization result is a fixture."""
    output_id = 'editorial'
    def __init__(self, engine):
        self.engine = engine
        self.calls = 0

    @property
    def active_fingerprint(self):
        return self.engine.wheels[self.output_id].active.fingerprint

    async def execute(self, action, payload):
        if action != 'evaluate':
            raise ValueError('Offline review does not promote a model')
        self.calls += 1
        fingerprint = hashlib.sha256(json.dumps(payload['proposal'], sort_keys=True).encode()).hexdigest()
        return {'trial_fingerprint': fingerprint, 'improved': False, 'promoted': False,
                'reason': 'Synthetic evaluator boundary; no paid model or production promotion.'}


class JsonPeer:
    def __init__(self, app):
        self.app = app

    async def post(self, path, **kwargs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://offline-peer.test') as client:
            return await client.post(path, **kwargs)


class PublicationPeer:
    def __init__(self, app, account_id):
        self.app, self.account_id = app, account_id

    async def command(self, publication, operation, payload):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://offline-peer.test') as client:
            return await HTTPPublicationClient(client, account_id=self.account_id).command(publication, operation, payload)


class Workspace:
    def __init__(self, directory, account):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.account = account
        self.model = OfflineModel()
        definition = CyclotronDefinition('offline-reference-review', (
            ClassifierSpec('editorial', ('publish', 'not publish'), 'Publish for this publication?', positive_label='publish'),
            ClassifierSpec('sibling', ('publish', 'not publish'), 'Publish for the sibling publication?', positive_label='publish')),
            seed='offline-review', optimize_every=100)
        self.engine = Cyclotron.open(directory / 'engine', definition, self.model)
        self.catalog = WebStore(directory / 'catalog.sqlite3')
        for key in ('sources', 'bindings', 'records'):
            self.catalog.save_item_list(key, key)
        self.catalog.upsert_list_items('sources', [{**ITEM, 'occurred_at': '2026-01-01T00:00:00Z'}])
        bindings = (PublicationBinding(PUBLICATION, ('editorial',), BINDING),
                    PublicationBinding('synthetic-sibling', ('sibling',), BINDING))
        for binding in bindings:
            self.catalog.upsert_list_items('bindings', [{'id': binding.publication_id, 'values': {
                'accountId': account, 'publicationId': binding.publication_id, 'revision': BINDING,
                'outputs': list(binding.outputs)}, 'occurred_at': '2026-01-01T00:00:00Z'}])
        self.records = PublicationRecords(self.catalog, account_id=account, source_lists={'sources'}, binding_list='bindings', record_list='records')
        self.evaluator = OfflineEvaluator(self.engine)
        steering = PublicationSteering(self.records, {'editorial': self.evaluator}, owner_execution=self.engine.execution, allow_evaluation=True)
        self.lab = PublicationLab(self.engine, account_id=account, bindings=bindings, records=self.records, steering=steering)
        self.examples = WebStore(directory / 'priming.sqlite3')
        self.list_id = 'publication-examples-' + account
        self.examples.save_item_list(self.list_id, 'Accepted synthetic reference examples')
        schema = {'type': 'object', 'properties': {name: {'type': 'string'} for name in (
            'text', 'title', 'abstract', 'source_uri', 'domain', 'published_at', 'ingestion_rationale')},
            'required': ['text', 'title', 'abstract'], 'additionalProperties': False}
        self.examples.save_classifier('editorial', 'Explicit publication judgment', {'question': 'Publish this reference?',
            'classes': [{'label': 'publish'}, {'label': 'not publish'}], 'item_schema': schema})
        self.jobs = CurationJobs(directory / 'jobs.sqlite3', OfflineCuration())
        transformer = create_transformer_app(self.jobs, authorize=lambda _: True)

        def transform(request):
            async def call():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=transformer), base_url='http://127.0.0.1') as client:
                    result = await client.request(request.method, request.url.path, content=request.content, headers=request.headers)
                    return httpx.Response(result.status_code, headers=result.headers, content=result.content)
            import asyncio
            return asyncio.run(call())

        self.transform_client = httpx.Client(transport=httpx.MockTransport(transform))
        self.priming = PrimingService(self.examples, transformers=[HTTPTransformer('papyrus', 'Papyrus reference preparation',
            'http://127.0.0.1', ({'name': 'url', 'label': 'Source URL', 'required': True},), allow_local=True)], client=self.transform_client)

    async def seed(self):
        if not self.engine.decision_log():
            actor = PublicationActor(self.account, 'fixture-seed', frozenset({(PUBLICATION, 'decide')}))
            await self.lab.command(actor, PUBLICATION, 'decide', {'bindingRevision': BINDING, 'item': ITEM,
                'context': {'sourceRef': self.records.reference('sources', ITEM['id'], 1).to_json(),
                            'bindingRef': self.records.reference('bindings', PUBLICATION, 1).to_json()}})

    def close(self):
        self.transform_client.close()
        self.priming.close()
        self.engine.close()


class ReviewAuthority:
    """Explicit session/grant fixture, never a production token issuer."""
    def __init__(self, directory):
        self.workspaces = {account: Workspace(Path(directory) / account, account) for account in ACCOUNTS}
        self.account, self.mode, self.allowed = ACCOUNTS[0], 'embedded', True

    @property
    def selection(self):
        return PublicationSelection(self.account, 'synthetic-editor', PUBLICATION, BINDING)

    def context(self, request=None, *, pinned=None, mode=None):
        original = pinned or self.selection
        workspace = self.workspaces[original.account_id]

        async def authorize(capability):
            if not self.allowed:
                raise PublicationError('synthetic session has signed out', 401)
            if self.selection != original:
                raise PublicationError('original synthetic session selection changed', 409, code='account_changed')
            if capability not in ('read', 'review', 'steer'):
                raise PublicationError('explicit synthetic publication grant absent', 403)
            return original

        async def access(connection, publication, capability):
            await authorize(capability)
            actor = PublicationActor(original.account_id, original.person_id,
                frozenset((PUBLICATION, cap) for cap in ('read', 'review', 'steer')))
            return PublicationAccess(workspace.lab, actor)

        bff = PublicationBFF(resolve_selection=lambda _: original, resolve_access=access)
        selected_mode = mode or self.mode
        if selected_mode == 'embedded':
            publication = EmbeddedPublicationTransport(bff, request)
            priming = GuardedPrimingService(workspace.priming, workspace.engine.execution)
        else:
            remote = create_publication_host(bff)
            publication = RemotePublicationTransport(PublicationPeer(remote, original.account_id))
            peer = create_curation_host(lambda _: self.context(pinned=original, mode='embedded'))
            priming = RemotePrimingTransport(JsonPeer(peer), original)
        return CurationContext(original, selected_mode, authorize, publication, priming, workspace.list_id,
            ({'id': 'editorial', 'revision': 1},), ('read', 'review', 'steer'),
            workspace.records.reference('bindings', PUBLICATION, 1).to_json())

    def proof(self):
        return {account: {'operationalLabels': len(workspace.engine.labels()),
                         'acceptedExamples': len(workspace.examples.snapshot_items(workspace.list_id)),
                         'modelFixtureCalls': workspace.model.calls, 'steeringFixtureCalls': workspace.evaluator.calls}
                for account, workspace in self.workspaces.items()}

    def close(self):
        for workspace in self.workspaces.values():
            workspace.close()
