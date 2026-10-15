"""Opt-in real Biblicus CLI -> local gateway proof, with fake provider/source.

Set BIBLICUS_CONTRACT_CHECKOUT to the assigned owner's pinned checkout.
Only disposable loopback ports/stores are used; no paid or source network calls.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn

from papyrus_content.priming_curation import PapyrusPrimingCuration
from papyrus_content.priming_http import CurationJobs, create_transformer_app
from papyrus_content.priming_provider_budget import MODEL, PrimingProviderBudget

ROOT=os.environ.get('BIBLICUS_CONTRACT_CHECKOUT')
PYTHON=os.environ.get('BIBLICUS_CONTRACT_PYTHON')
pytestmark=pytest.mark.skipif(not ROOT or not PYTHON,reason='Explicit pinned Biblicus checkout/interpreter required')
SOURCE='https://www.cisa.gov/news-events/alerts/2021/01/07/supply-chain-compromise'
BODY='Synthetic public source paragraph about a software supply chain compromise. No human judgment.'


@contextmanager
def gateway(tmp_path,transport):
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    budget=PrimingProviderBudget(tmp_path/'budget.sqlite3',transport=transport,proxy_base_url=f'http://127.0.0.1:{port}/provider/v1')
    jobs=CurationJobs(tmp_path/'gateway-jobs.sqlite3',None,provider_budget=budget)
    server=uvicorn.Server(uvicorn.Config(create_transformer_app(jobs,authorize=lambda request:request.client.host=='127.0.0.1'),log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+5
        while not server.started and thread.is_alive() and time.monotonic()<deadline:thread.join(.01)
        assert server.started,'Disposable gateway failed to start'
        yield budget
    finally:
        server.should_exit=True;thread.join(5);sock.close()
        assert not thread.is_alive(),'Disposable gateway failed to stop'


def configure(monkeypatch,body=BODY):
    from papyrus_content import reference_url_text as extraction
    from papyrus_newsroom import reference_curation_signals as metadata
    root=Path(ROOT).resolve();assert (root/'src/biblicus/web_transform.py').is_file()
    for module in (extraction,metadata):
        monkeypatch.setattr(module,'BIBLICUS_ROOT',root)
        monkeypatch.setattr(module,'_biblicus_python_executable',lambda:Path(PYTHON))
    # Only source IO is a fixture; planners, CLI subprocesses, gateway and result
    # validation run as shipped. Human preview/catalog are never opened.
    monkeypatch.setattr(extraction,'resolve_source_site_enrichment',lambda **kwargs:{})
    monkeypatch.setattr(extraction,'_extract_url_text',lambda *args,**kwargs:{'text':body,'markdown':body,'title':'Synthetic public title','sourceKind':'web','contentType':'text/html','method':'offline-fixture'})
    return extraction,metadata


def response(payload,*,malformed=False):
    schema=payload['text']['format']['name']
    value={'paragraph_ids':[0]} if schema=='ParagraphSelection' else {'value':'Synthetic grounded metadata'}
    return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'invalid JSON' if malformed else json.dumps(value)}]}]}


def processor():
    return PapyrusPrimingCuration(corpus={'key':'synthetic','name':'Synthetic','path':'synthetic'},classifier_id='editorial',publication_name='Synthetic',model=MODEL)


def test_real_cli_full_pipeline_has_seven_calls_and_no_human_classification(tmp_path,monkeypatch):
    configure(monkeypatch);calls=[]
    def transport(payload):calls.append(payload);return response(payload)
    with gateway(tmp_path,transport) as budget:
        budget.grant('job',source_url=SOURCE,approval_evidence='OFFLINE CLI CONTRACT')
        with budget.execution({'id':'job','inputs':{'url':SOURCE}}):
            result=processor().prepare({'url':SOURCE},None,'')
        assert result['status']=='complete'
        assert result['candidate']['values']['title']=='Synthetic grounded metadata'
        assert result['candidate']['values']['abstract']=='Synthetic grounded metadata'
        assert 'labels' not in result['candidate']
        assert result['candidate']['provenance']['source_url']==SOURCE
        assert len(calls)==7 and budget.status('job')['reserved_microdollars']==126000
        assert all(p['store'] is False and p['reasoning']=={'effort':'none'} for p in calls)
        artifacts=result['artifacts']['extraction']['plans']
        assert any(BODY in str(p['body']) for p in artifacts)


@pytest.mark.parametrize('failure',['malformed','outage','cancelled'])
def test_real_cli_article_failure_stops_before_metadata_and_no_candidate(tmp_path,monkeypatch,failure):
    configure(monkeypatch);calls=[]
    def transport(payload):
        calls.append(payload)
        if failure=='outage':raise OSError('OFFLINE PRIVATE TRANSPORT ERROR')
        return response(payload,malformed=payload['text']['format']['name']=='ParagraphSelection')
    with gateway(tmp_path,transport) as budget:
        jobs=CurationJobs(tmp_path/'jobs.sqlite3',processor(),provider_budget=budget)
        jobs.start({'request_id':'job','inputs':{'url':SOURCE}})
        budget.grant('job',source_url=SOURCE,approval_evidence='OFFLINE FAILURE CONTRACT')
        if failure=='cancelled':budget.cancel('job')
        jobs.run('job',1)
        result=jobs.status('job')
        assert result['status']=='failed' and 'candidate' not in result
        assert len(calls)==(0 if failure=='cancelled' else 1)
        assert 'PRIVATE' not in str(result)


def test_real_cli_gateway_token_rejection_does_not_call_provider(tmp_path,monkeypatch):
    configure(monkeypatch);calls=[]
    from papyrus_content import reference_url_text as extraction
    with gateway(tmp_path,lambda payload:calls.append(payload)) as budget:
        budget.grant('job',source_url=SOURCE,approval_evidence='OFFLINE TOKEN CONTRACT')
        with budget.execution({'id':'job','inputs':{'url':SOURCE}}):
            result=extraction._filter_article_text(extracted_text=' a'*13000,source_uri=SOURCE,reference_title='',original_title='',original_subtitle='',model=MODEL)
        assert result['status']=='failed' and calls==[]
        assert budget.status('job')['requests']==0


@pytest.mark.parametrize('failure',['malformed','outage','cancel_after_map'])
def test_real_cli_metadata_failure_never_dispatches_reduce(tmp_path,monkeypatch,failure):
    _,metadata=configure(monkeypatch);calls=[]
    def transport(payload):
        calls.append(payload)
        if failure=='outage':raise OSError('OFFLINE PRIVATE ERROR')
        if failure=='cancel_after_map':budget.cancel('job')
        return response(payload,malformed=failure=='malformed')
    with gateway(tmp_path,transport) as budget:
        budget.grant('job',source_url=SOURCE,approval_evidence='OFFLINE MAP FAILURE')
        with budget.execution({'id':'job','inputs':{'url':SOURCE}}):
            with pytest.raises(RuntimeError):
                metadata._run_biblicus_summarize_map_reduce(output_kind='summary',reference={'sourceUri':SOURCE},context={'extractedText':BODY},model=MODEL)
        assert len(calls)==1 and budget.status('job')['requests']==1
