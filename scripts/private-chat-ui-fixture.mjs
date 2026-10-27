import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";

const fixtureMode = process.argv[2] ?? "conversation";
const mobile = fixtureMode.startsWith("mobile");
const mode = fixtureMode.startsWith("mobile-") ? fixtureMode.slice(7) : fixtureMode;
const fixtureColors = process.env.PAPYRUS_CHAT_TEST_THEME === "dark" ? "--paper-rgb:22 26 26;--ink:#eef0eb;--org-ink:#eef0eb;--org-paper:#161a1a" : "--paper-rgb:255 255 255;--ink:#111;--org-ink:#111;--org-paper:white";
const bundle = await build({
  entryPoints: [fileURLToPath(new URL(mobile ? "./fixtures/mobile-chat-frame.tsx" : "./fixtures/private-chat-panel.tsx", import.meta.url))],
  plugins: [{ name: "synthetic-newsroom-session", setup(builder) {
    builder.onResolve({ filter: /^aws-amplify\/utils$/ }, () => ({ path: "utils", namespace: "synthetic" }));
    builder.onLoad({ filter: /^utils$/, namespace: "synthetic" }, () => ({ contents: `export const Hub = { listen: (_, fn) => { window.testAuthEvent = event => fn({ payload: { event } }); return () => {}; } };`, loader: "js" }));
    builder.onResolve({ filter: /^aws-amplify\/auth$/ }, () => ({ path: "auth", namespace: "synthetic" }));
    builder.onLoad({ filter: /.*/, namespace: "synthetic" }, () => ({ contents: `export async function fetchAuthSession() { return { tokens: { accessToken: { toString: () => sessionStorage.getItem("test-editor") || "synthetic-editor-a" } } }; }`, loader: "js" }));
  } }],
  bundle: true,
  write: false,
  outfile: "app.js",
  platform: "browser",
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"development"', "process.env": "{}" },
});
let expired = false;
const requests = [];
const messages = mode === "mobile" ? Array.from({ length: 35 }, (_, index) => ({ message_id: `fixture-${index}`, channel_id: "private-channel", seq: index + 1, author_kind: "bot", body: `Synthetic scroll test message ${index + 1}. This is local fixture content.`, created_at: "2026-10-24T00:00:00.000Z" })) : [];
let sendCount = 0;
const server = createServer(async (request, response) => {
  if (request.url === "/app.js") {
    response.setHeader("Content-Type", "text/javascript");
    response.end(bundle.outputFiles.find((file) => file.path.endsWith(".js")).contents);
    return;
  }
  if (request.url === "/app.css") {
    response.setHeader("Content-Type", "text/css");
    response.end(Buffer.concat([bundle.outputFiles.find((file) => file.path.endsWith(".css")).contents, Buffer.from(mobile ? readFileSync(new URL("../app/globals.css", import.meta.url), "utf8").replace(/^@import[^;]+;/gm, "") + readFileSync(new URL("../components/newsroom-organizer.css", import.meta.url), "utf8") : "")]));
    return;
  }
  if (request.url === "/" || request.url === "/public" || request.url?.startsWith("/?")) {
    response.setHeader("Set-Cookie", "papyrus-session=synthetic-session; HttpOnly; SameSite=Lax; Path=/");
    response.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/app.css"><style>html,body,#root{height:100%;margin:0;display:flex;flex-direction:column;${fixtureColors};--kb-theme-ui-font:Arial,sans-serif;--kb-theme-title-font:Georgia,serif;background:rgb(var(--paper-rgb))}</style></head><body><div id="root"></div><script src="/app.js"></script></body></html>`);
    return;
  }
  if (request.url?.startsWith("/api/auth/prospectus/")) throw new Error("Private chat must not request Prospectus connection or account access");
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
  if (request.headers.authorization === "Bearer synthetic-editor-b") {
    if (request.url === "/api/newsroom/chat/private-channel") respond({ channel_id: "editor-b-channel", participants: [{ kind: "human", actor_id: "editor-b" }] });
    else if (request.url === "/api/newsroom/chat/channels/editor-b-channel/messages" && request.method === "GET") respond({ messages: [{ message_id: "editor-b-message", channel_id: "editor-b-channel", seq: 1, author_kind: "bot", body: "Second editor private history", created_at: "2026-10-24T00:00:03.000Z" }] });
    else { response.writeHead(403, { "content-type": "application/json" }); response.end(JSON.stringify({ error: "chat_account_access_denied" })); }
    return;
  }
  if (request.url === "/api/newsroom/chat/private-channel" && request.method === "POST") {
    respond({ channel_id: "private-channel", participants: [{ kind: "human", actor_id: "server-editor" }, { kind: "bot", actor_id: "papyrus-assistant" }] });
    return;
  }
  if (request.url === "/api/newsroom/chat/channels/private-channel/messages" && request.method === "GET") {
    if (mode === "poll-expiry" && messages.length > 0) {
      response.writeHead(401, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "sign_in_required" }));
      return;
    }
    respond({ messages });
    return;
  }
  if (request.url === "/api/newsroom/chat/channels/private-channel/messages" && request.method === "POST") {
    if (mode === "send-expiry" && !expired) {
      expired = true;
      response.writeHead(401, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "sign_in_required" }));
      return;
    }
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
  const page = await browser.newPage({ hasTouch: mobile });
  const errors = [];
  page.on("pageerror", (error) => { errors.push(error.message); console.error(error.message); });
  await page.goto(`http://127.0.0.1:${server.address().port}/${mode === "connection" ? "?sign_in_error=newsroom_identity_mismatch" : ""}`);
  if (mobile && mode !== "mobile") {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.getByRole("button", { name: "Open private chat" }).click();
  }
  if (mode === "mobile") {
    const { verifyMobileChat } = await import("./verify-mobile-chat.mjs");
    await verifyMobileChat(page, `http://127.0.0.1:${server.address().port}`);
    assert.deepEqual(errors, []);
  } else {
  await page.getByText("Private conversation for this newsroom.").waitFor();
  const input = page.getByRole("textbox", { name: "Message input" });
  await input.fill("First private message");
  await input.press("Enter");
  if (mode === "send-expiry") {
    await page.getByRole("button", { name: "Retry", exact: true }).waitFor();
    assert.equal(await page.getByRole("textbox", { name: "Message input" }).count(), 0, "expired conversation is unmounted");
    assert.equal(await page.getByText("First private message", { exact: true }).count(), 0);
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await page.getByText("Private conversation for this newsroom.").waitFor();
    await page.getByRole("textbox", { name: "Message input" }).fill("First private message");
    await page.getByRole("textbox", { name: "Message input" }).press("Enter");
  }
  await page.getByText("First private message", { exact: true }).waitFor();
  if (mode === "poll-expiry") {
    await page.getByRole("button", { name: "Retry", exact: true }).waitFor();
    assert.equal(await page.getByText("First private message", { exact: true }).count(), 0, "a failed reauthorization removes the old transcript");
    assert.equal(await page.getByRole("textbox", { name: "Message input" }).count(), 0);
    assert.deepEqual(errors, []);
    console.log("PASS: polling expiry clears transcript and exposes identity recovery");
  } else {
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
  assert.equal(channelRequests.length, mode === "send-expiry" ? 2 : 1);
  assert.equal(sendRequests.length, mode === "send-expiry" ? 3 : 2);
  if (mode === "send-expiry") assert.notEqual(sendRequests[0].headers["idempotency-key"], sendRequests[1].headers["idempotency-key"], "identity recovery discards the old retry scope");
  for (const request of [...channelRequests, ...sendRequests]) {
    assert.equal(request.headers.cookie, "papyrus-session=synthetic-session", "the same-origin session cookie reaches the host route");
    assert.equal(request.headers.authorization, "Bearer synthetic-editor-a", "the client sends its existing newsroom identity for server verification");
    assert.equal(request.headers.origin, `http://127.0.0.1:${server.address().port}`);
  }
  for (const request of sendRequests) {
    const payload = JSON.parse(request.body);
    assert.deepEqual(Object.keys(payload), ["body"], "the browser sends no tenant, editor or bot identity");
    assert.ok(request.headers["idempotency-key"]);
  }
  if (mode === "identity-change") {
    await page.evaluate(() => window.testAuthEvent("signedOut"));
    await page.getByRole("button", { name: "Retry", exact: true }).waitFor();
    assert.equal(await page.getByText("Private runtime reply", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("textbox", { name: "Message input" }).count(), 0);
    await page.evaluate(() => { sessionStorage.setItem("test-editor", "synthetic-editor-b"); window.testAuthEvent("signedIn"); });
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await page.getByText("Second editor private history", { exact: true }).waitFor();
    assert.equal(await page.getByText("Private runtime reply", { exact: true }).count(), 0);
    await page.reload();
    await page.getByText("Second editor private history", { exact: true }).waitFor();
    assert.equal(await page.getByText("Private runtime reply", { exact: true }).count(), 0);
    const beforeRefresh = requests.filter(request => request.url.endsWith("/private-channel")).length;
    await page.evaluate(() => window.testAuthEvent("tokenRefresh"));
    await page.waitForTimeout(100);
    await page.getByText("Second editor private history", { exact: true }).waitFor();
    assert.equal(await page.getByText("Private runtime reply", { exact: true }).count(), 0);
    assert.equal(requests.filter(request => request.url.endsWith("/private-channel")).length, beforeRefresh + 1);
    assert.equal(sendCount, 2, "sign-in retry, token refresh and reload do not replay sends");
  }
  assert.deepEqual(errors, []);
  console.log("PASS: shared UI sends through the private host route once, preserves pending-reply sends, and renders the reply");
  }
  }
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
