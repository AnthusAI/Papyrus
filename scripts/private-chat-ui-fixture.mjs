import assert from "node:assert/strict";
import { createServer } from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";

const bundle = await build({
  entryPoints: [fileURLToPath(new URL("./fixtures/private-chat-panel.tsx", import.meta.url))],
  bundle: true,
  write: false,
  outfile: "app.js",
  platform: "browser",
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"development"' },
});
const requests = [];
const messages = [];
let sendCount = 0;
const server = createServer(async (request, response) => {
  if (request.url === "/app.js") {
    response.setHeader("Content-Type", "text/javascript");
    response.end(bundle.outputFiles.find((file) => file.path.endsWith(".js")).contents);
    return;
  }
  if (request.url === "/app.css") {
    response.setHeader("Content-Type", "text/css");
    response.end(bundle.outputFiles.find((file) => file.path.endsWith(".css")).contents);
    return;
  }
  if (request.url === "/") {
    response.setHeader("Set-Cookie", "papyrus-session=synthetic-session; HttpOnly; SameSite=Lax; Path=/");
    response.end('<!doctype html><html><head><link rel="stylesheet" href="/app.css"><style>html,body,#root{height:100%;margin:0;display:flex;flex-direction:column}</style></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
    return;
  }
  if (!request.url?.startsWith("/api/newsroom/chat/")) {
    response.writeHead(404).end();
    return;
  }
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const body = Buffer.concat(chunks).toString("utf8");
  requests.push({ url: request.url, method: request.method, headers: request.headers, body });
  const respond = (payload) => {
    response.writeHead(200, { "content-type": "application/json", "cache-control": "no-store" });
    response.end(JSON.stringify(payload));
  };
  if (request.url === "/api/newsroom/chat/private-channel" && request.method === "POST") {
    respond({ channel_id: "private-channel", participants: [{ kind: "human", actor_id: "server-editor" }, { kind: "bot", actor_id: "papyrus-assistant" }] });
    return;
  }
  if (request.url === "/api/newsroom/chat/channels/private-channel/messages" && request.method === "GET") {
    respond({ messages });
    return;
  }
  if (request.url === "/api/newsroom/chat/channels/private-channel/messages" && request.method === "POST") {
    sendCount += 1;
    const sent = JSON.parse(body);
    const message = {
      message_id: `human-${sendCount}`,
      channel_id: "private-channel",
      seq: sendCount,
      author_kind: "human",
      body: sent.body,
      addressed_to_bot_id: "papyrus-assistant",
      created_at: `2026-10-24T00:00:0${sendCount}.000Z`,
    };
    messages.push(message);
    if (sendCount === 2) messages.push({
      message_id: "assistant-1",
      channel_id: "private-channel",
      seq: 3,
      author_kind: "bot",
      body: "Private runtime reply",
      addressed_to_bot_id: null,
      created_at: "2026-10-24T00:00:03.000Z",
    });
    respond({ message, turn_id: "turn-1" });
    return;
  }
  response.writeHead(404).end();
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined, headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.getByText("Private conversation for your selected Account.").waitFor();
  const input = page.getByRole("textbox", { name: "Message input" });
  await input.fill("First private message");
  await input.press("Enter");
  await page.getByText("First private message", { exact: true }).waitFor();
  const send = page.getByRole("button", { name: "Send message", exact: true });
  assert.equal(await input.isDisabled(), false, "the shared composer remains available while a reply is running");
  await input.fill("Second private message");
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find((candidate) => candidate.getAttribute("aria-label") === "Send message");
    return button instanceof HTMLButtonElement && !button.disabled;
  }, undefined, { timeout: 5_000 });
  assert.equal(await send.isDisabled(), false, "a second message can be sent before the reply arrives");
  await input.press("Enter");
  await page.getByText("Private runtime reply", { exact: true }).waitFor({ timeout: 10_000 });
  assert.equal(sendCount, 2, "each deliberate send reaches the private adapter exactly once");
  const channelRequests = requests.filter((request) => request.url.endsWith("/private-channel"));
  const sendRequests = requests.filter((request) => request.method === "POST" && request.url.endsWith("/messages"));
  assert.equal(channelRequests.length, 1);
  assert.equal(sendRequests.length, 2);
  for (const request of [...channelRequests, ...sendRequests]) {
    assert.equal(request.headers.cookie, "papyrus-session=synthetic-session", "the same-origin session cookie reaches the host route");
    assert.equal(request.headers.authorization, undefined, "the client does not forward a bearer token");
    assert.equal(request.headers.origin, `http://127.0.0.1:${server.address().port}`);
  }
  for (const request of sendRequests) {
    const payload = JSON.parse(request.body);
    assert.deepEqual(Object.keys(payload), ["body"], "the browser sends no tenant, editor or bot identity");
    assert.ok(request.headers["idempotency-key"]);
  }
  assert.deepEqual(errors, []);
  console.log("PASS: shared UI sends through the private host route once, preserves pending-reply sends, and renders the reply");
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
