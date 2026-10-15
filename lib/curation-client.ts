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
  const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{
    'Content-Type':'application/json','X-Cyclotron-Account':scope.accountId,
    'X-Papyrus-Publication':scope.publicationId,'X-Papyrus-Binding':scope.bindingRevision,
  },body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok||result.errors)throw new Error(result.error??result.errors?.[0]?.message??'Curation request failed; check its outcome before retrying');
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
