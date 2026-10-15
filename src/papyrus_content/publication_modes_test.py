"""Actual Papyrus research/web projection feeds both Cyclotron deployment paths."""
import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest
from decision_flywheel import Cyclotron
from decision_flywheel.embedded_cyclotron import ClassifierSpec, CyclotronDefinition
from decision_flywheel.batched_classification import BatchedAnswers
from decision_flywheel.models import DecisionResult
from decision_flywheel.publication_lab import (PublicationLab, PublicationActor, PublicationBinding,
    EmbeddedPublicationClient, HTTPPublicationClient, create_publication_app)


class OfflineModel:
    model_identity = 'papyrus-publication-paths-offline-v1'
    def __init__(self): self.inputs=[]
    async def classify_many(self, configs, target, training, **kwargs):
        self.inputs.append(target)
        return BatchedAnswers({cid:{'decision':DecisionResult('accept' if cid=='intel' else 'reject',
            {'accept':.8 if cid=='intel' else .2,'reject':.2 if cid=='intel' else .8})} for cid in configs},
            'deterministic-offline',{},1)


@pytest.mark.parametrize('mode',['embedded','remote'])
@pytest.mark.parametrize('path',['research','web'])
def test_existing_papyrus_curation_can_be_vetted_with_explicit_publication_feedback_in_both_modes(tmp_path,monkeypatch,mode,path):
    from papyrus_newsroom import reference_curation_signals as signals
    # Tokenizer assets are another external boundary, not classifier evidence.
    monkeypatch.setattr(signals,'estimate_tokens',lambda *args,**kwargs:16)
    import socket
    def no_network(*args,**kwargs): raise AssertionError('offline contract attempted a network connection')
    monkeypatch.setattr(socket,'create_connection',no_network)
    spec=importlib.util.spec_from_file_location('publication_fixtures',Path(__file__).resolve().parents[2]/'scripts/priming-preview/fixtures.py')
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    prepared=fixtures.SyntheticCuration().prepare({'url':f'https://example.invalid/{path}','path':path},None,'')
    assert prepared['status']=='complete'
    candidate=prepared['candidate']
    assert candidate['values']['title'].startswith('Synthetic')
    assert ('scholarly abstract' if path=='research' else 'web summary') in candidate['values']['abstract']
    definition=CyclotronDefinition('papyrus-mode-contract',(
        ClassifierSpec('intel',('accept','reject'),'Accept for Threat Intelligence?'),
        ClassifierSpec('pilobolus',('accept','reject'),'Accept for Pilobolus?')))
    actor=PublicationActor('fixture-account','human-editor',frozenset((pub,action) for pub in ('threat-intelligence','pilobolus') for action in ('read','review','decide')))
    model=OfflineModel()
    async def exercise(client,engine):
        item={'id':candidate['id'],'values':candidate['values']}
        a=await client.command('threat-intelligence','decide',{'bindingRevision':'fixture-binding','item':item})
        b=await client.command('pilobolus','decide',{'bindingRevision':'fixture-binding','item':item})
        assert a['decision']['decisionId']==b['decision']['decisionId']
        prediction=a['decision']['classifiers']['intel']
        review=await client.command('threat-intelligence','review',{'bindingRevision':'fixture-binding',
            'decisionId':a['decision']['decisionId'],'classifier':'intel','predictionVersion':prediction['version'],
            'predictionFingerprint':prediction['fingerprint'],'requestId':'explicit-human-label',
            'label':'reject','explanation':'Human scope decision, distinct from extraction feedback.',
            'reasonCode':'out_of_scope'})
        assert review['review']['explanation'].startswith('Human scope decision')
        other=await client.command('pilobolus','status',{})
        assert other['classifiers']['pilobolus']['alignment']['labels']==0
        history=await client.command('threat-intelligence','history',{})
        assert history['history'][0]['item']['abstract']==candidate['values']['abstract']
        assert history['history'][0]['item']['source_uri']==candidate['values']['source_uri']
        assert len(engine.labels())==1 and len(model.inputs)==1
        assert model.inputs[0].values==candidate['values']
    async def scenario():
        with Cyclotron.open(tmp_path/'deployment-owned-fixture',definition,model) as engine:
            lab=PublicationLab(engine,account_id='fixture-account',bindings=(PublicationBinding('threat-intelligence',('intel',),'fixture-binding'),PublicationBinding('pilobolus',('pilobolus',),'fixture-binding')))
            if mode=='embedded':await exercise(EmbeddedPublicationClient(lab,actor),engine)
            else:
                app=create_publication_app(lab,authorize=lambda _:actor)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline-lab.test') as http:
                    await exercise(HTTPPublicationClient(http),engine)
    asyncio.run(scenario())
