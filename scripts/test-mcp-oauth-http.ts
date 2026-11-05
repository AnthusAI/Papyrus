import assert from "node:assert/strict";
import { createOAuthHttp } from "../lib/mcp/oauth-http";
const operations: Record<string, unknown>[] = [];
const app = createOAuthHttp({
  origin: "https://example.test", clients: { client: ["http://127.0.0.1:4444/callback"] }, secret: "x".repeat(32),
  invoke: async input => { operations.push(input); return input.operation === "issue" ? { code: "test-code" } : {}; },
  identity: async () => ({ principal: { kind: "reader", siteSubject: "ss1_test" }, upstream_expiry: 2000000000 }),
});
async function main() {
  let response = await app.metadata(); assert.equal((await response.json()).issuer, "https://example.test");
  const params = new URLSearchParams({ response_type: "code", client_id: "client", redirect_uri: "http://127.0.0.1:4444/callback", resource: "https://example.test/api/mcp", code_challenge_method: "S256", code_challenge: "A".repeat(43), state: "abc" });
  response = await app.authorize(new Request(`https://example.test/api/mcp/oauth/authorize?${params}`)); assert.equal(response.status, 303);
  const cookie = response.headers.get("set-cookie")!.split(";")[0];
  response = await app.consent(new Request("https://example.test/mcp/authorize", { headers: { cookie } })); const html = await response.text(); const csrf = html.match(/name="csrf" value="([^"]+)"/)![1];
  response = await app.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ csrf, decision: "allow" }) }));
  assert.equal(response.status, 303); assert.equal(new URL(response.headers.get("location")!).searchParams.get("code"), "test-code"); assert.equal(operations[0].operation, "issue");
  const count = operations.length;
  response = await app.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: "csrf=bad&decision=allow" })); assert.equal(response.status, 403);
  response = await app.token(new Request("https://example.test/api/mcp/oauth/token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ grant_type: "authorization_code", client_id: "client", redirect_uri: "http://127.0.0.1:4444/callback", resource: "https://example.test/api/mcp", code: "code", code_verifier: "A".repeat(43) }) })); assert.equal(response.status, 200); assert.equal(operations.at(-1)?.operation, "exchange");
  response = await app.revoke(new Request("https://example.test/api/mcp/oauth/revoke", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ client_id: "client", token: "token" }) })); assert.equal(response.status, 200); assert.equal(operations.at(-1)?.operation, "revoke");
  response = await app.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie, origin: "https://evil.test" }, body: "csrf=bad" })); assert.equal(response.status, 403);
  params.set("redirect_uri", "https://evil.test/"); response = await app.authorize(new Request(`https://example.test/api/mcp/oauth/authorize?${params}`)); assert.equal(response.status, 400); assert.equal(operations.length, count + 2);
  params.set("redirect_uri", "http://127.0.0.1:4444/callback"); params.set("code_challenge_method", "plain"); response = await app.authorize(new Request(`https://example.test/api/mcp/oauth/authorize?${params}`)); assert.equal(response.status, 400);
  params.set("code_challenge_method", "S256");
  const staff = createOAuthHttp({ origin: "https://example.test", clients: { client: ["http://127.0.0.1:4444/callback"] }, secret: "x".repeat(32), invoke: async input => { operations.push(input); return { code: "staff-code" }; }, identity: async () => ({ principal: { kind: "staff", subject: "verified", accessToken: "server-token", idToken: "server-id-token" }, upstream_expiry: 2000000000 }) });
  response = await staff.authorize(new Request(`https://example.test/api/mcp/oauth/authorize?${params}`)); const staffCookie = response.headers.get("set-cookie")!.split(";")[0];
  response = await staff.consent(new Request("https://example.test/mcp/authorize", { headers: { cookie: staffCookie } })); const staffCsrf = (await response.text()).match(/name="csrf" value="([^"]+)"/)![1];
  response = await staff.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie: staffCookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ csrf: staffCsrf, decision: "allow" }) })); assert.equal(response.status, 303); assert.equal((operations.at(-1)?.principal as { kind: string }).kind, "staff");
  console.log("MCP OAuth HTTP checks passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
