'use client';

import {createContext,useContext,useMemo,useRef,type ReactNode} from 'react';
import {createCurationSession,requestCuration,type CurationBootstrap,type CurationRequest,type CurationSession} from '../lib/curation-client';
import type {PublicationScope} from '../lib/publication-cyclotron';

const Context=createContext<CurationSession|null>(null);

/** Host opt-in. Absence preserves the released CMS and performs no new reads. */
export function NewsroomCurationProvider({bootstrap,request=requestCuration,children}:{bootstrap:CurationBootstrap|null;request?:CurationRequest;children:ReactNode}){
  const selected=useRef<PublicationScope|null>(bootstrap?.scope??null);
  selected.current=bootstrap?.scope??null;
  const session=useMemo(()=>bootstrap?createCurationSession(bootstrap,request,()=>selected.current):null,[bootstrap,request]);
  return <Context.Provider value={session}>{children}</Context.Provider>;
}

export function useNewsroomCuration(){return useContext(Context);}
