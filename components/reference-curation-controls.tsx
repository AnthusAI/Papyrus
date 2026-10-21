'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import {useNewsroomCuration} from './newsroom-curation-provider';
import {PublicationCyclotronPanel} from './publication-cyclotron-panel';
import type {PrimingPanelProps} from 'cyclotron/components/priming-panel';
import {Button} from './ui/button';
import {publicationSteeringPayload,type PublicationHistory,type PublicationStatus} from '../lib/publication-cyclotron';
import type {CurationSession} from '../lib/curation-client';

/** `refreshSignal` changes when references were just added, so the panel reloads by itself. */
export function ReferenceCurationControls({disabled=false,refreshSignal=0}:{disabled?:boolean;refreshSignal?:number}){
  const session=useNewsroomCuration();
  return session&&!disabled?<Controls key={session.key} session={session} disabled={disabled} refreshSignal={refreshSignal}/>:null;
}

/**
 * The import option of the Add a reference area, or null. Fail-closed: it exists
 * only when a curation session supplies priming and the person may review.
 */
export function useReferenceImport(disabled=false):{panel:PrimingPanelProps;sessionKey:string}|null{
  const session=useNewsroomCuration();
  if(!session||disabled||!session.bootstrap.priming||!session.bootstrap.capabilities.includes('review'))return null;
  return {sessionKey:session.key,panel:{client:session.priming,listId:session.bootstrap.priming.listId,classifiers:session.bootstrap.priming.classifiers}};
}

function Controls({session,disabled,refreshSignal}:{session:CurationSession;disabled:boolean;refreshSignal:number}){
  const [snapshot,setSnapshot]=useState<{status:PublicationStatus;history:PublicationHistory}|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [steering,setSteering]=useState<string|null>(null);
  const [rubric,setRubric]=useState('');
  const [explanation,setExplanation]=useState('');
  const [busy,setBusy]=useState(false);
  const [trial,setTrial]=useState<{fingerprint:string;improved:boolean}|null>(null);
  const [steeringMessage,setSteeringMessage]=useState('');
  const steeringRequests=useRef<Record<string,string>>({});
  const canReview=!disabled&&session.bootstrap.capabilities.includes('review');
  const canSteer=!disabled&&session.bootstrap.capabilities.includes('steer');
  const refresh=useCallback(async()=>{
    setLoading(true);setError('');
    try{setSnapshot(await session.snapshot());}
    catch(failure){setSnapshot(null);setError(failure instanceof Error?failure.message:'Suggestions are unavailable right now.');}
    finally{setLoading(false);}
  },[session]);
  useEffect(()=>{
    let active=true;
    void session.snapshot().then(value=>{if(active){setSnapshot(value);setError('');}}).catch(failure=>{if(active){setSnapshot(null);setError(failure instanceof Error?failure.message:'Suggestions are unavailable right now.');}}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[session]);
  const lastSignal=useRef(refreshSignal);
  useEffect(()=>{if(lastSignal.current!==refreshSignal){lastSignal.current=refreshSignal;void refresh();}},[refreshSignal,refresh]);
  async function steer(action:'evaluate'|'promote'){
    if(!snapshot||!steering||!session.bootstrap.bindingRef)return;
    setBusy(true);setSteeringMessage('');
    try{
      const identity=JSON.stringify([action,steering,rubric.trim(),explanation.trim(),trial?.fingerprint??'',snapshot.status.classifiers[steering].cyclotron.fingerprint]);
      const requestId=steeringRequests.current[identity]??=crypto.randomUUID();
      const command=action==='evaluate'?{action,proposal:{rubric:rubric.trim()},explanation,requestId} as const:{action,trialFingerprint:trial?.fingerprint??'',explanation,requestId} as const;
      const payload=publicationSteeringPayload(snapshot.status,steering,session.bootstrap.bindingRef,command);
      const receipt=await session.publication.steer(payload);
      const result=(receipt.steering as {result?:{trial_fingerprint?:string;improved?:boolean;promoted?:boolean}}|undefined)?.result;
      if(action==='evaluate')setTrial(result?.trial_fingerprint?{fingerprint:result.trial_fingerprint,improved:result.improved===true}:null);
      setSteeringMessage(action==='promote'?'The tested change is now in use.':result?.improved?'Test finished: the change improved the results.':'Test finished: no improvement was found.');
      await refresh();
    }catch(failure){setSteeringMessage(failure instanceof Error?failure.message:'The result is unknown; check before trying again.');}
    finally{setBusy(false);}
  }
  return <section aria-label="Suggestions for this publication" className="max-h-[55dvh] min-h-0 shrink-0 space-y-3 overflow-y-auto rounded-md border p-3" data-curation-mode={session.bootstrap.mode}>
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">Suggestions for this publication</h3><Button variant="outline" size="sm" disabled={loading||busy} onClick={()=>void refresh()}>Refresh</Button></div>
    <p className="text-xs text-muted-foreground">{session.bootstrap.mode==='remote'?'Shared review service':'This site'} · {session.bootstrap.scope.publicationId}</p>
    {loading?<p role="status">Loading suggestions…</p>:null}
    {error?<p role="alert">{error}</p>:null}
    {snapshot?<PublicationCyclotronPanel mode={session.bootstrap.mode} status={snapshot.status} history={snapshot.history}
      onReview={canReview?async payload=>{await session.publication.review(payload);await refresh();}:undefined}
      onSteer={canSteer&&snapshot.status.features?.steering&&session.bootstrap.bindingRef?classifier=>{setSteering(classifier);setRubric('');setExplanation('');setTrial(null);setSteeringMessage('');}:undefined}/>:null}
    {steering?<form aria-label="Rule change" className="space-y-3 rounded-md border p-3" onSubmit={event=>{event.preventDefault();void steer('evaluate');}}>
      <h4 className="font-semibold">Test a rule change</h4>
      <p className="text-sm">A change is tested before it is adopted. Opening this form does not change any existing suggestion.</p>
      <label className="block text-sm">Proposed rule<textarea className="mt-1 block min-h-24 w-full rounded border bg-background p-2" required value={rubric} onChange={event=>{setRubric(event.target.value);setTrial(null);}}/></label>
      <label className="block text-sm">Why make this change?<textarea className="mt-1 block min-h-20 w-full rounded border bg-background p-2" required value={explanation} onChange={event=>setExplanation(event.target.value)}/></label>
      <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy||!canSteer||!rubric.trim()||!explanation.trim()}>Test change</Button><Button type="button" variant="outline" disabled={busy||!canSteer||!trial?.improved||!explanation.trim()} onClick={()=>void steer('promote')}>Adopt tested change</Button><Button type="button" variant="ghost" disabled={busy} onClick={()=>setSteering(null)}>Close</Button></div>
      {steeringMessage?<p role="status">{steeringMessage}</p>:null}
    </form>:null}
  </section>;
}
