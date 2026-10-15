"""Offline spending-boundary specs; every provider transport is a test double."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

from fastapi.testclient import TestClient
import pytest

from papyrus_content.priming_provider_budget import (
    BudgetDenied, MODEL, PrimingProviderBudget, worker_environment,
)
from papyrus_content.priming_http import CurationJobs, create_transformer_app

SOURCE='https://www.cisa.gov/news-events/alerts/2021/01/07/supply-chain-compromise'


def request(index=0, **overrides):
    return {'model':MODEL,'input':f'Public source text for stage {index}', 'max_output_tokens':2000, **overrides}


def budget(tmp_path, transport=None):
    calls=[]
    def record(payload):
        calls.append(payload)
        return {'id':'offline-response','output':[]}
    return PrimingProviderBudget(tmp_path/'budget.sqlite3',transport=transport or record),calls


def grant(b):
    b.grant('job',source_url=SOURCE,approval_evidence='OFFLINE TEST GRANT')


def test_no_grant_or_wrong_source_never_issues_worker_credentials(tmp_path):
    b,calls=budget(tmp_path)
    with pytest.raises(BudgetDenied):
        with b.execution({'id':'job','inputs':{'url':SOURCE}}):pass
    grant(b)
    with pytest.raises(BudgetDenied):
        with b.execution({'id':'job','inputs':{'url':'https://example.invalid'}}):pass
    assert calls==[] and b.status('job')['requests']==0


def test_approval_cannot_be_reset_by_new_request_identity_or_cancellation(tmp_path):
    b,_=budget(tmp_path);grant(b)
    b.cancel('job')
    with pytest.raises(BudgetDenied):grant(b)
    with pytest.raises(BudgetDenied):b.grant('different-job',source_url=SOURCE,approval_evidence='OFFLINE TEST GRANT')


def test_grant_expires_without_dispatch_or_budget_reset(tmp_path):
    b,calls=budget(tmp_path);b.clock=lambda:100;grant(b)
    token=b.capability('job');b.clock=lambda:3701
    with pytest.raises(BudgetDenied):b.complete(token,request())
    assert calls==[] and b.status('job')['requests']==0


def test_crash_after_reservation_seals_reopened_grant(tmp_path):
    import os
    import subprocess
    import sys
    b,_=budget(tmp_path);grant(b)
    program='''import os,sys
from papyrus_content.priming_provider_budget import PrimingProviderBudget,MODEL
b=PrimingProviderBudget(sys.argv[1],transport=lambda payload:os._exit(0))
b.complete(b.capability('job'),{'model':MODEL,'input':'Offline crash test','max_output_tokens':2000})
'''
    result=subprocess.run([sys.executable,'-c',program,str(b.path)],env=dict(os.environ),timeout=20)
    assert result.returncode==0
    reopened,_=budget(tmp_path)
    assert reopened.status('job')['state']=='sealed'
    assert reopened.status('job')['requests']==1
    with pytest.raises(BudgetDenied):reopened.complete(reopened.capability('job'),request(1))


def test_seven_requests_are_reserved_durably_before_transport_and_eighth_denied(tmp_path):
    b,calls=budget(tmp_path);grant(b)
    token=b.capability('job')
    for n in range(7):b.complete(token,request(n))
    with pytest.raises(BudgetDenied):b.complete(token,request(7))
    state=b.status('job')
    assert len(calls)==7 and state['requests']==7
    assert state['reserved_microdollars']==126000 <= 500000
    reopened,_=budget(tmp_path)
    with pytest.raises(BudgetDenied):reopened.complete(token,request(8))
    assert all(p['store'] is False and p['service_tier']=='default' for p in calls)
    assert all(p['reasoning']=={'effort':'none'} and 'tools' not in p for p in calls)


@pytest.mark.parametrize('payload',[
    request(model='unapproved-model'),request(max_output_tokens=2001),
    request(tools=[{'type':'web_search'}]),request(input=' words'*13000),
    request(input=[{'role':'user','content':[{'type':'input_image','image_url':'https://example.invalid/a'}]}]),
    request(service_tier='priority'),request(store=True),
])
def test_unapproved_model_tools_tokens_modalities_and_pricing_fail_before_dispatch(tmp_path,payload):
    b,calls=budget(tmp_path);grant(b)
    with pytest.raises(BudgetDenied):b.complete(b.capability('job'),payload)
    assert calls==[] and b.status('job')['requests']==0


def test_duplicate_request_is_not_retried(tmp_path):
    b,calls=budget(tmp_path);grant(b);token=b.capability('job')
    b.complete(token,request())
    with pytest.raises(BudgetDenied):b.complete(token,request())
    assert len(calls)==1 and b.status('job')['requests']==1


@pytest.mark.parametrize('failure',[RuntimeError('uncertain network failure'),asyncio.CancelledError()])
def test_uncertain_dispatch_or_cancellation_retains_reservation_and_seals_budget(tmp_path,failure):
    calls=[]
    def fail(payload):calls.append(payload);raise failure
    b,_=budget(tmp_path,fail);grant(b);token=b.capability('job')
    with pytest.raises(type(failure)):b.complete(token,request())
    with pytest.raises(BudgetDenied):b.complete(token,request(1))
    state=b.status('job')
    assert len(calls)==1 and state['requests']==1 and state['reserved_microdollars']==18000


def test_concurrent_requests_cannot_cross_the_ceiling(tmp_path):
    b,calls=budget(tmp_path);grant(b);token=b.capability('job')
    def run(n):
        try:b.complete(token,request(n));return True
        except BudgetDenied:return False
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(run,range(12)))
    assert sum(results)==7 and len(calls)==7 and b.status('job')['requests']==7


def test_worker_scope_removes_real_credentials_and_is_not_shared_across_threads(tmp_path,monkeypatch):
    from papyrus_content.reference_url_text import _biblicus_env
    b,_=budget(tmp_path);grant(b)
    monkeypatch.setenv('OPENAI_API_KEY','REAL SECRET MUST STAY OUT')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','OTHER SECRET MUST STAY OUT')
    with b.execution({'id':'job','inputs':{'url':SOURCE}}):
        env=_biblicus_env()
        assert env['OPENAI_API_KEY']==b.capability('job')
        assert env['OPENAI_BASE_URL']=='http://127.0.0.1:8902/provider/v1'
        assert 'AWS_SECRET_ACCESS_KEY' not in env and 'REAL SECRET' not in str(env)
        with ThreadPoolExecutor(max_workers=1) as pool:assert pool.submit(worker_environment).result() is None
    assert worker_environment() is None


def test_existing_worker_commands_share_the_scoped_proxy_without_package_install(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from papyrus_content import reference_url_text as extraction
    from papyrus_newsroom import reference_curation_signals as metadata
    b,_=budget(tmp_path);grant(b);calls=[]
    monkeypatch.setattr(extraction,'BIBLICUS_ROOT',tmp_path)
    monkeypatch.setattr(metadata,'BIBLICUS_ROOT',tmp_path)
    def worker(command,**kwargs):
        calls.append((command,kwargs))
        env=kwargs['env']
        assert env['OPENAI_API_KEY']==b.capability('job')
        assert env['OPENAI_BASE_URL'].endswith('/provider/v1')
        if 'article-text' in command:
            return SimpleNamespace(returncode=1,stdout=json.dumps({'error':{'code':'missing_dspy','message':'Optional worker dependency missing'}}),stderr='')
        return SimpleNamespace(returncode=0,stdout=json.dumps({'task':'summary','value':'Offline contract value'}),stderr='')
    monkeypatch.setattr(extraction.subprocess,'run',worker)
    with b.execution({'id':'job','inputs':{'url':SOURCE}}):
        with pytest.raises(RuntimeError):extraction._run_biblicus_article_text({'extracted_text':'Offline source'})
        metadata._run_biblicus_summarize_map_reduce(output_kind='summary',reference={},context={'extractedText':'Offline source'},model=MODEL)
    assert len(calls)==2 and all(command[0]!='uv' for command,_ in calls)


def test_real_job_http_composition_enforces_capability_and_cancel_boundary(tmp_path):
    b,calls=budget(tmp_path);grant(b)
    class Processor:
        def prepare(self,inputs,previous,feedback):
            assert worker_environment()['OPENAI_BASE_URL'].endswith('/provider/v1')
            return {'status':'complete','candidate':{'id':'offline','values':{'text':'Offline only'}}}
    jobs=CurationJobs(tmp_path/'jobs.sqlite3',Processor(),provider_budget=b)
    client=TestClient(create_transformer_app(jobs,authorize=lambda _:True))
    assert client.post('/provider/v1/responses',json=request()).status_code==403
    headers={'Authorization':'Bearer '+b.capability('job')}
    assert client.post('/provider/v1/responses',json=request(),headers=headers).status_code==200
    client.post('/jobs',json={'contract_version':'cyclotron-transform/v1','request_id':'job','inputs':{'url':SOURCE}})
    assert client.get('/jobs/job').json()['status']=='complete'
    client.delete('/jobs/job')
    assert client.post('/provider/v1/responses',json=request(1),headers=headers).status_code==409
    assert len(calls)==1 and b.status('job')['state']=='cancelled'


def test_production_transport_does_not_exist_without_explicit_key(tmp_path):
    with pytest.raises(BudgetDenied):PrimingProviderBudget(tmp_path/'no-key.sqlite3')


@pytest.mark.parametrize('status',[200,302,502])
def test_actual_http_adapter_has_fixed_destination_no_tools_storage_or_retries(tmp_path,monkeypatch,status):
    import httpx
    calls=[]
    def wire(req):
        calls.append(req)
        return httpx.Response(status,json={'id':'OFFLINE ONLY','output':[]},headers={'Location':'https://example.invalid/redirect'})
    def transport(*,retries):
        assert retries==0
        return httpx.MockTransport(wire)
    monkeypatch.setattr(httpx,'HTTPTransport',transport)
    b=PrimingProviderBudget(tmp_path/'http.db',api_key='OFFLINE KEY');grant(b)
    if status==200:b.complete(b.capability('job'),request())
    else:
        with pytest.raises(httpx.HTTPStatusError):b.complete(b.capability('job'),request())
        assert b.status('job')['state']=='sealed'
    assert len(calls)==1
    assert str(calls[0].url)=='https://api.openai.com/v1/responses'
    sent=json.loads(calls[0].content)
    assert sent['model']==MODEL and sent['max_output_tokens']==2000
    assert sent['store'] is False and sent['service_tier']=='default' and 'tools' not in sent


def test_revision_cannot_spend_original_url_grant_on_another_source(tmp_path):
    b,calls=budget(tmp_path)
    prepared=[]
    class Processor:
        def prepare(self,inputs,previous,feedback):
            prepared.append(inputs)
            return {'status':'complete','candidate':{'values':{'title':'Public source'}}}
    jobs=CurationJobs(tmp_path/'jobs.sqlite3',Processor(),provider_budget=b)
    job,_=jobs.start({'request_id':'revision-url','inputs':{'url':SOURCE}})
    b.grant(job['id'],source_url=SOURCE,approval_evidence='OFFLINE REVISION GRANT')
    jobs.run(job['id'],job['version'])
    revised,_=jobs.feedback(job['id'],{'request_id':'change-url','reason':'Use another source','inputs':{'url':'https://example.invalid/other'}})
    jobs.run(revised['id'],revised['version'])
    with jobs.connect() as db:state=jobs.read(db,job['id'])
    assert state['status']=='failed'
    assert len(prepared)==1 and calls==[]


def test_title_abstract_revision_retains_original_source_grant(tmp_path):
    b,calls=budget(tmp_path)
    prepared=[]
    class Processor:
        def prepare(self,inputs,previous,feedback):
            prepared.append((inputs,previous,feedback,worker_environment()))
            return {'status':'complete','candidate':{'values':{'title':inputs.get('title','Extracted title'),'abstract':inputs.get('abstract','Extracted abstract')}}}
    jobs=CurationJobs(tmp_path/'jobs.sqlite3',Processor(),provider_budget=b)
    job,_=jobs.start({'request_id':'correction','inputs':{'url':SOURCE}})
    b.grant(job['id'],source_url=SOURCE,approval_evidence='OFFLINE CORRECTION GRANT')
    jobs.run(job['id'],job['version'])
    corrections={'title':'Corrected source title','abstract':'Corrected source abstract'}
    revised,_=jobs.feedback(job['id'],{'request_id':'correct-title','reason':'Repair extraction','inputs':corrections})
    jobs.run(revised['id'],revised['version'])
    result=jobs.status(job['id'])
    assert result['status']=='complete'
    assert result['candidate']['values']==corrections
    assert prepared[1][0]==corrections and prepared[1][2]=='Repair extraction'
    assert prepared[1][3]['OPENAI_API_KEY']==b.capability(job['id'])
    assert b.status(job['id'])['requests']==0 and calls==[]
