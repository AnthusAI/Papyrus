import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { once } from "node:events";
import { chromium } from "playwright";
import { createOAuthHttp } from "../lib/mcp/oauth-http";

async function listen(server: Server): Promise<string> {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing listener address");
  return `http://127.0.0.1:${address.port}`;
}

async function main() {
  const callback = createServer((request, response) => {
    response.writeHead(200, { "Content-Type": "text/plain" });
    response.end(`Arrived ${request.url}`);
  });
  const callbackOrigin = await listen(callback);
  let handle: (request: Request) => Promise<Response>;
  const server = createServer(async (request, response) => {
    try {
      const chunks: Buffer[] = [];
      for await (const chunk of request) chunks.push(Buffer.from(chunk));
      const url = `http://127.0.0.1:${(server.address() as { port: number }).port}${request.url}`;
      const headers = new Headers();
      for (const [name, value] of Object.entries(request.headers)) if (value !== undefined) headers.set(name, Array.isArray(value) ? value.join(", ") : value);
      const webRequest = new Request(url, { method: request.method, headers, ...(request.method === "POST" ? { body: Buffer.concat(chunks) } : {}) });
      const result = await handle(webRequest);
      response.writeHead(result.status, Object.fromEntries(result.headers));
      response.end(Buffer.from(await result.arrayBuffer()));
    } catch { response.writeHead(500); response.end(); }
  });
  const origin = await listen(server);
  const redirect = `${callbackOrigin}/callback`;
  const oauth = createOAuthHttp({ origin, clients: { client: [redirect] }, secret: "x".repeat(32),
    identity: async () => ({ principal: { kind: "reader", siteSubject: `ss1_${"A".repeat(43)}` }, upstream_expiry: 4102444800 }),
    invoke: async () => ({ code: "browser-code" }) });
  handle = request => new URL(request.url).pathname === "/api/mcp/oauth/authorize" ? oauth.authorize(request) : oauth.consent(request);
  let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.PAPYRUS_CHROMIUM_PATH ? { executablePath: process.env.PAPYRUS_CHROMIUM_PATH } : {}) });
    const page = await browser.newPage();
    page.setDefaultTimeout(7000);
    page.setDefaultNavigationTimeout(7000);
    const params = new URLSearchParams({ response_type: "code", client_id: "client", redirect_uri: redirect,
      resource: `${origin}/api/mcp`, code_challenge_method: "S256", code_challenge: "A".repeat(43), state: "browser-state" });
    await page.goto(`${origin}/api/mcp/oauth/authorize?${params}`);
    await page.getByLabel("Reader").check();
    await Promise.all([page.waitForURL(url => url.origin === callbackOrigin), page.getByRole("button", { name: "Allow" }).click()]);
    assert.equal(new URL(page.url()).searchParams.get("code"), "browser-code");
    assert.equal(new URL(page.url()).searchParams.get("state"), "browser-state");
    assert.equal(new URL(page.url()).searchParams.get("iss"), origin);
    assert.match(await page.locator("body").innerText(), /Arrived/);
  } finally {
    await browser?.close();
    await Promise.all([new Promise<void>(resolve => server.close(() => resolve())), new Promise<void>(resolve => callback.close(() => resolve()))]);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
