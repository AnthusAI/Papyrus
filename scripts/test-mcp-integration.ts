import assert from 'node:assert/strict';
import { createSiteMcpHandler } from '../lib/mcp/server';
import type { McpPrincipal } from '../lib/mcp/oauth-runtime';

const staff = { kind: 'staff', subject: 'staff-1', accessToken: 'private-token', idToken: 'private-id-token' } as McpPrincipal;
const reader: McpPrincipal = { kind: 'reader', siteSubject: 'ss1_' + 'a'.repeat(43) };
const requests: Array<Record<string, unknown>> = [];
const config = { oauth: { origin: 'https://example.test', functionArn: 'arn:aws:lambda:us-east-1:123456789012:function:oauth' }, domain: { functionArn: 'arn:aws:lambda:us-east-1:123456789012:function:tools' } };
const handler = createSiteMcpHandler({ ...config,
  verify: async request => { assert.deepEqual(request, { operation: 'verify', token: 'staff', resource: 'https://example.test/api/mcp' }); return { principal: staff }; },
  invoke: async (_arn, request) => { requests.push(request); return request.operation === 'list' ? { tools: [{ name: 'story_get', inputSchema: { type: 'object' } }] } : { content: [{ type: 'text', text: 'Seeded story' }], structuredContent: { story: { title: 'Seeded story' } } }; },
});
const post = (h: typeof handler, method: string, params = {}, token = 'staff') => h(new Request('https://example.test/api/mcp', { method: 'POST', headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json', accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) }));
async function main() {
  const list = await (await post(handler, 'tools/list')).json();
  assert.equal(list.result.tools[0]._meta.ui.resourceUri, 'ui://papyrus/story');
  const call = await (await post(handler, 'tools/call', { name: 'story_get', arguments: { lineageId: '1' } })).json();
  assert.equal(call.result.content[0].text, 'Seeded story'); assert.equal(call.result.structuredContent.story.title, 'Seeded story');
  assert.deepEqual(call.result._meta.papyrus.availableTools, ['story_get']);
  assert.ok(!JSON.stringify(call).includes('private-token')); assert.ok(!JSON.stringify(call).includes('private-id-token'));
  assert.deepEqual(requests.find(x => x.operation === 'call')?.principal, { kind: 'staff', subject: 'staff-1', idToken: 'private-id-token' });
  const resources = await (await post(handler, 'resources/read', { uri: 'ui://papyrus/story' })).json(); assert.match(resources.result.contents[0].mimeType, /mcp-app/);
  const readerHandler = createSiteMcpHandler({ ...config, verify: async () => ({ principal: reader }), invoke: async (_arn, request) => { assert.deepEqual(request.principal, reader); return { tools: [{ name: 'reader_submit', inputSchema: { type: 'object' } }] }; } });
  assert.equal((await (await post(readerHandler, 'tools/list')).json()).result.tools[0].name, 'reader_submit');
  assert.ok((await (await post(readerHandler, 'tools/call', { name: 'story_get' })).json()).error);
  const missing = createSiteMcpHandler({ ...config, domain: null }); assert.equal((await post(missing, 'tools/list')).status, 404);
  const invalid = createSiteMcpHandler({ ...config, verify: async () => ({ principal: null }) }); const challenge = await post(invalid, 'tools/list'); assert.equal(challenge.status, 401); assert.match(challenge.headers.get('www-authenticate')!, /\/api\/mcp\/oauth\/resource/);
  const unavailable = createSiteMcpHandler({ ...config, verify: async () => { throw Error('unavailable'); } }); assert.equal((await post(unavailable, 'tools/list')).status, 503);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
