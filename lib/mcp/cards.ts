/** Optional MCP Apps. Tool results remain unchanged for hosts without app support. */
const referenceUri = "ui://papyrus/reference";
const storyUri = "ui://papyrus/story";
const mimeType = "text/html;profile=mcp-app";
const ui = { csp: { connectDomains: [], resourceDomains: [] } };

export function listMcpAppResources() {
  return [
    { uri: referenceUri, name: "Reference card", mimeType, _meta: { ui } },
    { uri: storyUri, name: "Story card", mimeType, _meta: { ui } },
  ];
}

export function withMcpAppMetadata<T extends { name: string; [key: string]: unknown }>(tool: T): T & { _meta?: { ui: { resourceUri: string } } } {
  const uri = tool.name === "reference_get" ? referenceUri : tool.name === "story_get" ? storyUri : undefined;
  if (!uri) return tool;
  return { ...tool, _meta: { ...(typeof tool._meta === "object" && tool._meta ? tool._meta : {}), ui: { resourceUri: uri } } };
}

export function withMcpAppResult<T extends { [key: string]: unknown }>(result: T, availableTools: string[]): T {
  return { ...result, _meta: { ...(typeof result._meta === "object" && result._meta ? result._meta : {}), papyrus: { availableTools: [...availableTools] } } };
}

export function readMcpAppResource(uri: string) {
  if (uri !== referenceUri && uri !== storyUri) throw new Error("Unknown MCP App resource");
  return { contents: [{ uri, mimeType, _meta: { ui }, text: cardHtml(uri === referenceUri ? "reference" : "story") }] };
}

function cardHtml(kind: "reference" | "story") {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{color-scheme:light dark;font:15px system-ui,sans-serif}body{margin:0;padding:16px}main{max-width:48rem}h1{font-size:1.25rem;margin:.2em 0}h2{font-size:1rem}button,input,textarea{font:inherit}button{margin:.25rem .4rem .25rem 0;padding:.4rem .7rem}dl{display:grid;grid-template-columns:minmax(8rem,auto) 1fr;gap:.4rem}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}label{display:block;margin:.5rem 0}textarea{display:block;width:100%;max-width:32rem}#status{min-height:1.5em}nav{margin-bottom:.5rem}
</style></head><body><main><nav><button id="back" hidden>Back</button></nav><h1 id="title">Loading ${kind}…</h1><p id="status" role="status" aria-live="polite"></p><section id="details" aria-label="Details"></section><section id="actions" aria-label="Actions"></section><section id="extra" aria-label="Additional information"></section></main><script>
(() => {
  const initialKind = ${JSON.stringify(kind)};
  const title = document.getElementById('title'), details = document.getElementById('details'), actions = document.getElementById('actions'), extra = document.getElementById('extra'), status = document.getElementById('status'), back = document.getElementById('back');
  let sequence = 0, input = {}, current = null, currentKind = initialKind, history = [], available = new Set();
  const pending = new Map();
  function send(method, params) { parent.postMessage({jsonrpc:'2.0',method,params}, '*'); }
  function request(method, params) { return new Promise((resolve,reject) => { const id = ++sequence; pending.set(id,{resolve,reject}); parent.postMessage({jsonrpc:'2.0',id,method,params},'*'); }); }
  function call(name, args) { return request('tools/call',{name,arguments:args}).then(result => { if(result.isError) { const error = new Error(result.structuredContent?.message || result.content?.[0]?.text || 'The request failed'); error.code = result.structuredContent?.code; throw error; } return result.structuredContent || {}; }); }
  function button(label, handler, target = actions) { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; b.addEventListener('click',handler); target.append(b); return b; }
  function print(value, target) { const pre = document.createElement('pre'); pre.textContent = typeof value === 'string' ? value : JSON.stringify(value,null,2); target.append(pre); }
  function renderRecord(record, type) {
    current = record; currentKind = type; title.textContent = record.title || (type === 'reference' ? 'Reference' : 'Story'); details.replaceChildren(); actions.replaceChildren(); extra.replaceChildren(); back.hidden = history.length === 0;
    const dl = document.createElement('dl');
    for (const [key,value] of Object.entries(record)) { if (value == null || key === 'title') continue; const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = key.replace(/([A-Z])/g,' $1'); dd.textContent = typeof value === 'object' ? JSON.stringify(value,null,2) : String(value); dl.append(dt,dd); }
    details.append(dl); addNavigation(record,details);
    const lineageId = record.lineageId || input.lineageId;
    if (!lineageId) return;
    button('Refresh', () => refresh());
    if (type === 'story') {
      if (available.has('story_evidence')) button('Evidence', () => show('story_evidence',{lineageId},'Evidence'));
      if (available.has('story_next')) button('Next step', () => show('story_next',{lineageId},'Next step'));
    } else {
      if (available.has('reference_decide')) { const noteLabel = document.createElement('label'); noteLabel.textContent = 'Decision note (required to reject)'; const note = document.createElement('textarea'); noteLabel.append(note); actions.append(noteLabel);
      for (const decision of ['accept','reject']) button(decision === 'accept' ? 'Accept' : 'Reject', () => { if (decision === 'reject' && !note.value.trim()) { status.textContent = 'Enter a reason to reject.'; return; } mutate('reference_decide',{lineageId,expectedCurrentVersionId:record.currentVersionId || record.id,expectedRevision:record.updatedAt,decision,...(note.value.trim() ? {note:note.value.trim()} : {})}); }); }
    }
    if (available.has(type + '_star')) { const label = document.createElement('label'); label.textContent = 'Stars (1–5) '; const stars = document.createElement('input'); stars.type='number'; stars.min='1'; stars.max='5'; stars.step='1'; label.append(stars); actions.append(label);
    button('Save stars', () => { const value = Number(stars.value); if (!Number.isInteger(value) || value < 1 || value > 5) { status.textContent = 'Enter a whole number from 1 to 5.'; return; } mutate(type + '_star',{lineageId,expectedCurrentVersionId:record.currentVersionId || record.id,expectedRevision:record.updatedAt,stars:value}); }); }
  }
  async function refresh() { try { const result = await call(currentKind + '_get',{lineageId:current?.lineageId || input.lineageId}); renderRecord(result[currentKind],currentKind); } catch(e) { status.textContent = e.message; } }
  async function mutate(name,args) { try { await call(name,args); status.textContent = 'Saved. Refreshing…'; await refresh(); status.textContent = 'Saved.'; } catch(e) { if (e.code === 'stale_revision' || e.code === 'stale_version') { status.textContent = 'This record changed. Refreshing; review it before trying again.'; await refresh(); } else status.textContent = e.message; } }
  async function show(name,args,heading) { try { const result = await call(name,args); extra.replaceChildren(); const h = document.createElement('h2'); h.textContent = heading; extra.append(h); print(result,extra); addNavigation(result,extra); } catch(e) { status.textContent = e.message; } }
  function addNavigation(value,target) { if (!value || typeof value !== 'object') return; if (Array.isArray(value)) { value.forEach(item => addNavigation(item,target)); return; } for (const [key,item] of Object.entries(value)) { if ((key === 'referenceLineageId' || key === 'storyLineageId') && typeof item === 'string') { const type = key.startsWith('reference') ? 'reference' : 'story'; button('Open ' + type,async () => { try { const result = await call(type + '_get',{lineageId:item}); history.push({record:current,type:currentKind}); renderRecord(result[type],type); } catch(e) { status.textContent=e.message; } },target); } else if (typeof item === 'object') addNavigation(item,target); } }
  back.addEventListener('click',() => { const previous = history.pop(); if(previous) renderRecord(previous.record,previous.type); });
  window.addEventListener('message', event => { if(event.source !== parent || !event.data || event.data.jsonrpc !== '2.0') return; const msg = event.data; if (msg.id != null && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result); return; } if(msg.method === 'ui/notifications/tool-input') input = msg.params?.arguments || {}; if(msg.method === 'ui/notifications/tool-result') { const names = msg.params?._meta?.papyrus?.availableTools; available = new Set(Array.isArray(names) ? names.filter(name => typeof name === 'string') : []); const data = msg.params?.structuredContent; if(msg.params?.isError) status.textContent = data?.message || 'Unable to load this record.'; else if(data?.[initialKind]) { renderRecord(data[initialKind],initialKind); } } });
  request('ui/initialize',{appInfo:{name:'Papyrus cards',version:'1.0.0'},appCapabilities:{},protocolVersion:'2026-01-26'}).then(() => send('ui/notifications/initialized',{})).catch(() => { status.textContent='Unable to connect to the host.'; });
})();
</script></body></html>`;
}
