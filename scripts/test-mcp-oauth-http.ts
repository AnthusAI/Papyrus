import assert from "node:assert/strict";
import { oauthRoute } from "../lib/mcp/oauth-site";
import { createOAuthHttp } from "../lib/mcp/oauth-http";
const operations: Record<string, unknown>[] = [];
const app = createOAuthHttp({
  origin: "https://example.test", clients: { client: ["http://127.0.0.1:4444/callback"] }, secret: "x".repeat(32),
  invoke: async input => { operations.push(input); return input.operation === "issue" ? { code: "test-code" } : {}; },
  identity: async () => ({ principal: { kind: "reader", siteSubject: "ss1_test" }, upstream_expiry: 2000000000 }),
});
async function main() {
  const dependencies = { config: () => ({ origin: "https://example.test", functionArn: "test" }), clients: () => ({ client: ["https://client.test/cb"] }), service: async () => { throw new Error("secret unavailable"); } };
  let response = await oauthRoute("metadata", new Request("https://example.test/.well-known/oauth-authorization-server"), dependencies); const metadata = await response.json(); assert.equal(metadata.issuer, "https://example.test"); assert.equal(metadata.authorization_response_iss_parameter_supported, true);
  response = await oauthRoute("resource", new Request("https://example.test/api/mcp/oauth/resource"), dependencies); assert.equal((await response.json()).resource, "https://example.test/api/mcp");
  response = await oauthRoute("consent", new Request("https://example.test/mcp/authorize"), dependencies); assert.equal(response.status, 503); assert.match(await response.text(), /Try again later/);
  response = await app.metadata(); assert.equal((await response.json()).issuer, "https://example.test");
  const params = new URLSearchParams({ response_type: "code", client_id: "client", redirect_uri: "http://127.0.0.1:4444/callback", resource: "https://example.test/api/mcp", code_challenge_method: "S256", code_challenge: "A".repeat(43), state: "abc" });
  response = await app.authorize(new Request(`https://example.test/api/mcp/oauth/authorize?${params}`)); assert.equal(response.status, 303);
  const cookie = response.headers.get("set-cookie")!.split(";")[0];
  response = await app.consent(new Request("https://example.test/mcp/authorize", { headers: { cookie } })); const html = await response.text(); const csrf = html.match(/name="csrf" value="([^"]+)"/)![1];
  response = await app.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ csrf, decision: "allow", identity: "reader" }) }));
  assert.equal(response.status, 303); assert.equal(new URL(response.headers.get("location")!).searchParams.get("code"), "test-code"); assert.equal(new URL(response.headers.get("location")!).searchParams.get("iss"), "https://example.test"); assert.equal(new URL(response.headers.get("location")!).searchParams.get("state"), "abc"); assert.equal(operations[0].operation, "issue");
  response = await app.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ csrf, decision: "deny" }) }));
  assert.equal(new URL(response.headers.get("location")!).searchParams.get("iss"), "https://example.test"); assert.equal(new URL(response.headers.get("location")!).searchParams.get("state"), "abc"); assert.equal(new URL(response.headers.get("location")!).searchParams.get("error"), "access_denied");
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
  response = await staff.consent(new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie: staffCookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ csrf: staffCsrf, decision: "allow", identity: "staff" }) })); assert.equal(response.status, 303); assert.equal((operations.at(-1)?.principal as { kind: string }).kind, "staff");
  let signedIn = false;
  const returning = createOAuthHttp({ origin: "https://example.test", clients: { client: ["http://127.0.0.1:4444/callback"] }, secret: "x".repeat(32), invoke: async () => ({ code: "return-code" }), identity: async (_request, kind) => signedIn && kind === "reader" ? { principal: { kind: "reader", siteSubject: "ss1_test" }, upstream_expiry: 2000000000 } : null });
  response = await returning.authorize(new Request(`https://example.test/api/mcp/oauth/authorize?${params}`)); const returnCookie = response.headers.get("set-cookie")!.split(";")[0];
  response = await returning.consent(new Request("https://example.test/mcp/authorize", { headers: { cookie: returnCookie } })); const returnCsrf = (await response.text()).match(/name="csrf" value="([^"]+)"/)![1];
  const submit = () => new Request("https://example.test/mcp/authorize", { method: "POST", headers: { cookie: returnCookie, origin: "https://example.test", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ csrf: returnCsrf, decision: "allow", identity: "reader" }) });
  response = await returning.consent(submit()); assert.equal(response.status, 401); assert.match(await response.text(), /Sign in as a reader/);
  signedIn = true; response = await returning.consent(submit()); assert.equal(response.status, 303);
  console.log("MCP OAuth HTTP checks passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
