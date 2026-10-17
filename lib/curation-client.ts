import {createPrimingClient} from 'cyclotron/priming-client';
import {assertPublicationScope,createPublicationClient,publicationScopeKey,type PublicationEnvelope,type PublicationRevisionRef,type PublicationScope} from './publication-cyclotron';

export type CurationBootstrap={
  scope:PublicationScope;
  mode:'embedded'|'remote';
  priming:{listId:string;classifiers:{id:string;revision:number}[]}|null;
  capabilities:readonly string[];
  bindingRef:PublicationRevisionRef|null;
};
export type CurationRequest=<T>(path:string,body:Record<string,unknown>,scope:Readonly<PublicationScope>)=>Promise<T>;

/** Same-origin only. The server verifies these expected pins against its session. */
export const requestCuration:CurationRequest=async<T,>(path:string,body:Record<string,unknown>,scope:Readonly<PublicationScope>)=>{
  if(!path.startsWith('/api/newsroom/curation/'))throw new Error('Same-origin curation route required');
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),15000);
  let response:Response;
  let result;
  try{
  response=await fetch(path,{method:'POST',credentials:'same-origin',signal:controller.signal,headers:{
    'Content-Type':'application/json','X-Cyclotron-Account':scope.accountId,
    'X-Papyrus-Publication':scope.publicationId,'X-Papyrus-Binding':scope.bindingRevision,
  },body:JSON.stringify(body)});
  result=await response.json().catch(()=>null);
  }catch(error){
    const timeout=controller.signal.aborted||(error instanceof Error&&error.name==='AbortError');
    throw new Error(timeout?'Curation request timed out. Your selection is preserved. Check the server and saved history before retrying; do not resubmit automatically.':'Cannot reach the curation server. Your selection is preserved. Check the preview is running and saved history before retrying; do not resubmit automatically.');
  }finally{clearTimeout(timer);}
  if(response.status===401)throw new Error('Sign in again: the curation session expired. Your selection is preserved.');
  if(response.status===403)throw new Error('Your session does not have permission for this curation action. Your selection is preserved.');
  if(!response.ok||!result||result.errors)throw new Error(`Curation request failed (HTTP ${response.status}): ${result?.error??result?.errors?.[0]?.message??'invalid server response'}. Check saved history before retrying; your selection is preserved.`);
  return result as T;
};

/** One controller contract for both modes; no browser-selected service URL. */
export function createCurationSession(bootstrap:CurationBootstrap,request:CurationRequest,currentScope:()=>PublicationScope|null){
  const pinned=Object.freeze({...bootstrap.scope});
  const scopeKey=publicationScopeKey(pinned);
  const assertCurrent=()=>{
    const selected=currentScope();
    if(!selected||publicationScopeKey(selected)!==scopeKey)throw new Error('Curation account selection changed; refresh context');
  };
  const publication=createPublicationClient(pinned,(operation,payload,scope)=>request<PublicationEnvelope&Record<string,unknown>>('/api/newsroom/curation/publication',{operation,payload},scope),currentScope);
  const priming=createPrimingClient(async<T,>(query:string,variables:Record<string,unknown>):Promise<T>=>{
    assertCurrent();
    const result=await request<{data:T}>('/api/newsroom/curation/priming',{query,variables},pinned);
    assertCurrent();
    return result.data;
  });
  return {
    key:JSON.stringify([bootstrap.mode,scopeKey]),bootstrap,publication,priming,
    async snapshot(){
      const [status,history]=await Promise.all([publication.status(),publication.history()]);
      assertCurrent();assertPublicationScope(status,history);
      return {status,history};
    },
  };
}

export type CurationSession=ReturnType<typeof createCurationSession>;
