"""Synthetic job transport; no model, source network, or cloud mutation."""
from fastapi.testclient import TestClient
import pytest
from papyrus_content.priming_http import CurationJobs,create_transformer_app

class Processor:
    def __init__(self):self.calls=[]
    def prepare(self,inputs,previous,feedback):
        self.calls.append((inputs,previous,feedback))
        if feedback and not inputs:return {'status':'clarification','fields':[{'name':'abstract','label':'Abstract','required':True}],'message':'Correct abstract','private':'never expose'}
        return {'status':'complete','candidate':{'id':'synthetic','occurred_at':'2026-10-14','values':{'text':inputs.get('abstract','Synthetic extracted text')}},'artifacts':{'body':'Private source working data'}}


def test_http_start_status_feedback_and_cancel_are_durable_and_retry_safe(tmp_path):
    processor=Processor();jobs=CurationJobs(tmp_path/'jobs.db',processor)
    client=TestClient(create_transformer_app(jobs,authorize=lambda _:True))
    payload={'contract_version':'cyclotron-transform/v1','request_id':'job','inputs':{'url':'https://example.invalid'}}
    assert client.post('/jobs',json=payload).status_code==200
    result=client.get('/jobs/job').json();assert result['status']=='complete'
    assert 'artifacts' not in result and 'Private' not in str(result)
    assert client.post('/jobs',json=payload).json()['job_id']=='job' and len(processor.calls)==1
    assert client.post('/jobs',json={**payload,'inputs':{'url':'changed'}}).status_code==409
    revised={'request_id':'revision','reason':'Wrong extraction','inputs':{}}
    client.post('/jobs/job/feedback',json=revised)
    assert client.get('/jobs/job').json()['status']=='clarification'
    assert client.post('/jobs/job/feedback',json=revised).status_code==200 and len(processor.calls)==2
    assert client.delete('/jobs/job').json()['status']=='cancelled'
    assert client.delete('/jobs/job').json()['status']=='cancelled'
    assert client.post('/jobs/job/feedback',json={**revised,'request_id':'late'}).status_code==409
    reopened=CurationJobs(tmp_path/'jobs.db',processor)
    assert reopened.status('job')['status']=='cancelled'


def test_cancel_during_processing_discards_late_candidate(tmp_path):
    processor=Processor();jobs=CurationJobs(tmp_path/'db',processor)
    jobs.start({'request_id':'job','inputs':{}})
    processor.prepare=lambda *args:(jobs.cancel('job'),{'status':'complete','candidate':{'id':'late'}})[1]
    jobs.run('job',1)
    assert jobs.status('job')['status']=='cancelled' and 'candidate' not in jobs.status('job')


def test_transformer_requires_host_authority_and_redacts_failures(tmp_path):
    processor=Processor();jobs=CurationJobs(tmp_path/'db',processor)
    denied=TestClient(create_transformer_app(jobs,authorize=lambda _:False))
    assert denied.post('/jobs',json={}).status_code==403
    processor.prepare=lambda *_:(_ for _ in ()).throw(RuntimeError('private provider credential'))
    client=TestClient(create_transformer_app(jobs,authorize=lambda _:True))
    client.post('/jobs',json={'contract_version':'cyclotron-transform/v1','request_id':'failure','inputs':{}})
    result=client.get('/jobs/failure').json()
    assert result['status']=='failed' and 'credential' not in str(result)


def test_readiness_failure_is_actionable_retryable_and_cancellable(tmp_path):
    from papyrus_content.priming_curation import CurationNotReady
    processor=Processor()
    def unavailable(*args):
        raise CurationNotReady('Paper parser is unavailable. No example was imported.')
    processor.prepare=unavailable
    jobs=CurationJobs(tmp_path/'readiness.db',processor)
    client=TestClient(create_transformer_app(jobs,authorize=lambda _:True))
    client.post('/jobs',json={'contract_version':'cyclotron-transform/v1','request_id':'paper','inputs':{'url':'https://arxiv.org/abs/2503.15739'}})
    result=client.get('/jobs/paper').json()
    assert result['status']=='failed' and result['message'].startswith('Paper parser is unavailable')
    assert 'candidate' not in result
    processor.prepare=Processor().prepare
    client.post('/jobs/paper/feedback',json={'request_id':'retry','reason':'Parser is ready; retry source extraction','inputs':{}})
    assert client.get('/jobs/paper').json()['status']=='complete'
    assert client.delete('/jobs/paper').json()['status']=='cancelled'
