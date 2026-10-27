const assert = require('node:assert/strict');
const esbuild = require('esbuild');
const vm = require('node:vm');
(async () => {
  const result = await esbuild.build({ entryPoints: ['components/monitoring-panel.tsx'], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', plugins: [{ name: 'synthetic-boundary', setup(build) {
    build.onResolve({ filter: /^(react|react\/jsx-runtime|next\/navigation)$|monitoring-client$|monitoring-overview-view$|monitoring-overview-fixture$/ }, args => ({ path: args.path, namespace: 'fixture' }));
    build.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ loader: 'js', contents:
      args.path === 'react' ? 'exports.useState=v=>[v, globalThis.h.set]; exports.useEffect=f=>globalThis.h.effects.push(f);' :
      args.path === 'react/jsx-runtime' ? 'exports.jsx=exports.jsxs=(type,props)=>({type,props});' :
      args.path === 'next/navigation' ? 'exports.useSearchParams=()=>new URLSearchParams(globalThis.h.search);' :
      args.path.endsWith('monitoring-client') ? 'exports.loadMonitoringEmailSubmission=id=>{globalThis.h.calls.push(id);return globalThis.h.response}; exports.loadMonitoringOverview=()=>{throw Error("overview read")}; exports.resolveMonitoringEmailArticleLink=()=>{}; exports.importMonitoringEmailCandidates=()=>{};' :
      args.path.endsWith('monitoring-overview-view') ? 'exports.EmailSubmissions=()=>null; exports.MonitoringOverviewView=()=>null;' : 'exports.FIXTURE_ALL_PIPELINE_OVERVIEW={}; exports.FIXTURE_MONITORING_OVERVIEW={};'
    }));
  }}] });
  let finish;
  const h = {search:'receipt=EMAIL%23synthetic', effects:[], calls:[], values:[], set(v){h.values.push(v)}, response:new Promise(r=>finish=r)};
  const context = { module:{exports:{}}, URLSearchParams, h, window: { setInterval() { throw Error('receipt must not start overview refresh'); } } };
  vm.runInNewContext(result.outputFiles[0].text, context);
  const mount = () => { const outer = context.module.exports.MonitoringPanel({isAdmin:true,isDemo:false}); return typeof outer.type === 'function' ? outer.type(outer.props) : outer; };
  mount();
  assert.equal(h.effects.length, 1, 'one exact-receipt loader');
  const cleanup = h.effects[0]();
  assert.deepEqual(h.calls, ['EMAIL#synthetic']);
  cleanup(); finish({submission:{receiptId:'EMAIL#synthetic'}}); await Promise.resolve();
  assert.equal(h.values.some(x=>x?.submission), false, 'closed receipt response discarded');
  for (const response of [{submission:{receiptId:'EMAIL#synthetic'}}, {error:'forbidden'}, {state:'unavailable'}]) {
    h.effects=[]; h.values=[]; h.calls=[]; h.response=Promise.resolve(response);
    mount(); h.effects[0](); await Promise.resolve();
    assert.deepEqual(h.calls,['EMAIL#synthetic']);
    assert.ok(h.values.includes(response), 'response retained without overview fallback');
  }
  h.effects=[]; h.calls=[]; h.search='receipt=';
  mount(); for(const effect of h.effects) effect();
  assert.deepEqual(h.calls,[], 'empty receipt cannot widen scope');
  console.log('PASS: exact receipt, denied/unavailable, empty receipt, and stale response scenarios');
})();
