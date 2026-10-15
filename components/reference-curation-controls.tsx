'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import {useNewsroomCuration} from './newsroom-curation-provider';
import {PublicationCyclotronPanel} from './publication-cyclotron-panel';
import {ReferencePriming} from './reference-priming';
import {Button} from './ui/button';
import {publicationSteeringPayload,type PublicationHistory,type PublicationStatus} from '../lib/publication-cyclotron';
import type {CurationSession} from '../lib/curation-client';

export function ReferenceCurationControls({disabled=false}:{disabled?:boolean}){
  const session=useNewsroomCuration();
  return session&&!disabled?<Controls key={session.key} session={session} disabled={disabled}/>:null;
}

function Controls({session,disabled}:{session:CurationSession;disabled:boolean}){
  const [snapshot,setSnapshot]=useState<{status:PublicationStatus;history:PublicationHistory}|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [primingMessage,setPrimingMessage]=useState('');
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
    catch(failure){setSnapshot(null);setError(failure instanceof Error?failure.message:'Curation status unavailable');}
    finally{setLoading(false);}
  },[session]);
  useEffect(()=>{
    let active=true;
    void session.snapshot().then(value=>{if(active){setSnapshot(value);setError('');}}).catch(failure=>{if(active){setSnapshot(null);setError(failure instanceof Error?failure.message:'Curation status unavailable');}}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[session]);
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
      setSteeringMessage(action==='promote'?'Evaluated proposal promoted.':result?.improved?'Evaluation complete: the candidate improved the measured result.':'Evaluation complete: no improvement was reported.');
      await refresh();
    }catch(failure){setSteeringMessage(failure instanceof Error?failure.message:'Proposal outcome unavailable; check before retrying');}
    finally{setBusy(false);}
  }
  return <section aria-label="Publication curation" className="max-h-[55dvh] min-h-0 shrink-0 space-y-3 overflow-y-auto rounded-md border p-3" data-curation-mode={session.bootstrap.mode}>
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">Publication curation</h3><Button variant="outline" size="sm" disabled={loading||busy} onClick={()=>void refresh()}>Refresh curation</Button></div>
    <p className="text-xs text-muted-foreground">{session.bootstrap.mode==='remote'?'Remote workspace':'Embedded workspace'} · {session.bootstrap.scope.publicationId}</p>
    {loading?<p role="status">Loading publication monitoring…</p>:null}
    {error?<p role="alert">{error}</p>:null}
    {snapshot?<PublicationCyclotronPanel mode={session.bootstrap.mode} status={snapshot.status} history={snapshot.history}
      onReview={canReview?async payload=>{await session.publication.review(payload);await refresh();}:undefined}
      onSteer={canSteer&&snapshot.status.features?.steering&&session.bootstrap.bindingRef?classifier=>{setSteering(classifier);setRubric('');setExplanation('');setTrial(null);setSteeringMessage('');}:undefined}/>:null}
    {steering?<form aria-label="Classifier proposal" className="space-y-3 rounded-md border p-3" onSubmit={event=>{event.preventDefault();void steer('evaluate');}}>
      <h4 className="font-semibold">Evaluate classifier proposal</h4>
      <p className="text-sm">A proposal is evaluated before an explicit promotion. Existing classifications are not relabeled by opening this form.</p>
      <label className="block text-sm">Proposed instructions<textarea className="mt-1 block min-h-24 w-full rounded border bg-background p-2" required value={rubric} onChange={event=>{setRubric(event.target.value);setTrial(null);}}/></label>
      <label className="block text-sm">Why make this change?<textarea className="mt-1 block min-h-20 w-full rounded border bg-background p-2" required value={explanation} onChange={event=>setExplanation(event.target.value)}/></label>
      <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy||!canSteer||!rubric.trim()||!explanation.trim()}>Evaluate proposal</Button><Button type="button" variant="outline" disabled={busy||!canSteer||!trial?.improved||!explanation.trim()} onClick={()=>void steer('promote')}>Promote evaluated proposal</Button><Button type="button" variant="ghost" disabled={busy} onClick={()=>setSteering(null)}>Close proposal</Button></div>
      {steeringMessage?<p role="status">{steeringMessage}</p>:null}
    </form>:null}
    {session.bootstrap.priming&&canReview?<ReferencePriming client={session.priming} listId={session.bootstrap.priming.listId} classifiers={session.bootstrap.priming.classifiers}
      onAccepted={draft=>{setPrimingMessage(`Accepted ${draft.rows.length} example item${draft.rows.length===1?'':'s'} for this pinned publication. Operation remains available without priming.`);void refresh();}}/>:null}
    {primingMessage?<p role="status">{primingMessage}</p>:null}
  </section>;
}
