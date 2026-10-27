const assert = require('node:assert/strict');
const { buildSync } = require('esbuild');
const vm = require('node:vm');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'email-handoff-'));
(async () => {
  const out = path.join(temp, 'client.cjs');
  buildSync({entryPoints:['lib/monitoring-client.ts'],outfile:out,bundle:true,platform:'node',format:'cjs',external:['aws-amplify/data']});
  for (const failQueue of [false,true]) {
    const calls=[];
    const sandboxModule={exports:{}};
    vm.runInNewContext(fs.readFileSync(out,'utf8'), {module:sandboxModule,exports:sandboxModule.exports,process,queueMicrotask,setTimeout,clearTimeout,performance,require(name){
      assert.equal(name,'aws-amplify/data');
      return {generateClient({authMode}) { assert.equal(authMode,'userPool'); return {async graphql({query,variables}) {
        const input=JSON.parse(variables.input); calls.push({query,input});
        assert.equal(input.receiptId,'EMAIL#synthetic');
        if(query.includes('IntakeEmailSubmissionReferences')) return {data:{intakeEmailSubmissionReferences:JSON.stringify({ok:true,references:input.items.map(i=>({id:`ref-${i.candidateIndex}`}))})}};
        assert.ok(query.includes('MonitoringQueueEmailReference'));
        assert.equal(input.referenceId,`ref-${input.candidateIndex}`);
        return {data:{monitoringQueueEmailReference:JSON.stringify(failQueue?{error:'unavailable'}:{queued:true})}};
      }}}};
    }});
    const result=await sandboxModule.exports.importMonitoringEmailCandidates('EMAIL#synthetic',Array.from({length:21},(_,i)=>({candidateIndex:i,source_uri:`https://example.org/${i}`})));
    assert.equal(result.imported,failQueue?20:21);
    assert.equal(Boolean(result.error),failQueue);
    assert.equal(calls.filter(x=>x.query.includes('MonitoringQueueEmailReference')).length,failQueue?1:21);
    assert.ok(calls.every(x=>!x.query.includes('monitoringOverview')));
  }
  // Accept and Reject are the editor's words; the wire carries release and discard with the optional reason.
  const sent=[];
  const decideModule={exports:{}};
  vm.runInNewContext(fs.readFileSync(out,'utf8'), {module:decideModule,exports:decideModule.exports,process,queueMicrotask,setTimeout,clearTimeout,performance,require(){
    return {generateClient({authMode}) { assert.equal(authMode,'userPool'); return {async graphql({query,variables}) {
      assert.ok(query.includes('monitoringDecideEmailSubmission')); sent.push(variables);
      return {data:{monitoringDecideEmailSubmission:JSON.stringify({ok:true,already:false,quarantine:{state:'release_requested',decision:null,failure:null}})}};
    }}}};
  }});
  const accepted=await decideModule.exports.decideMonitoringEmailSubmission('EMAIL#synthetic','accept','Known sender');
  await decideModule.exports.decideMonitoringEmailSubmission('EMAIL#synthetic','reject','');
  assert.deepEqual(JSON.parse(JSON.stringify(sent)),[{receiptId:'EMAIL#synthetic',decision:'release',reason:'Known sender'},{receiptId:'EMAIL#synthetic',decision:'discard',reason:''}]);
  assert.equal(accepted.ok,true);
  console.log('PASS: selected Reference handoff, 20-item batches, recoverable queue failures, and Accept/Reject decisions');
})().finally(()=>fs.rmSync(temp,{recursive:true,force:true}));
