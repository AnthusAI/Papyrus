'use client';

import {useEffect,useState,type ReactNode} from 'react';
import {loadProspectusAccountState} from '../lib/prospectus-account-client';
import type {CurationBootstrap} from '../lib/curation-client';
import {NewsroomCurationProvider} from './newsroom-curation-provider';

type Fetcher=(input:string,init?:RequestInit)=>Promise<Response>;
const CONTEXT_PATH='/api/newsroom/curation/context';

function validBootstrap(value:unknown):value is CurationBootstrap{
  const body=value as Partial<CurationBootstrap>|null;
  const scope=body?.scope;
  return !!scope&&[scope.accountId,scope.publicationId,scope.bindingRevision].every(item=>typeof item==='string'&&item.trim()!=='')
    &&(body!.mode==='embedded'||body!.mode==='remote')&&Array.isArray(body!.capabilities);
}

/**
 * Ask the server for the curation bootstrap, or null. Only a signed-in person with a selected
 * account causes a context read; every other outcome (no Prospectus, signed out, no selection,
 * any refusal or failure) is null, so the released CMS is unchanged.
 */
export async function loadCurationBootstrap(returnPath:string,fetcher:Fetcher=fetch):Promise<CurationBootstrap|null>{
  try{
    const account=await loadProspectusAccountState(returnPath,fetcher);
    if(account.status!=='signedIn'||!account.selectedAccountId)return null;
    const response=await fetcher(CONTEXT_PATH,{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)return null;
    const body=await response.json().catch(()=>null);
    if(!validBootstrap(body)||body.scope.accountId!==account.selectedAccountId)return null;
    return body;
  }catch{return null;}
}

/** Mounts the curation provider for the References tab. Fails closed to no provider content. */
export function NewsroomCurationBootstrap({enabled=true,children}:{enabled?:boolean;children:ReactNode}){
  const [bootstrap,setBootstrap]=useState<CurationBootstrap|null>(null);
  useEffect(()=>{
    if(!enabled)return;
    let current=true;
    void loadCurationBootstrap(window.location.pathname).then(value=>{if(current)setBootstrap(value);});
    return()=>{current=false;setBootstrap(null);};
  },[enabled]);
  return <NewsroomCurationProvider bootstrap={bootstrap}>{children}</NewsroomCurationProvider>;
}
