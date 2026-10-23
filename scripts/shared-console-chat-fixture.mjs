import assert from "node:assert/strict";
import { createServer } from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
const mode = process.argv[2];
assert.ok(["send", "reference", "pending-reply", "keyboard-send", "disabled-send"].includes(mode), "Expected a supported shared chat fixture mode");
const result = await build({ entryPoints: [fileURLToPath(new URL("./fixtures/shared-console-chat.tsx", import.meta.url))], bundle: true, write: false, outfile: "app.js", platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"development"' } });
const server = createServer((request, response) => {
  if (request.url === "/app.js") { response.setHeader("Content-Type", "text/javascript"); response.end(result.outputFiles.find((file) => file.path.endsWith(".js")).contents); }
  else if (request.url === "/app.css") { response.setHeader("Content-Type", "text/css"); response.end(result.outputFiles.find((file) => file.path.endsWith(".css")).contents); }
  else response.end('<!doctype html><html><head><link rel="stylesheet" href="/app.css"><style>html,body,#root,main{height:100%;margin:0;display:flex;flex-direction:column}</style></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined, headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/?mode=${mode}`);
  await page.getByText("Ready", { exact: true }).waitFor();
  assert.equal(await page.locator('a[href^="javascript:"]').count(), 0);
  if (mode === "send" || mode === "pending-reply" || mode === "keyboard-send") {
    await page.getByRole("textbox", { name: "Message input" }).fill("Run the editorial check");
    if (mode === "keyboard-send") {
      await page.getByRole("textbox", { name: "Message input" }).press("Enter");
    } else {
      if (mode === "pending-reply") assert.equal(await page.getByRole("button", { name: "Send message", exact: true }).isDisabled(), false);
      await page.getByRole("button", { name: "Send message", exact: true }).click();
    }
    await page.getByText("Papyrus received the editorial request", { exact: true }).waitFor();
    assert.equal(await page.getByLabel("Papyrus sends").textContent(), "1");
    console.log(mode === "pending-reply" ? "Papyrus pending reply send passed" : mode === "keyboard-send" ? "Papyrus keyboard send passed" : "Papyrus shared chat send passed");
    if (mode === "send") console.log("Safe shared markdown passed");
  } else if (mode === "disabled-send") {
    await page.getByRole("textbox", { name: "Message input" }).fill("This must not be sent");
    await page.getByRole("textbox", { name: "Message input" }).press("Enter");
    assert.equal(await page.getByLabel("Papyrus sends").textContent(), "0");
    console.log("Papyrus disabled send passed");
  } else {
    await page.getByRole("button", { name: "Open reference", exact: true }).click();
    assert.equal(await page.getByLabel("Papyrus reference actions").textContent(), "1");
    console.log("Papyrus reference action passed");
  }
  assert.deepEqual(errors, []);
} finally { await browser?.close(); await new Promise((resolve) => server.close(resolve)); }
