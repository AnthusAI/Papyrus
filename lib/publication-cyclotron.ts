import type {CyclotronDecision,CyclotronReview} from 'cyclotron/sdk-types';
import type {CyclotronStatus} from 'cyclotron/cyclotron-status';
import type {ReviewControlReview} from 'cyclotron/components/review-control';

export type PublicationScope={accountId:string;publicationId:string;bindingRevision:string};
export type PublicationEnvelope=PublicationScope&{contractVersion:'cyclotron-publication/v1';publicationId:string;bindingRevision:string;features?:{frozenContext:boolean;replayExport:boolean;steering:boolean};outputs:Array<{id:string;question:string;classes:string[];positiveLabel:string|null}>};
export type PublicationStatus=PublicationEnvelope&{classifiers:Record<string,CyclotronStatus>};
export type PublicationRevisionRef={listId:string;itemId:string;revision:number;contentHash:string};
export type PublicationContext={contextId:string;decisionId:string;publicationId:string;sourceRef:PublicationRevisionRef;bindingRef:PublicationRevisionRef;source:{id:string;values:Record<string,unknown>};binding:{values:{accountId:string;publicationId:string;revision:string;outputs:string[]}}};
export type PublicationHistoryRow={decision:CyclotronDecision;item:Record<string,unknown>;state?:string;reviews:Record<string,CyclotronReview>;context?:PublicationContext;historicalContext?:boolean;provenanceUnavailable?:boolean;feedbackReconciliationRequired?:boolean};
export type PublicationHistory=PublicationEnvelope&{history:PublicationHistoryRow[]};
export type PublicationReviewPayload={bindingRevision:string;decisionId:string;classifier:string;predictionVersion:number;predictionFingerprint:string;requestId:string;label:string;explanation:string;reasonCode:string|null;contextId?:string};
export type PublicationSteeringInput={requestId:string;explanation:string}&({action:'evaluate';proposal:Record<string,unknown>}|{action:'promote';trialFingerprint:string});
export type PublicationSteeringPayload=PublicationSteeringInput&{bindingRevision:string;bindingRef:PublicationRevisionRef;classifier:string;expectedFingerprint:string};

function ordered(value:unknown):unknown{
 if(Array.isArray(value))return value.map(ordered);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>[key,ordered(item)]));
 return value;
}

/** Stable cache/component identity; length-safe even when IDs contain delimiters. */
export function publicationScopeKey(scope:PublicationScope):string{
 if([scope.accountId,scope.publicationId,scope.bindingRevision].some(value=>typeof value!=='string'||!value.trim()))throw new Error('Complete publication account scope required');
 return JSON.stringify([scope.accountId,scope.publicationId,scope.bindingRevision]);
}

export function assertPublicationScope(status:PublicationStatus,history:PublicationHistory){
 if(status.contractVersion!=='cyclotron-publication/v1'||history.contractVersion!==status.contractVersion||publicationScopeKey(status)!==publicationScopeKey(history)||status.publicationId!==history.publicationId||status.bindingRevision!==history.bindingRevision)throw new Error('Publication snapshot binding mismatch');
 const outputs=new Set(status.outputs.map(output=>output.id));
 if(!outputs.size||outputs.size!==status.outputs.length||status.outputs.some(output=>status.classifiers[output.id]?.cyclotron.classifier!==output.id)||JSON.stringify(history.outputs)!==JSON.stringify(status.outputs))throw new Error('Publication snapshot is incomplete');
 if(Object.keys(status.classifiers).some(id=>!outputs.has(id))||history.outputs.some(output=>!outputs.has(output.id))||history.history.some(row=>[...Object.keys(row.decision.classifiers),...Object.keys(row.reviews)].some(id=>!outputs.has(id))))throw new Error('Snapshot includes an output outside this publication');
 if(history.history.some(row=>row.context&&(row.context.binding.values.accountId!==status.accountId||row.context.publicationId!==status.publicationId||row.context.decisionId!==row.decision.decisionId||JSON.stringify(ordered(row.context.source.values))!==JSON.stringify(ordered(row.item)))))throw new Error('Historical source context mismatch');
}

/** Explicit output target and incumbent pin; never a global review-rate mutation. */
export function publicationSteeringPayload(status:PublicationStatus,classifier:string,bindingRef:PublicationRevisionRef,command:PublicationSteeringInput):PublicationSteeringPayload{
 if(!status.outputs.some(output=>output.id===classifier)||!status.classifiers[classifier])throw new Error('Steering output is outside this publication');
 if(!command.requestId.trim()||!command.explanation.trim())throw new Error('Steering needs a stable identity and explicit explanation');
 const fingerprint=status.classifiers[classifier].cyclotron.fingerprint;
 if(!fingerprint)throw new Error('Active classifier fingerprint unavailable');
 if(command.action==='evaluate'){
  if(!Object.keys(command.proposal).length||Object.keys(command.proposal).some(key=>!['rubric','tasks','example_ids','dynamic_elements'].includes(key)))throw new Error('Native proposal fields required');
 }else if(command.action!=='promote'||!command.trialFingerprint.trim())throw new Error('An explicitly evaluated trial is required');
 return {...command,explanation:command.explanation.trim(),bindingRevision:status.bindingRevision,bindingRef,classifier,expectedFingerprint:fingerprint};
}

export function publicationReviewPayload(binding:PublicationEnvelope,row:PublicationHistoryRow,classifier:string,review:ReviewControlReview,requestId:string):PublicationReviewPayload{
 if(row.context&&row.context.binding.values.accountId!==binding.accountId)throw new Error('Review account context mismatch');
 if(row.historicalContext||row.provenanceUnavailable||row.feedbackReconciliationRequired||row.context&&row.context.binding.values.revision!==binding.bindingRevision)throw new Error('Historical source or binding revision is read-only');
 const output=binding.outputs.find(output=>output.id===classifier);const prediction=row.decision.classifiers[classifier];
 if(!output||!prediction||review.decisionId!==row.decision.decisionId||review.itemId!==row.decision.itemId)throw new Error('Review does not match the displayed publication decision');
 if(!review.label||!output.classes.includes(review.label))throw new Error('Choose an explicit classification label');
 if(!review.explanation?.trim())throw new Error('Explain this classification before submitting');
 if(!requestId.trim())throw new Error('A stable review request identity is required');
 return {bindingRevision:binding.bindingRevision,decisionId:row.decision.decisionId,classifier,predictionVersion:prediction.version,predictionFingerprint:prediction.fingerprint,requestId,label:review.label,explanation:review.explanation.trim(),reasonCode:review.reasonCode,...(row.context?{contextId:row.context.contextId}:{})};
}

/** Host chooses an authenticated same-origin BFF; storage mode never changes UI semantics. */
export function createPublicationClient(scope:PublicationScope,request:(operation:string,payload:Record<string,unknown>,scope:Readonly<PublicationScope>)=>Promise<PublicationEnvelope&Record<string,unknown>>,currentScope:()=>PublicationScope|null){
 const pinned=Object.freeze({accountId:scope.accountId,publicationId:scope.publicationId,bindingRevision:scope.bindingRevision});
 const key=publicationScopeKey(pinned);
 const assertSelected=()=>{const current=currentScope();if(!current||publicationScopeKey(current)!==key)throw new Error('Publication account selection changed; refresh context');};
 const command=async(operation:string,payload:Record<string,unknown>)=>{
  assertSelected();
  if('bindingRevision' in payload&&payload.bindingRevision!==pinned.bindingRevision)throw new Error('Publication binding changed; refresh context');
  const value=await request(operation,payload,pinned);
  assertSelected();
  if(value.contractVersion!=='cyclotron-publication/v1'||publicationScopeKey(value)!==key)throw new Error('Publication response contract mismatch');
  return value;
 };
 return {scope:pinned,cacheKey:key,command,status:async()=>await command('status',{}) as PublicationStatus,history:async()=>await command('history',{}) as PublicationHistory,
  review:async(payload:PublicationReviewPayload)=>command('review',payload),
  steer:async(payload:PublicationSteeringPayload)=>command('steer',payload),replayRecords:async()=>command('replay',{})};
}
