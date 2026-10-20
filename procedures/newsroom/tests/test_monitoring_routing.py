"""Native SDK + actual HTTP/embedded adapters; providers are explicitly offline."""
import asyncio
from dataclasses import replace

import httpx
import pytest
from decision_flywheel import Cyclotron
from decision_flywheel.batched_classification import BatchedAnswers
from decision_flywheel.embedded_cyclotron import ClassifierSpec, CyclotronDefinition
from decision_flywheel.models import DecisionResult
from decision_flywheel.publication_lab import (
    EmbeddedPublicationClient, HTTPPublicationClient, PublicationActor,
    PublicationBinding, PublicationLab, create_publication_app,
    PublicationAccess,
)
from papyrus_content.curation_host import EmbeddedPublicationTransport
from papyrus_content.publication_bff import PublicationBFF, PublicationSelection
from papyrus_content.monitoring_routing import PublicationRoute, RoutingFailure, route_discovery
from papyrus_content.site_cyclotron import site_classifier_specs

PUBLICATIONS = ('papyrus', 'threat-intelligence', 'anthus', 'pilobolus')
ITEM = {'id': 'synthetic-hn-source-revision-1', 'values': {
    'title': 'Synthetic shared source', 'source_uri': 'https://example.invalid/source',
    'text': 'Explicitly synthetic contract input; never live evaluation evidence.'}}
SECTIONS = [{'id': name, 'title': name.title(), 'enabled': enabled, 'sortOrder': order}
            for order, (name, enabled) in enumerate((('research', True), ('commentary', True), ('retired', False)))]
SECTION_SPECS = tuple(site_classifier_specs(SECTIONS))
SECTION_OUTPUTS = tuple(spec.id for spec in SECTION_SPECS)


class OfflineModel:
    model_identity = 'monitor-two-layer-offline-contract'
    def __init__(self): self.calls, self.excluded = [], set()
    async def classify_many(self, configs, target, training, **kwargs):
        self.calls.append((tuple(configs), target.id))
        answers = {}
        for cid, config in configs.items():
            labels = tuple(config.task.labels)
            label = 'exclude' if cid in self.excluded else labels[0]
            answers[cid] = {'decision': DecisionResult(label, {
                value: .8 if value == label else .2 / (len(labels) - 1) for value in labels})}
        return BatchedAnswers(answers, 'offline-contract', {}, 1)


def setup(tmp_path):
    shared_model = OfflineModel()
    definition = CyclotronDefinition('synthetic-shared-publication-router', tuple(
        ClassifierSpec(pub, ('include', 'exclude'), f'Synthetic relevance for {pub}?', positive_label='include')
        for pub in PUBLICATIONS))
    shared = Cyclotron.open(tmp_path / 'shared', definition, shared_model)
    actor = PublicationActor('synthetic-account', 'synthetic-worker', frozenset(
        (pub, cap) for pub in PUBLICATIONS for cap in ('read', 'decide')))
    lab = PublicationLab(shared, account_id=actor.account_id, bindings=tuple(
        PublicationBinding(pub, (pub,), 'remote-v1') for pub in PUBLICATIONS))
    engines, models, clients, routes = [], {}, {}, []
    for pub in PUBLICATIONS:
        models[pub] = OfflineModel()
        local = Cyclotron.open(tmp_path / pub, CyclotronDefinition('synthetic-sections-' + pub, SECTION_SPECS), models[pub])
        engines.append(local)
        local_lab = PublicationLab(local, account_id=actor.account_id, bindings=(
            PublicationBinding(pub, SECTION_OUTPUTS, 'sections-v1'),))
        selection = PublicationSelection(actor.account_id, actor.actor_id, pub, 'sections-v1')
        clients[pub] = EmbeddedPublicationTransport(PublicationBFF(
            resolve_selection=lambda _, scope=selection: scope,
            resolve_access=lambda _, p, cap, bound=local_lab: PublicationAccess(bound, actor)), None)
        routes.append(PublicationRoute(pub, 'remote-v1', pub, 'include', 'sections-v1', SECTION_OUTPUTS))
    return shared, shared_model, actor, lab, engines, models, clients, routes


def authorize(publication, layer):
    return PublicationSelection('synthetic-account', 'synthetic-worker', publication,
                                'remote-v1' if layer == 'remote' else 'sections-v1')


def test_shared_remote_request_and_integrated_multi_section_outputs(tmp_path):
    shared, model, actor, lab, engines, models, clients, routes = setup(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_publication_app(lab, authorize=lambda _: actor)),
                                     base_url='http://synthetic-lab.test') as http:
            remote = HTTPPublicationClient(http, account_id=actor.account_id)
            result = await route_discovery(remote, clients, routes, ITEM, account_id=actor.account_id, authorize=authorize)
            assert result['sharedDecisionId']
            assert len(model.calls) == 1
            assert set(model.calls[0][0]) == set(PUBLICATIONS)
            assert set(result['publications']) == set(PUBLICATIONS)
            for pub, row in result['publications'].items():
                assert set(row['relevance']['decision']['classifiers']) == {pub}
                assert set(row['sections']['decision']['classifiers']) == set(SECTION_OUTPUTS)
                assert len(SECTION_OUTPUTS) == 3  # Two enabled section fits plus the existing selector.
                assert not any('retired' in output for output in SECTION_OUTPUTS)
                assert len(models[pub].calls) == 1
            assert not shared.labels() and all(not engine.labels() for engine in engines)
    try: asyncio.run(run())
    finally:
        shared.close()
        for engine in engines: engine.close()


def test_wrong_backend_is_refused_before_any_model_call(tmp_path):
    shared, model, actor, lab, engines, models, clients, routes = setup(tmp_path)
    try:
        with pytest.raises(ValueError, match='remote HTTP'):
            asyncio.run(route_discovery(EmbeddedPublicationClient(lab, actor), clients, routes, ITEM,
                                        account_id=actor.account_id, authorize=authorize))
        assert not model.calls and all(not m.calls for m in models.values())
    finally:
        shared.close()
        for engine in engines: engine.close()


def test_changed_binding_does_not_fall_back_or_run_integrated_models(tmp_path):
    shared, model, actor, lab, engines, models, clients, routes = setup(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_publication_app(lab, authorize=lambda _: actor)),
                                     base_url='http://synthetic-lab.test') as http:
            with pytest.raises(RoutingFailure, match='remote routing') as failure:
                await route_discovery(HTTPPublicationClient(http, account_id=actor.account_id), clients,
                                      [replace(routes[0], remote_revision='stale'), *routes[1:]], ITEM,
                                      account_id=actor.account_id, authorize=authorize)
            assert 'binding' in str(failure.value.__cause__)
            assert failure.value.receipt['sharedDecisionId'] is None
            assert not model.calls and all(not m.calls for m in models.values())
    try: asyncio.run(run())
    finally:
        shared.close()
        for engine in engines: engine.close()


def test_negative_relevance_skips_only_that_publications_sections(tmp_path):
    shared, model, actor, lab, engines, models, clients, routes = setup(tmp_path)
    model.excluded.add('papyrus')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_publication_app(lab, authorize=lambda _: actor)),
                                     base_url='http://synthetic-lab.test') as http:
            result = await route_discovery(HTTPPublicationClient(http, account_id=actor.account_id), clients,
                                          routes, ITEM, account_id=actor.account_id, authorize=authorize)
            assert result['publications']['papyrus']['sections'] is None and not models['papyrus'].calls
            assert all(len(models[p].calls) == 1 for p in PUBLICATIONS if p != 'papyrus')
            assert len(model.calls) == 1 and not shared.labels()
    try: asyncio.run(run())
    finally:
        shared.close()
        for engine in engines: engine.close()


def test_split_remote_decisions_retain_partial_receipt_without_integrated_fallback(tmp_path):
    shared, model, actor, lab, engines, models, clients, routes = setup(tmp_path)
    class SplitReply(HTTPPublicationClient):
        async def command(self, publication, operation, payload):
            response = await super().command(publication, operation, payload)
            if publication == 'anthus':
                response['decision']['decisionId'] = 'different-engine-decision'
            return response
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_publication_app(lab, authorize=lambda _: actor)),
                                     base_url='http://synthetic-lab.test') as http:
            with pytest.raises(RoutingFailure) as failure:
                await route_discovery(SplitReply(http, account_id=actor.account_id), clients, routes, ITEM,
                                      account_id=actor.account_id, authorize=authorize)
            assert failure.value.stage == 'remote routing for anthus'
            assert set(failure.value.receipt['publications']) == {'papyrus', 'threat-intelligence'}
            assert 'one multi-output decision' in str(failure.value.__cause__)
            assert all(not m.calls for m in models.values())
    try: asyncio.run(run())
    finally:
        shared.close()
        for engine in engines: engine.close()
