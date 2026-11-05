import assert from "node:assert/strict";
import { createMcpHandler } from "../lib/mcp/transport";

type Principal = { role: "reader" | "staff" };
let calls = 0;
const handler = createMcpHandler<Principal>({
  enabled: true,
  resourceMetadataUrl: "https://example.test/.well-known/oauth-protected-resource",
  verifyBearer: async token => token === "reader" || token === "staff" ? { role: token } : null,
  listTools: async p => [{ name: "read", inputSchema: { type: "object" } }, ...(p.role === "staff" ? [{ name: "edit", inputSchema: { type: "object" } }] : [])],
  callTool: async (p, name) => {
    calls++;
    if (name === "edit" && p.role !== "staff") throw new Error("Forbidden");
    return { content: [{ type: "text", text: "Seeded article" }], structuredContent: { title: "Seeded article" } };
  },
});
const post = (body: unknown, token?: string, extra: Record<string, string> = {}) => handler(new Request("https://example.test/api/mcp", { method: "POST", headers: { "content-type": "application/json", accept: "application/json, text/event-stream", ...(token ? { authorization: `Bearer ${token}` } : {}), ...extra }, body: JSON.stringify(body) }));
const rpc = (method: string, params: object = {}, id: number | undefined = 1) => ({ jsonrpc: "2.0", method, params, ...(id === undefined ? {} : { id }) });
async function main() {
  let response = await post(rpc("tools/list"), undefined, { "mcp-session-id": "not-auth" });
  assert.equal(response.status, 401); assert.match(response.headers.get("www-authenticate")!, /resource_metadata/);
  response = await post(rpc("tools/call", { name: "read", arguments: {} })); assert.equal(response.status, 401);
  response = await post(rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } }), "reader");
  assert.equal((await response.json()).result.protocolVersion, "2025-06-18"); assert.equal(response.headers.get("cache-control"), "no-store");
  response = await post(rpc("tools/list"), "reader"); assert.deepEqual((await response.json()).result.tools.map((t: { name: string }) => t.name), ["read"]);
  response = await post(rpc("tools/list"), "staff"); assert.equal((await response.json()).result.tools.length, 2);
  response = await post(rpc("tools/call", { name: "edit", arguments: {} }), "reader"); assert.ok((await response.json()).error);
  response = await post(rpc("tools/call", { name: "read", arguments: {} }), "reader"); const result = (await response.json()).result; assert.equal(result.content[0].text, result.structuredContent.title);
  response = await post(rpc("initialize", { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "test", version: "1" } }), "reader"); assert.equal((await response.json()).result.protocolVersion, "2025-11-25");
  response = await post(rpc("tools/list"), "reader", { accept: "application/json-extra, text/event-stream" }); assert.equal(response.status, 406);
  response = await post(rpc("tools/list", { padding: "x".repeat(1024 * 1024) }), "reader"); assert.equal(response.status, 413);
  const unavailable = createMcpHandler<Principal>({ enabled: true, resourceMetadataUrl: "https://example.test/.well-known/oauth-protected-resource", verifyBearer: async () => { throw new Error("offline"); }, listTools: async () => [], callTool: async () => ({ content: [] }) });
  response = await unavailable(new Request("https://example.test/api/mcp", { method: "POST", headers: { authorization: "Bearer test" } })); assert.equal(response.status, 503);
  const unconfigured = createMcpHandler<Principal>({ enabled: true, verifyBearer: async () => ({ role: "staff" }), listTools: async () => [], callTool: async () => ({ content: [] }) });
  response = await unconfigured(new Request("https://example.test/api/mcp", { method: "POST" })); assert.equal(response.status, 404);
  const before = calls;
  response = await post(rpc("tools/call", { name: "read" }), "reader", { origin: "https://evil.test" }); assert.equal(response.status, 403);
  response = await post(rpc("tools/list"), "reader", { "mcp-protocol-version": "invalid" }); assert.equal(response.status, 400); assert.equal(calls, before);
  response = await post({ jsonrpc: "2.0", method: "notifications/initialized" }, "reader"); assert.equal(response.status, 202); assert.equal(await response.text(), "");
  response = await handler(new Request("https://example.test/api/mcp", { method: "GET", headers: { authorization: "Bearer reader", accept: "text/event-stream" } })); assert.equal(response.status, 405);
  const disabled = createMcpHandler<Principal>({ enabled: false, verifyBearer: async () => null, listTools: async () => [], callTool: async () => ({ content: [] }) });
  response = await disabled(new Request("https://example.test/api/mcp", { method: "POST" })); assert.equal(response.status, 404);
  console.log("MCP transport seeded checks passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
