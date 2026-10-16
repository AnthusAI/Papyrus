import assert from 'node:assert/strict';
import type {PublicationScope} from '../lib/publication-cyclotron';
import {createCurationSession,requestCuration,type CurationBootstrap,type CurationRequest} from '../lib/curation-client';
const scope={accountId:'account-a',publicationId:'publication-a',bindingRevision:'binding-1'};
const bootstrap:CurationBootstrap={scope,mode:'embedded',priming:{listId:'examples-a',classifiers:[{id:'editorial',revision:1}]},capabilities:['read','review'],bindingRef:null};
async function main(){
 let selected:typeof scope|null=scope,calls=0;
 const request:CurationRequest=async<T,>(_path:string,_body:Record<string,unknown>,pinned:Readonly<PublicationScope>)=>{calls++;assert.deepEqual(pinned,scope);return {data:{primingContract:{list_id:'examples-a'}}} as T;};
 const embedded=createCurationSession(bootstrap,request,()=>selected);
 const remote=createCurationSession({...bootstrap,mode:'remote'},request,()=>selected);
 assert.notEqual(embedded.key,remote.key);
 await embedded.priming.contract('examples-a',[{id:'editorial',revision:1}]);assert.equal(calls,1);
 selected=null;
 await assert.rejects(embedded.priming.contract('examples-a',[{id:'editorial',revision:1}]),/selection changed/);assert.equal(calls,1);
 await assert.rejects(embedded.publication.status(),/selection changed/);assert.equal(calls,1);
 selected=scope;
 let complete!:(value:unknown)=>void;
 const pending:CurationRequest=<T,>()=>new Promise<T>(resolve=>{complete=resolve as (value:unknown)=>void;});
 const stale=createCurationSession(bootstrap,pending,()=>selected);
 const read=stale.priming.contract('examples-a',[{id:'editorial',revision:1}]);
 selected={...scope,accountId:'account-b'};complete({data:{primingContract:{list_id:'examples-a'}}});
 await assert.rejects(read,/selection changed/);
 const originalFetch=globalThis.fetch;
 try {
  for(const [status,body,expected] of [[401,{error:'Session expired'},/Sign in again/],[403,{error:'Denied'},/permission/],[503,{error:'Unavailable'},/503/]] as const){
   globalThis.fetch=async()=>new Response(JSON.stringify(body),{status});
   await assert.rejects(requestCuration('/api/newsroom/curation/publication',{},scope),expected);
  }
  globalThis.fetch=async()=>{throw new TypeError('Failed to fetch');};
  await assert.rejects(requestCuration('/api/newsroom/curation/publication',{},scope),/Cannot reach.*not resubmit automatically/);
  globalThis.fetch=async()=>{throw new DOMException('Aborted','AbortError');};
  await assert.rejects(requestCuration('/api/newsroom/curation/publication',{},scope),/timed out.*not resubmit automatically/);
  globalThis.fetch=async()=>new Response('not JSON',{status:502});
  await assert.rejects(requestCuration('/api/newsroom/curation/publication',{},scope),/502/);
 } finally {globalThis.fetch=originalFetch;}
 console.log('curation session: mode identity, logout, pre-dispatch and stale-response isolation: ok');
}
void main();
