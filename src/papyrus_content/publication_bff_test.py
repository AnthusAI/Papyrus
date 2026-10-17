"""Papyrus BFF composes actual guarded SDK ownership with fresh host authority."""
import asyncio
from dataclasses import replace

import httpx
import pytest
from decision_flywheel import Cyclotron
from decision_flywheel.publication_lab import (PublicationAccess,PublicationActor,
    PublicationLab,PublicationError,HTTPPublicationClient,create_publication_host)
from decision_flywheel.publication_lab_test import DEFINITION,BINDINGS,ITEM,OfflineModel,review_payload
from papyrus_content.publication_bff import PublicationBFF,PublicationSelection


@pytest.mark.parametrize('mode',['embedded','remote'])
@pytest.mark.parametrize('operation',['decide','review','status','history','events'])
@pytest.mark.parametrize('change',['revoked','outage','account','person','binding'])
def test_queued_operation_reauthorizes_before_protected_reads_or_dispatch(tmp_path,mode,operation,change,monkeypatch):
    async def scenario():
        model=OfflineModel()
        with Cyclotron.open(tmp_path/'engine',DEFINITION,model) as engine:
            lab=PublicationLab(engine,account_id='account-a',bindings=BINDINGS)
            selection=PublicationSelection('account-a','person','threat-intelligence','binding-1')
            state={'selection':selection,'allowed':True,'available':True};resolved=asyncio.Event()
            actor=PublicationActor('account-a','person',frozenset(('threat-intelligence',cap) for cap in ('read','decide','review')))
            first=await lab.command(actor,'threat-intelligence','decide',{'bindingRevision':'binding-1','item':ITEM})
            async def access(*args):
                resolved.set()
                if not state['available']:raise ConnectionError('Synthetic central account outage')
                return PublicationAccess(lab,actor) if state['allowed'] else None
            bff=PublicationBFF(resolve_selection=lambda _:state['selection'],resolve_access=access)
            app=create_publication_host(bff)
            # Any protected read before reauthorization fails this test, even if no write follows.
            reads=[]
            for name in ('decision','decision_log','status'):
                original=getattr(engine,name)
                def read(*args,_name=name,_original=original,**kwargs):
                    reads.append(_name)
                    assert state['allowed'] and state['available'] and state['selection']==selection
                    return _original(*args,**kwargs)
                monkeypatch.setattr(engine,name,read)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline.test') as http:
                payload=review_payload(first) if operation=='review' else ({'bindingRevision':'binding-1','item':{**ITEM,'id':'queued-target'}} if operation=='decide' else ({'after':0,'limit':10} if operation=='events' else {}))
                async def command():
                    if mode=='remote':return await HTTPPublicationClient(http,account_id='account-a').command(selection.publication_id,operation,payload)
                    owned=await bff(None,selection.publication_id,{'status':'read','history':'read','events':'read'}.get(operation,operation))
                    return await owned.lab.command(owned.actor,selection.publication_id,operation,payload,execution_guard=owned.execution_guard)
                async with engine.execution():
                    task=asyncio.create_task(command());await resolved.wait()
                    if change=='revoked':state['allowed']=False
                    elif change=='outage':state['available']=False
                    else:state['selection']=replace(selection,**{ {'account':'account_id','person':'person_id','binding':'binding_revision'}[change]:'changed'})
                with pytest.raises(PublicationError) as refused:await task
                assert refused.value.status==({'revoked':403,'outage':503}.get(change,409))
                assert reads==[] and engine.labels()==[] and model.calls==1
    asyncio.run(scenario())


def test_bff_round_trip_preserves_real_labels_and_monitoring_with_guarded_owner(tmp_path):
    async def scenario():
        model=OfflineModel()
        with Cyclotron.open(tmp_path/'engine',DEFINITION,model) as engine:
            lab=PublicationLab(engine,account_id='account-a',bindings=BINDINGS)
            selection=PublicationSelection('account-a','person','threat-intelligence','binding-1');checks=[]
            actor=PublicationActor('account-a','person',frozenset(('threat-intelligence',cap) for cap in ('read','decide','review')))
            def access(_connection,publication,capability):checks.append(capability);return PublicationAccess(lab,actor)
            app=create_publication_host(PublicationBFF(resolve_selection=lambda _:selection,resolve_access=access))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline.test') as http:
                client=HTTPPublicationClient(http,account_id='account-a')
                decision=await client.command(selection.publication_id,'decide',{'bindingRevision':'binding-1','item':ITEM})
                payload=review_payload(decision)
                saved=await client.command(selection.publication_id,'review',payload)
                assert saved==await client.command(selection.publication_id,'review',payload)
                assert saved['review']['explanation']==payload['explanation'] and saved['review']['reviewer']=='person'
                history=await client.command(selection.publication_id,'history',{})
                assert history['history'][0]['reviews']['intel']['label']==payload['label']
                status=await client.command(selection.publication_id,'status',{})
                assert status['accountId']=='account-a' and len(engine.labels())==1 and model.calls==1
                assert checks==['decide','decide','review','review','review','review','read','read','read','read']
    asyncio.run(scenario())


def test_authority_loss_after_decision_keeps_native_result_and_reports_missing_provenance(tmp_path):
    from decision_flywheel.publication_composition_test import catalog,request
    async def scenario():
        state={'allowed':True}
        class RevokeAfterDispatch(OfflineModel):
            async def classify_many(self,*args,**kwargs):
                result=await super().classify_many(*args,**kwargs)
                state['allowed']=False
                return result
        model=RevokeAfterDispatch();store,records=catalog(tmp_path)
        with Cyclotron.open(tmp_path/'engine',DEFINITION,model) as engine:
            lab=PublicationLab(engine,account_id='account-a',bindings=BINDINGS,records=records)
            selection=PublicationSelection('account-a','person','threat-intelligence','binding-1')
            actor=PublicationActor('account-a','person',frozenset(('threat-intelligence',cap) for cap in ('read','decide')))
            bff=PublicationBFF(resolve_selection=lambda _:selection,resolve_access=lambda *args:PublicationAccess(lab,actor) if state['allowed'] else None)
            app=create_publication_host(bff)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline.test') as http:
                client=HTTPPublicationClient(http,account_id='account-a')
                with pytest.raises(PublicationError) as uncertain:
                    await client.command(selection.publication_id,'decide',{'bindingRevision':'binding-1','item':ITEM,'context':request(records)})
                assert uncertain.value.code=='reconciliation_required'
                decisions=engine.decision_log()
                assert len(decisions)==1 and model.calls==1 and engine.labels()==[]
                assert records.contexts(selection.publication_id,decisions[0]['decision']['decisionId'])==[]
                state['allowed']=True
                history=await client.command(selection.publication_id,'history',{})
                assert history['history'][0]['provenanceUnavailable'] is True
    asyncio.run(scenario())


def test_cancelled_queued_host_operation_never_dispatches_and_can_be_retried_explicitly(tmp_path):
    async def scenario():
        model=OfflineModel();entered=asyncio.Event()
        with Cyclotron.open(tmp_path/'engine',DEFINITION,model) as engine:
            lab=PublicationLab(engine,account_id='account-a',bindings=BINDINGS)
            selection=PublicationSelection('account-a','person','threat-intelligence','binding-1')
            actor=PublicationActor('account-a','person',frozenset({('threat-intelligence','decide')}))
            def access(*args):entered.set();return PublicationAccess(lab,actor)
            bff=PublicationBFF(resolve_selection=lambda _:selection,resolve_access=access)
            app=create_publication_host(bff)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline.test') as http:
                client=HTTPPublicationClient(http,account_id='account-a');payload={'bindingRevision':'binding-1','item':ITEM}
                async with engine.execution():
                    task=asyncio.create_task(client.command(selection.publication_id,'decide',payload))
                    await entered.wait();task.cancel()
                    with pytest.raises(asyncio.CancelledError):await task
                assert model.calls==0 and engine.decision_log()==[]
                result=await client.command(selection.publication_id,'decide',payload)
                assert result['accountId']=='account-a' and model.calls==1
    asyncio.run(scenario())


@pytest.mark.parametrize('cancel',[False,True])
def test_guarded_steering_uses_public_owner_and_rejects_queued_work_before_catalog_reads(tmp_path,monkeypatch,cancel):
    from decision_flywheel.publication_composition_test import catalog
    from decision_flywheel.publication_steering import PublicationSteering
    async def scenario():
        _,records=catalog(tmp_path);state={'allowed':True};entered=asyncio.Event()
        class Evaluator:
            output_id='intel';active_fingerprint='active-1';calls=0
            async def execute(self,*args):self.calls+=1;return {'improved':False,'promoted':False}
        evaluator=Evaluator()
        with Cyclotron.open(tmp_path/'engine',DEFINITION,OfflineModel()) as engine:
            steering=PublicationSteering(records,{'intel':evaluator},owner_execution=engine.execution,allow_evaluation=True)
            lab=PublicationLab(engine,account_id='account-a',bindings=BINDINGS,records=records,steering=steering)
            selection=PublicationSelection('account-a','person','threat-intelligence','binding-1')
            actor=PublicationActor('account-a','person',frozenset(('threat-intelligence',cap) for cap in ('read','steer')))
            def access(*args):entered.set();return PublicationAccess(lab,actor) if state['allowed'] else None
            bff=PublicationBFF(resolve_selection=lambda _:selection,resolve_access=access)
            payload={'bindingRevision':'binding-1','bindingRef':records.reference('bindings','threat-intelligence',1).to_json(),
                     'classifier':'intel','requestId':'guarded-steer','expectedFingerprint':'active-1','action':'evaluate',
                     'proposal':{'rubric':'Explicit human rubric'},'explanation':'Evaluate before promotion.'}
            original=records.binding_revision;reads=[]
            def read(*args):reads.append(True);assert state['allowed'];return original(*args)
            monkeypatch.setattr(records,'binding_revision',read)
            app=create_publication_host(bff)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://offline.test') as http:
                client=HTTPPublicationClient(http,account_id='account-a')
                async with engine.execution():
                    task=asyncio.create_task(client.command(selection.publication_id,'steer',payload));await entered.wait()
                    if cancel:
                        task.cancel()
                        with pytest.raises(asyncio.CancelledError):await task
                    else:state['allowed']=False
                if not cancel:
                    with pytest.raises(PublicationError) as denied:await task
                    assert denied.value.status==403
                assert evaluator.calls==0 and reads==[] and records.records()==[]
                state['allowed']=True
                receipt=await client.command(selection.publication_id,'steer',payload)
                assert await client.command(selection.publication_id,'steer',payload)==receipt
                assert evaluator.calls==1 and engine.labels()==[]
    asyncio.run(scenario())
