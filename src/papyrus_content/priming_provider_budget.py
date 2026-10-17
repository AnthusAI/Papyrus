"""Opt-in, durable spending boundary for one approved priming job.

No provider is enabled by import or by HTTP. Only a trusted host can create a
grant. Worker subprocesses receive a job capability, never the provider key.
Reservations survive failed/uncertain delivery and cancellation; no refunds or
automatic retries can turn a job restart into a fresh spending allowance.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

MODEL='gpt-5.4-mini-2026-03-17'
MAX_REQUESTS=7
MAX_INPUT_TOKENS=12000
MAX_OUTPUT_TOKENS=2000
MAX_MICRODOLLARS=500000
# Pinned standard rates checked 2026-10-15: $0.75 input/$4.50 output per 1M.
# Reserve the full per-request maxima, even if the response uses fewer tokens.
RESERVATION_MICRODOLLARS=18000
PROVIDER_URL='https://api.openai.com/v1/responses'
_worker_environment=ContextVar('papyrus_priming_worker_environment',default=None)


class BudgetDenied(ValueError):
    """Controlled host-authored failure safe for a job's public status."""


def worker_environment():
    value=_worker_environment.get()
    return dict(value) if value is not None else None


class PrimingProviderBudget:
    def __init__(self,path,*,api_key=None,transport=None,proxy_base_url='http://127.0.0.1:8902/provider/v1'):
        if transport is None and not api_key:raise BudgetDenied('A trusted host must supply the provider key; paid execution is disabled.')
        target=urlsplit(proxy_base_url)
        if target.scheme!='http' or target.hostname!='127.0.0.1' or target.username or target.password:
            raise BudgetDenied('Worker provider proxy must bind to loopback.')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.proxy_base_url=proxy_base_url
        self.clock=time.time
        if transport is None:
            def transport(payload):
                import httpx
                with httpx.Client(timeout=60,follow_redirects=False,transport=httpx.HTTPTransport(retries=0)) as client:
                    response=client.post(PROVIDER_URL,json=payload,headers={'Authorization':f'Bearer {api_key}'})
                    response.raise_for_status()
                    return response.json()
        self.transport=transport
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS priming_provider_grants(job_id TEXT PRIMARY KEY,source_url TEXT NOT NULL,approval_evidence TEXT UNIQUE NOT NULL,capability TEXT UNIQUE NOT NULL,state TEXT NOT NULL,requests INTEGER NOT NULL,reserved_microdollars INTEGER NOT NULL,expires_at REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS priming_provider_attempts(job_id TEXT NOT NULL,signature TEXT NOT NULL,state TEXT NOT NULL,PRIMARY KEY(job_id,signature))')
            db.execute("UPDATE priming_provider_grants SET state='sealed' WHERE job_id IN (SELECT job_id FROM priming_provider_attempts WHERE state='reserved') AND state='active'")
            db.execute("UPDATE priming_provider_attempts SET state='uncertain' WHERE state='reserved'")

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def grant(self,job_id,*,source_url,approval_evidence):
        target=urlsplit(source_url)
        if not job_id or not approval_evidence or target.scheme!='https' or not target.hostname or target.username or target.password:
            raise BudgetDenied('A job, exact HTTPS source and trusted approval evidence are required.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM priming_provider_grants WHERE job_id=?',(job_id,)).fetchone():
                raise BudgetDenied('Existing job grants cannot be reset or replaced.')
            if db.execute('SELECT 1 FROM priming_provider_grants WHERE approval_evidence=?',(approval_evidence,)).fetchone():
                raise BudgetDenied('A spending approval cannot be reused for another job.')
            db.execute('INSERT INTO priming_provider_grants VALUES (?,?,?,?,?,?,?,?)',(job_id,source_url,approval_evidence,secrets.token_urlsafe(32),'active',0,0,self.clock()+3600))

    def capability(self,job_id):
        with self.connect() as db:
            row=db.execute('SELECT capability FROM priming_provider_grants WHERE job_id=?',(job_id,)).fetchone()
            if row is None:raise BudgetDenied('No trusted spending grant exists for this job.')
            return row['capability']

    def status(self,job_id):
        with self.connect() as db:
            row=db.execute('SELECT state,requests,reserved_microdollars,expires_at FROM priming_provider_grants WHERE job_id=?',(job_id,)).fetchone()
            if row is None:raise BudgetDenied('No trusted spending grant exists for this job.')
            return dict(row)

    @contextmanager
    def execution(self,job):
        with self.connect() as db:
            row=db.execute('SELECT * FROM priming_provider_grants WHERE job_id=?',(job['id'],)).fetchone()
            if row is None or row['state']!='active' or row['expires_at']<=self.clock() or row['source_url']!=job['inputs'].get('url'):
                raise BudgetDenied('No active spending grant matches this job and source URL. No provider call was made.')
            token=row['capability']
        scope=_worker_environment.set({'OPENAI_API_KEY':token,'OPENAI_BASE_URL':self.proxy_base_url,'OPENAI_API_BASE':self.proxy_base_url,'OPENAI_MAX_RETRIES':'0','BIBLICUS_HTML_LLM_STRUCTURED':'0','BIBLICUS_GROBID_AUTO_START':'0'})
        try:yield
        finally:_worker_environment.reset(scope)

    def cancel(self,job_id):
        with self.connect() as db:db.execute("UPDATE priming_provider_grants SET state='cancelled' WHERE job_id=?",(job_id,))

    def complete(self,token,payload):
        payload=self.validate(payload)
        signature=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM priming_provider_grants WHERE capability=?',(token,)).fetchone()
            if row is None or row['state']!='active' or row['expires_at']<=self.clock():raise BudgetDenied('Worker capability is absent, expired, cancelled or sealed.')
            if row['requests']>=MAX_REQUESTS or row['reserved_microdollars']+RESERVATION_MICRODOLLARS>MAX_MICRODOLLARS:
                raise BudgetDenied('The approved request or spending ceiling has been reached.')
            if db.execute('SELECT 1 FROM priming_provider_attempts WHERE job_id=? AND signature=?',(row['job_id'],signature)).fetchone():
                raise BudgetDenied('Duplicate provider request denied; retries are disabled.')
            job_id=row['job_id']
            db.execute('UPDATE priming_provider_grants SET requests=requests+1,reserved_microdollars=reserved_microdollars+? WHERE job_id=?',(RESERVATION_MICRODOLLARS,job_id))
            db.execute('INSERT INTO priming_provider_attempts VALUES (?,?,?)',(job_id,signature,'reserved'))
        try:result=self.transport(payload)
        except BaseException:
            with self.connect() as db:
                db.execute("UPDATE priming_provider_attempts SET state='uncertain' WHERE job_id=? AND signature=?",(job_id,signature))
                db.execute("UPDATE priming_provider_grants SET state='sealed' WHERE job_id=? AND state='active'",(job_id,))
            raise
        with self.connect() as db:db.execute("UPDATE priming_provider_attempts SET state='delivered' WHERE job_id=? AND signature=?",(job_id,signature))
        return result

    @staticmethod
    def validate(payload):
        if not isinstance(payload,dict) or set(payload)-{'model','input','text','max_output_tokens'}:
            raise BudgetDenied('Only bounded text generation is allowed; tools, storage and pricing overrides are disabled.')
        if payload.get('model')!=MODEL:raise BudgetDenied('The model is not approved for this test.')
        maximum=payload.get('max_output_tokens')
        if type(maximum) is not int or not 1<=maximum<=MAX_OUTPUT_TOKENS:raise BudgetDenied('Output token bound exceeded.')
        value=payload.get('input')
        if isinstance(value,list):
            if not value or len(value)>256:raise BudgetDenied('Text message count exceeded.')
            for message in value:
                if not isinstance(message,dict) or set(message)!={'role','content'} or message['role'] not in ('system','developer','user','assistant'):
                    raise BudgetDenied('Only text messages are allowed.')
                content=message['content']
                if isinstance(content,list):
                    if any(not isinstance(c,dict) or set(c)!={'type','text'} or c['type']!='input_text' or not isinstance(c['text'],str) for c in content):
                        raise BudgetDenied('Only text messages are allowed.')
                elif not isinstance(content,str):raise BudgetDenied('Only text messages are allowed.')
        elif not isinstance(value,str) or not value:raise BudgetDenied('Text input is required.')
        import tiktoken
        try:encoding=tiktoken.encoding_for_model(MODEL)
        except Exception:raise BudgetDenied('The pinned model tokenizer is unavailable; no provider call was made.') from None
        # Count the entire serialized request, with a conservative allowance for
        # provider framing. Oversized source is rejected, never silently clipped.
        tokens=len(encoding.encode(json.dumps(payload,ensure_ascii=False),disallowed_special=()))+1024
        if tokens>MAX_INPUT_TOKENS:
            raise BudgetDenied('Input token bound exceeded.')
        return {**payload,'store':False,'service_tier':'default','reasoning':{'effort':'none'}}
