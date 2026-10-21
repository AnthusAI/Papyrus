import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";

// Behaviour of the standard front end's page actions in a real browser. The page is the golden article of the flat
// fixture site (features_backend/fixtures/standard-site/flat/expected); the script is the shipped asset.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const golden = resolve(root, "features_backend/fixtures/standard-site/flat/expected");
const script = readFileSync(resolve(root, "src/papyrus_content/projection/standard/assets/papyrus-page-actions.js"), "utf8");
const css = readFileSync(resolve(root, "src/papyrus_content/projection/standard/assets/markus-components.css"), "utf8");
const markdown = readFileSync(resolve(golden, "orchids.md"), "utf8");
const AI_ITEMS =
  '<li><a class="markus-action-link" data-action="claude" href="https://claude.ai/new?q=x" target="_blank" rel="noopener noreferrer">Open in Claude</a></li>';
const html = readFileSync(resolve(golden, "orchids.html"), "utf8").replace(
  '</li></ul><span class="markus-actions-status"',
  `</li>${AI_ITEMS}</ul><span class="markus-actions-status"`,
);
assert.ok(html.includes("Open in Claude"), "the fixture page has a links list to extend");
const ORIGIN = "https://almanac.example.org";

let browser: Browser;
before(async () => {
  browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
});
after(async () => {
  await browser.close();
});

async function open(context: BrowserContext, options: { clipboard?: boolean } = {}): Promise<Page> {
  await context.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/orchids.html") return route.fulfill({ contentType: "text/html", body: html });
    if (path === "/orchids.md") return route.fulfill({ contentType: "text/markdown", body: markdown });
    if (path.startsWith("/_plugins/papyrus-page-actions")) return route.fulfill({ contentType: "text/javascript", body: script });
    if (path.includes("markus-components")) return route.fulfill({ contentType: "text/css", body: css });
    if (path.endsWith(".css")) return route.fulfill({ contentType: "text/css", body: "" });
    return route.fulfill({ status: 404, body: "" });
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    (window as unknown as { events: unknown[] }).events = [];
    (window as unknown as { gtag: (...a: unknown[]) => void }).gtag = (...args) => (window as unknown as { events: unknown[] }).events.push(args);
  });
  await page.goto(`${ORIGIN}/orchids.html`);
  return page;
}

test("copy puts the Markdown twin on the clipboard, confirms it, and reports the action", async () => {
  const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
  const page = await open(context);
  await page.getByRole("button", { name: "Copy Markdown" }).click();
  await page.getByRole("status").filter({ hasText: "Copied" }).waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), markdown);
  assert.ok(markdown.startsWith("# Orchids of the Marsh") && markdown.includes("Canonical: https://almanac.example.org/orchids.html"));
  const events = await page.evaluate(() => (window as unknown as { events: unknown[][] }).events);
  assert.deepEqual(events.find((entry) => entry[0] === "event")?.slice(1), ["page_action", { action: "copy" }]);
  await context.close();
});

test("when the Clipboard API is unavailable the copy falls back to selecting the text", async () => {
  const context = await browser.newContext();
  const page = await open(context);
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true }));
  await page.getByRole("button", { name: "Copy Markdown" }).click();
  // execCommand("copy") succeeds in a user gesture: the status confirms it and the helper textarea is removed again.
  // Where it does not, the textarea stays selected with the full text for a manual copy.
  await page.waitForFunction(() => {
    const status = document.querySelector(".markus-actions-status")?.textContent ?? "";
    return status === "Copied" || status.startsWith("Press") || document.querySelector(".markus-actions-fallback") !== null;
  });
  const area = page.locator(".markus-actions-fallback");
  if (await area.count()) assert.equal(await area.inputValue(), markdown);
  await context.close();
});

test("the menu button follows the ARIA menu pattern and is keyboard operable", async () => {
  const context = await browser.newContext();
  const page = await open(context);
  const button = page.getByRole("button", { name: "More page actions" });
  assert.equal(await button.getAttribute("aria-haspopup"), "menu");
  assert.equal(await button.getAttribute("aria-expanded"), "false");
  await button.focus();
  await page.keyboard.press("ArrowDown");
  assert.equal(await button.getAttribute("aria-expanded"), "true");
  const items = page.getByRole("menuitem");
  assert.deepEqual(await items.allTextContents(), ["View as Markdown", "Open in Claude"]);
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "View as Markdown");
  await page.keyboard.press("ArrowDown");
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Open in Claude");
  await page.keyboard.press("ArrowDown");
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "View as Markdown");
  await page.keyboard.press("End");
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Open in Claude");
  await page.keyboard.press("Escape");
  assert.equal(await button.getAttribute("aria-expanded"), "false");
  assert.equal(await page.evaluate(() => document.activeElement?.className), "markus-actions-menu-button");
  await context.close();
});

test("the layout does not move when the script runs", async () => {
  const context = await browser.newContext();
  const page = await open(context);
  const height = await page.locator("[data-papyrus-page-actions]").evaluate((element) => element.getBoundingClientRect().height);
  assert.ok(height >= 36, `reserved height ${height}`);
  await context.close();
});

test("without JavaScript the Markdown link works and the copy button is not offered", async () => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await open(context);
  assert.ok(await page.getByRole("link", { name: "View as Markdown" }).isVisible());
  assert.equal(await page.getByRole("button", { name: "Copy Markdown" }).count(), 0);   // visibility:hidden keeps it out of the accessibility tree
  await context.close();
});
