"""Synthetic source/provider fixtures prove acceptance wiring, not real TI judgments."""
import asyncio
import base64
import csv
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from decision_flywheel import Cyclotron,ClassifierSpec,CyclotronDefinition,Item
from decision_flywheel.batched_classification import BatchedAnswers
from decision_flywheel.models import DecisionResult
from decision_flywheel.priming import HTTPTransformer,PrimingService
from decision_flywheel.web_api import create_app
from decision_flywheel.web_store import WebStore
from papyrus_content.priming_bootstrap import AcceptedPrimingSnapshot
from papyrus_content.priming_http import CurationJobs,create_transformer_app

QUESTION='Publish for this configured publication?'
DEFINITION=CyclotronDefinition('synthetic-priming-acceptance',(ClassifierSpec('editorial',('publish','not publish'),QUESTION),))
REFS=[{'id':'editorial','revision':1}]
SCHEMA={'type':'object','properties':{'text':{'type':'string','minLength':1},'title':{'type':'string','minLength':1},'abstract':{'type':'string','minLength':1},'source_uri':{'type':'string'},'domain':{'type':'string'},'ingestion_rationale':{'type':'string'},'published_at':{'type':'string'}},'required':['text','title','abstract'],'additionalProperties':False}


class InspectModel:
    model_identity='synthetic-priming-acceptance-offline-v1'
    def __init__(self):self.contexts=[]
    async def classify_many(self,configs,target,training,**kwargs):
        self.contexts.append(training)
        return BatchedAnswers({cid:{'decision':DecisionResult('publish',{'publish':.8,'not publish':.2})} for cid in configs},'offline',{},1)


def service(tmp_path,processor=None):
    store=WebStore(tmp_path/'catalog.sqlite3');store.save_item_list('examples','Explicitly accepted examples')
    store.save_classifier('editorial','Editorial',{'question':QUESTION,'classes':[{'label':label} for label in ('publish','not publish')],'item_schema':SCHEMA})
    transport=None
    if processor is not None:
        jobs=CurationJobs(tmp_path/'jobs.sqlite3',processor)
        remote=TestClient(create_transformer_app(jobs,authorize=lambda _:True))
        def request(req):
            response=remote.request(req.method,req.url.path,content=req.content,headers={'Content-Type':'application/json'})
            return httpx.Response(response.status_code,content=response.content,headers={'Content-Type':'application/json'})
        transport=httpx.Client(transport=httpx.MockTransport(request))
    priming=PrimingService(store,transformers=[HTTPTransformer('papyrus','Existing Papyrus curation','https://transformer.invalid',({'name':'url','label':'Source URL','required':True},))] if processor else (),client=transport)
    web=TestClient(create_app(store,priming=priming))
    def command(action,payload):
        result=web.post('/graphql',json={'query':'mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}','variables':{'action':action,'payload':payload}}).json()
        if result.get('errors'):raise ValueError(result['errors'][0]['message'])
        return result['data']['primingCommand']
    return store,priming,command


def snapshot(priming):return AcceptedPrimingSnapshot.capture(priming,list_id='examples',classifiers=REFS,definition=DEFINITION)


def test_research_and_web_accepted_over_shared_panel_api_prime_only_new_store(tmp_path,monkeypatch):
    from papyrus_newsroom import reference_curation_signals as signals
    monkeypatch.setattr(signals,'estimate_tokens',lambda *args,**kwargs:16)
    spec=importlib.util.spec_from_file_location('acceptance_fixture',Path(__file__).resolve().parents[2]/'scripts/curation-review/fixtures.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    store,priming,command=service(tmp_path,fixture.OfflineCuration())
    # All external source/provider boundaries are synthetic; no arbitrary network.
    monkeypatch.setattr('socket.create_connection',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('unexpected network')))
    try:
        for path,label in [('research','publish'),('web','not publish')]:
            draft=command('transform',{'identifier':path,'list_id':'examples','refs':REFS,'transformer_id':'papyrus','inputs':{'url':f'https://example.invalid/{"paper" if path=="research" else "web"}'}})
            draft=command('poll',{'identifier':path});assert draft['status']=='preview',draft['errors']
            assert len(store.list_items('examples'))==(0 if path=='research' else 1)
            with pytest.raises(ValueError):command('accept',{'identifier':path,'version':draft['version'],'labels':[{}]})
            if path=='research':
                command('feedback',{'identifier':path,'version':draft['version'],'request_id':'reject-1','reason':'Synthetic extraction correction, not an editorial judgment.','inputs':{}})
                draft=command('poll',{'identifier':path});assert draft['status']=='clarification'
                command('feedback',{'identifier':path,'version':draft['version'],'request_id':'correct-1','reason':'Use the corrected extraction.','inputs':{'title':'Synthetic corrected research title','abstract':'Synthetic corrected research abstract.'}})
                draft=command('poll',{'identifier':path});assert draft['status']=='preview',draft['errors']
            acceptance={'identifier':path,'version':draft['version'],'labels':[{'editorial':{'label':label,'rationale':f'Synthetic explicit human {path} judgment.'}}]}
            saved=command('accept',acceptance);assert saved['status']=='accepted'
            assert command('accept',acceptance)==saved
        command('transform',{'identifier':'cancel','list_id':'examples','refs':REFS,'transformer_id':'papyrus','inputs':{'url':'https://example.invalid/paper-cancel'}})
        command('cancel',{'identifier':'cancel'})
        with pytest.raises(ValueError):command('accept',{'identifier':'cancel','version':1,'labels':None})
        assert len(store.list_items('examples'))==2
        selected=snapshot(priming);examples=selected.for_definition(DEFINITION)
        assert [row.label for row in examples['editorial']]==['publish','not publish']
        assert all(row.context['human_feedback'].startswith('Synthetic explicit human') for row in examples['editorial'])
        assert all('extraction correction' not in row.context['human_feedback'] for row in examples['editorial'])
        assert all(json.loads(row.context['priming_origin'])['classifiers']==REFS for row in examples['editorial'])
        model=InspectModel()
        with Cyclotron.open(tmp_path/'new-store',DEFINITION,model,priming_examples=examples) as engine:
            assert engine.labels()==[] and engine.status().alignment.labels==0
            asyncio.run(engine.decide(Item('operational-after-priming',{'text':'Synthetic operational target'})))
            assert model.contexts[0]['editorial']==examples['editorial']
            with pytest.raises(ValueError,match='priming'):asyncio.run(engine.decide(examples['editorial'][0].item))
        with Cyclotron.open(tmp_path/'new-store',DEFINITION,InspectModel()) as reopened:
            assert reopened.labels()==[]
            asyncio.run(reopened.decide(Item('another-operational-target',{'text':'Synthetic target after reopen'})))
        paper=store.list_items('examples')[0]
        assert paper['provenance']['priming']['feedback'][0]['reason'].startswith('Synthetic extraction correction')
        assert paper['provenance']['papyrus']['processing_path']=='research'
    finally:priming.close()


@pytest.mark.parametrize('kind',['csv','json','jsonl','xlsx'])
def test_structured_preview_requires_acceptance_then_can_seed_a_new_store(tmp_path,kind):
    store,priming,command=service(tmp_path)
    row={'id':'synthetic-file-example','occurred_at':'2026-10-15','values':{'text':'Synthetic reviewed values','title':'Synthetic source title','abstract':'Synthetic source abstract'},'labels':{'editorial':{'label':'not publish','rationale':'Synthetic explicit human reason.'}}}
    if kind in ('csv','xlsx'):
        fields={'id':row['id'],'occurred_at':row['occurred_at'],**{'values.'+k:v for k,v in row['values'].items()},'editorial.label':'not publish','editorial.rationale':'Synthetic explicit human reason.'}
        if kind=='csv':
            output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(fields));writer.writeheader();writer.writerow(fields);content=output.getvalue().encode()
        else:
            from openpyxl import Workbook
            workbook=Workbook();sheet=workbook.active;sheet.append(list(fields));sheet.append(list(fields.values()));output=io.BytesIO();workbook.save(output);content=output.getvalue()
    else:content=json.dumps([row] if kind=='json' else row).encode()
    try:
        draft=command('file',{'identifier':'file','list_id':'examples','refs':REFS,'kind':kind,'content':base64.b64encode(content).decode()})
        with pytest.raises(ValueError,match='accepted'):snapshot(priming)
        assert store.list_items('examples')==[]
        command('accept',{'identifier':'file','version':draft['version'],'labels':None})
        selected=snapshot(priming);assert selected.for_definition(DEFINITION)['editorial'][0].label=='not publish'
        with Cyclotron.open(tmp_path/'unprimed-existing',DEFINITION,InspectModel()):pass
        with pytest.raises(ValueError,match='priming'):
            Cyclotron.open(tmp_path/'unprimed-existing',DEFINITION,InspectModel(),priming_examples=selected.for_definition(DEFINITION))
        with pytest.raises(ValueError,match='question'):
            AcceptedPrimingSnapshot.capture(priming,list_id='examples',classifiers=REFS,definition=CyclotronDefinition('other',(ClassifierSpec('editorial',('publish','not publish'),'Another question?'),)))
        template=priming.template('examples',REFS,'csv')
        assert 'values.abstract' in template['content'] and 'editorial.rationale' in template['content']
        assert 'Synthetic reviewed values' not in template['content']
        assert priming.template('examples',REFS,'xlsx')['encoding']=='base64'
        changed=CyclotronDefinition('changed',(ClassifierSpec('editorial',('publish','not publish'),'A changed editorial question?'),))
        with pytest.raises(ValueError,match='definition changed'):selected.for_definition(changed)
    finally:priming.close()


@pytest.mark.parametrize('use_priming',[False,True])
@pytest.mark.parametrize('overlap',[False,True])
def test_actual_relevance_sweep_optionally_consumes_only_the_explicit_accepted_snapshot(tmp_path,monkeypatch,use_priming,overlap):
    from features_backend.steps.cyclotron_relevance_sweep_steps import SweepClient,configure,reference,CORPUS_ID,DOCTRINE
    from papyrus_content.relevance_sweep import run_decide_relevance
    store,priming,command=service(tmp_path)
    try:
        row={'id':'synthetic-before-operation','occurred_at':'2026-10-15','values':{'text':'Synthetic accepted context','title':'Synthetic title','abstract':'Synthetic abstract'},'labels':{'editorial':{'label':'not publish','rationale':'Synthetic explicit rejection reason.'}}}
        draft=command('file',{'identifier':'before-operation','list_id':'examples','refs':REFS,'kind':'json','content':base64.b64encode(json.dumps([row]).encode()).decode()})
        command('accept',{'identifier':draft['id'],'version':draft['version'],'labels':None})
        selected=snapshot(priming) if use_priming else None
        context=SimpleNamespace(tmp=str(tmp_path));configure(context,tmp_path/'worker')
        block=context.steering['relevanceCyclotron'];block.update(cyclotronId=DEFINITION.id,classifierId='editorial',question=QUESTION,labels=['publish','not publish'],positiveLabel='publish')
        block['store']['s3Prefix']=None
        client=SweepClient({'Reference':[reference('synthetic-before-operation' if overlap else 'synthetic-operational','Synthetic operational security paper','pending')]})
        model=InspectModel()
        def body(client,attachment,content):client.upsert('ModelAttachment',attachment);client.bodies[attachment['id']]=content
        monkeypatch.setattr('papyrus_content.relevance_sweep.knowledge_corpus_id',lambda _:CORPUS_ID)
        monkeypatch.setattr('papyrus_content.records.upload_attachment_body',body)
        monkeypatch.setattr('papyrus_content.assignments.upload_attachment_body',body)
        monkeypatch.setattr('papyrus_content.relevance_sweep.download_attachment_buffer',lambda client,attachment:client.bodies.get(attachment['id']))
        monkeypatch.setattr('socket.create_connection',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('unexpected network')))
        if overlap and use_priming:
            with pytest.raises(ValueError,match='disjoint'):
                run_decide_relevance(client,context.steering,DOCTRINE,apply=True,worker='synthetic-worker',model=model,priming_snapshot=selected)
            assert client.updates==[] and model.contexts==[]
            return
        result=run_decide_relevance(client,context.steering,DOCTRINE,apply=True,worker='synthetic-worker',model=model,priming_snapshot=selected)
        assert result.decided==1 and result.status['alignment']['labels']==0
        training=model.contexts[0]['editorial']
        assert [item.item.id for item in training]==(['synthetic-before-operation'] if use_priming else [])
        if use_priming:assert training[0].context['human_feedback']=='Synthetic explicit rejection reason.'
        assert len(store.list_items('examples'))==1
    finally:priming.close()


def test_captured_priming_is_immutable_when_more_examples_are_later_accepted(tmp_path):
    from dataclasses import replace
    store,priming,command=service(tmp_path)
    try:
        def accept(identifier):
            row={'id':identifier,'occurred_at':'2026-10-15','values':{'title':'Synthetic title','abstract':'Synthetic abstract','text':'Synthetic text'},'labels':{'editorial':{'label':'publish','rationale':'Synthetic explicit human explanation.'}}}
            draft=command('file',{'identifier':identifier,'list_id':'examples','refs':REFS,'kind':'json','content':base64.b64encode(json.dumps([row]).encode()).decode()})
            command('accept',{'identifier':identifier,'version':draft['version'],'labels':None})
        accept('first');first=snapshot(priming)
        accept('later');later=snapshot(priming)
        assert len(first.for_definition(DEFINITION)['editorial'])==1
        assert len(later.for_definition(DEFINITION)['editorial'])==2 and first.fingerprint!=later.fingerprint
        with Cyclotron.open(tmp_path/'pinned-store',DEFINITION,InspectModel(),priming_examples=first.for_definition(DEFINITION)):pass
        with pytest.raises(ValueError,match='priming'):
            Cyclotron.open(tmp_path/'pinned-store',DEFINITION,InspectModel(),priming_examples=later.for_definition(DEFINITION))
        with pytest.raises(ValueError,match='fingerprint'):
            replace(first,payload=first.payload+' ').for_definition(DEFINITION)
    finally:priming.close()
