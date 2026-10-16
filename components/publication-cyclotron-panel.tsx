'use client';

import {useRef,useState} from 'react';
import {ReviewControl,type ReviewControlReview} from 'cyclotron/components/review-control';
import {CyclotronStatusView} from 'cyclotron/components/cyclotron-status';
import {assertPublicationScope,publicationScopeKey,publicationReviewPayload,type PublicationStatus,type PublicationHistory,type PublicationHistoryRow,type PublicationReviewPayload} from '../lib/publication-cyclotron';

function requestId(){
 const bytes=crypto.getRandomValues(new Uint8Array(16));
 return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
}

/** Data-only shared operator panel. The authorized host owns reads, writes and refresh. */
type PublicationPanelProps={mode:'embedded'|'remote';status:PublicationStatus;history:PublicationHistory;onReview?:(payload:PublicationReviewPayload)=>Promise<void>;onSteer?:(classifier:string)=>void};
export function PublicationCyclotronPanel(props:PublicationPanelProps){
 assertPublicationScope(props.status,props.history);
 // Remount all drafts, retry identities, pending messages and busy state on scope change.
 return <PublicationControls key={publicationScopeKey(props.status)} {...props}/>;
}
function PublicationControls({mode,status,history,onReview,onSteer}:PublicationPanelProps){
 assertPublicationScope(status,history);
 const context=publicationScopeKey(status);const current=useRef(context);current.current=context;
 const [message,setMessage]=useState<{context:string;key:string;error:boolean;text:string}|null>(null);const [busy,setBusy]=useState<string|null>(null);
 const [editing,setEditing]=useState<Record<string,boolean>>({});const requests=useRef<Record<string,{signature:string;id:string}>>({});
 async function submit(row:PublicationHistoryRow,classifier:string,review:ReviewControlReview){
  const key=`${context}:${row.decision.decisionId}:${classifier}:${row.context?.contextId??'legacy'}`;
  try{
   const signature=JSON.stringify(review);const previous=requests.current[key];
   const id=previous?.signature===signature?previous.id:requestId();requests.current[key]={signature,id};
   const payload=publicationReviewPayload(status,row,classifier,review,id);
   if(!onReview)throw new Error('This host has not enabled human review');
   setBusy(key);setMessage(null);await onReview(payload);
   if(current.current===context){setMessage({context,key,error:false,text:'Human label acknowledged.'});setEditing(old=>({...old,[key]:false}));}
  }catch(error){if(current.current===context)setMessage({context,key,error:true,text:error instanceof Error?error.message:'Review failed; its outcome must be checked before retrying.'});}
  finally{if(current.current===context)setBusy(null);}
 }
 return <section data-publication-scope={context} aria-label="Publication Cyclotron controls" className="space-y-4">
  <header><h2 className="text-lg font-semibold">Cyclotron · {status.publicationId}</h2><p className="text-sm text-muted-foreground">{mode==='embedded'?'Classifier data owned by this deployment.':'Canonical classifier data owned by the shared remote lab.'}</p></header>
  {status.outputs.map(output=><section key={`${context}:${output.id}`} aria-label={output.question} className="space-y-3 rounded-md border p-3">
   <CyclotronStatusView status={status.classifiers[output.id]} classifierName={output.question} variant="card"/>
   {onSteer?<button type="button" disabled={Boolean(busy)} onClick={()=>onSteer(output.id)}>Evaluate classifier proposal</button>:null}
   {history.history.map(row=>{
    const prediction=row.decision.classifiers[output.id];if(!prediction)return null;
    const key=`${context}:${row.decision.decisionId}:${output.id}:${row.context?.contextId??'legacy'}`;const saved=row.reviews[output.id];const historical=Boolean(row.historicalContext||row.provenanceUnavailable||row.feedbackReconciliationRequired);
    return <article key={key} className="space-y-2 rounded-md border p-3">
     {historical?<p className="text-sm">Historical source or binding revision · read-only</p>:null}{row.feedbackReconciliationRequired?<p role="status">Canonical feedback changed; provenance reconciliation is required before replay.</p>:null}<h3 className="font-medium">{String(row.item.title??row.decision.itemId)}</h3>
     <p className="whitespace-pre-wrap text-sm">{String(row.item.abstract??row.item.text??'')}</p>
     {!saved||editing[key]?<p className="text-sm" role="status">{historical?'This source revision is read-only.':!onReview?'Human review is unavailable in this session.':busy===key?'Submitting review… Your selection is preserved; wait for acknowledgement.':'Choose a label to enable Submit review. Explanation is optional.'}</p>:null}
     <ReviewControl key={`${key}:${Boolean(editing[key])}`} itemId={`${row.decision.itemId}:${Array.from(new TextEncoder().encode(context+':'+output.id+':'+(row.context?.contextId??'legacy')),byte=>byte.toString(16).padStart(2,'0')).join('')}`} decision={{decisionId:row.decision.decisionId,...prediction,classes:output.classes}} question={output.question} mode="labels" positiveLabel={output.positiveLabel??undefined} disabled={Boolean(busy)||!onReview||historical} value={saved&&!editing[key]?{label:saved.label,reasonCode:saved.reasonCode,explanation:saved.explanation}:undefined} onReview={review=>void submit(row,output.id,{...review,itemId:row.decision.itemId})}/>
     {message?.context===context&&message.key===key?<p role={message.error?'alert':'status'} className="text-sm">{message.text}</p>:null}
     {saved&&onReview&&!historical&&!editing[key]?<button type="button" disabled={Boolean(busy)} onClick={()=>setEditing(old=>({...old,[key]:true}))}>Correct human label</button>:null}
     <details><summary>Decision provenance and version</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify({itemId:row.decision.itemId,source:row.item.source_uri,decisionId:row.decision.decisionId,prediction,bindingRevision:row.context?.binding.values.revision??status.bindingRevision,sourceRef:row.context?.sourceRef,contextId:row.context?.contextId},null,2)}</pre></details>
    </article>;
   })}
  </section>)}
 </section>;
}
