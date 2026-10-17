"""Customer-hosted HTTP job service for Papyrus reference curation.

Run one service owner per SQLite store. Source artifacts are private working
state; only status/clarification and candidate item projections cross HTTP.
Authentication and network/tool permissions are supplied by the host.
"""
import base64
from contextlib import contextmanager,nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable
from fastapi import BackgroundTasks,FastAPI,HTTPException,Request
from .priming_curation import CurationNotReady
from .priming_provider_budget import BudgetDenied

MAX_BYTES=4_000_000


def json_value(value):
    if isinstance(value,bytes):return {'encoding':'base64','content':base64.b64encode(value).decode()}
    if isinstance(value,dict):return {key:json_value(child) for key,child in value.items()}
    if isinstance(value,(list,tuple)):return [json_value(child) for child in value]
    return value


def encode(value):return json.dumps(json_value(value),sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):return hashlib.sha256(encode(value).encode()).hexdigest()


class CurationJobs:
    def __init__(self,path,processor,*,provider_budget=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.processor=processor;self.provider_budget=provider_budget
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS curation_priming_jobs(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            # A prior owner died during extraction. Make interruption visible;
            # explicit feedback can retry, never silently invent completion.
            for row in db.execute('SELECT id,payload FROM curation_priming_jobs').fetchall():
                job=json.loads(row['payload'])
                if job['status']=='running':job.update(status='failed',message='Processing was interrupted. Retry with feedback or cancel.');self.write(db,job)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def read(self,db,identifier):
        row=db.execute('SELECT payload FROM curation_priming_jobs WHERE id=?',(identifier,)).fetchone()
        if row is None:raise ValueError('unknown curation job')
        return json.loads(row['payload'])

    def write(self,db,job):
        data=encode(job)
        if len(data.encode())>MAX_BYTES*10:raise ValueError('private curation working state exceeds size limit')
        db.execute('INSERT INTO curation_priming_jobs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(job['id'],data))

    def public(self,job):
        working=job.get('working') or {}
        result={'job_id':job['id'],'status':job['status']}
        if job.get('message'):result['message']=job['message']
        if job['status']=='complete':result['candidate']=working['candidate']
        if job['status']=='clarification':result.update(message=working['message'],fields=working['fields'])
        return result

    def status(self,identifier):
        with self.connect() as db:return self.public(self.read(db,identifier))

    def start(self,payload):
        identifier=payload.get('request_id');inputs=payload.get('inputs')
        if not isinstance(identifier,str) or not identifier or len(identifier)>200 or not isinstance(inputs,dict):raise ValueError('request identity and structured inputs required')
        signature=digest(payload)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT payload FROM curation_priming_jobs WHERE id=?',(identifier,)).fetchone()
            if old:
                job=json.loads(old[0])
                if job['signature']!=signature:raise ValueError('job identity has different content')
                return job,False
            job={'id':identifier,'signature':signature,'inputs':inputs,'status':'queued','version':1,'actions':{},'feedback':'','working':None,'revision_inputs':None}
            self.write(db,job);return job,True

    def run(self,identifier,version):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');job=self.read(db,identifier)
            if job['version']!=version or job['status']!='queued':return
            job['status']='running';self.write(db,job)
        try:
            previous=job['working']
            inputs=job['revision_inputs'] if previous is not None else job['inputs']
            scope=self.provider_budget.execution({**job,'inputs':{**job['inputs'],**inputs}}) if self.provider_budget is not None else nullcontext()
            with scope:working=self.processor.prepare(inputs,previous,job['feedback'])
            if working.get('status') not in ('complete','clarification'):raise ValueError('curation must complete or ask for clarification')
            if working['status']=='complete' and ('labels' in working['candidate'] or not working['candidate'].get('values')):raise ValueError('candidate must be complete and unclassified')
            working=json.loads(encode(working));status=working['status'];message=None
        except CurationNotReady as error:working=None;status='failed';message=str(error)
        except BudgetDenied as error:working=None;status='failed';message=str(error)
        except Exception:working=None;status='failed';message='Reference processing failed. No example was imported; revise or cancel.'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self.read(db,identifier)
            if current['version']!=version or current['status']=='cancelled':return
            if working is not None:current['working']=working
            current.update(status=status,message=message);self.write(db,current)

    def feedback(self,identifier,payload):
        request_id=payload.get('request_id');reason=payload.get('reason');inputs=payload.get('inputs')
        if not isinstance(request_id,str) or not request_id or len(request_id)>200 or not isinstance(reason,str) or not reason.strip() or not isinstance(inputs,dict):raise ValueError('feedback identity, reason and structured inputs required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');job=self.read(db,identifier)
            if job['status']=='cancelled':raise ValueError('curation job is cancelled')
            signature=digest(payload)
            if request_id in job['actions']:
                if job['actions'][request_id]!=signature:raise ValueError('feedback identity has different content')
                return job,False
            if job['status'] not in ('complete','clarification','failed'):raise ValueError('curation is still processing')
            job['actions'][request_id]=signature;job.update(version=job['version']+1,status='queued',feedback=reason,revision_inputs=inputs,message=None)
            self.write(db,job);return job,True

    def cancel(self,identifier):
        if self.provider_budget is not None:self.provider_budget.cancel(identifier)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');job=self.read(db,identifier);job.update(status='cancelled',working=None,message=None);self.write(db,job)
            return self.public(job)


def create_transformer_app(jobs:CurationJobs,*,authorize:Callable[[Request],bool]):
    app=FastAPI()
    @app.middleware('http')
    async def host_authority(request,next_handler):
        from fastapi.responses import JSONResponse
        if not authorize(request):return JSONResponse({'error':'host authorization required'},status_code=403)
        response=await next_handler(request);response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response
    async def payload(request):
        raw=await request.body()
        if len(raw)>MAX_BYTES:raise HTTPException(413,'request exceeds size limit')
        try:value=json.loads(raw)
        except ValueError:raise HTTPException(400,'invalid JSON') from None
        if not isinstance(value,dict):raise HTTPException(400,'structured request required')
        return value
    def conflict(function,*args):
        try:return function(*args)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
    @app.post('/jobs')
    async def start(request:Request,background:BackgroundTasks):
        body=await payload(request)
        if body.get('contract_version')!='cyclotron-transform/v1':raise HTTPException(400,'unknown transformation contract version')
        job,created=conflict(jobs.start,body)
        if created or job['status']=='queued':background.add_task(jobs.run,job['id'],job['version'])
        return jobs.public(job)
    @app.get('/jobs/{identifier}')
    async def status(identifier:str,background:BackgroundTasks):
        with jobs.connect() as db:job=conflict(jobs.read,db,identifier)
        if job['status']=='queued':background.add_task(jobs.run,identifier,job['version'])
        return jobs.public(job)
    @app.post('/jobs/{identifier}/feedback')
    async def feedback(identifier:str,request:Request,background:BackgroundTasks):
        job,created=conflict(jobs.feedback,identifier,await payload(request))
        if created or job['status']=='queued':background.add_task(jobs.run,identifier,job['version'])
        return jobs.public(job)
    @app.delete('/jobs/{identifier}')
    async def cancel(identifier:str):return conflict(jobs.cancel,identifier)
    if jobs.provider_budget is not None:
        @app.post('/provider/v1/responses')
        async def completion(request:Request):
            from starlette.concurrency import run_in_threadpool
            authorization=request.headers.get('Authorization','')
            if not authorization.startswith('Bearer '):raise HTTPException(403,'Worker capability required')
            try:return await run_in_threadpool(jobs.provider_budget.complete,authorization[7:],await payload(request))
            except BudgetDenied as error:raise HTTPException(409,str(error)) from None
            except Exception:raise HTTPException(502,'Provider request failed; retries are disabled and its reservation is retained.') from None
    return app
