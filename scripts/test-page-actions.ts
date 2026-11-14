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

async function open(context: BrowserContext, options: { twin?: string } = {}): Promise<Page> {
  await context.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/orchids.html") return route.fulfill({ contentType: "text/html", body: html });
    if (path === "/orchids.md") return route.fulfill({ contentType: "text/markdown", body: options.twin ?? markdown });
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

test("copy gives a page written as page blocks exactly as the twin, directives and all, with no second title", async () => {
  const twin = [
    "> How decisions get made.",
    "",
    '::band{id="top" tone="card"}',
    "# Decision models",
    "",
    '::image{src="images/wide.png" alt="A wide chart" layout="full" caption="Wide"}',
    "",
    '::column{panel="card"}',
    '::island{name="Chart" kind="bar" summary="A bar chart: 2B leads."}',
    "",
  ].join("\n");
  const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
  const page = await open(context, { twin });
  await page.getByRole("button", { name: "Copy Markdown" }).click();
  await page.getByRole("status").filter({ hasText: "Copied" }).waitFor();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  assert.ok(copied.endsWith(twin), "the twin is copied whole");
  assert.equal(copied.split("# ").length - 1, 1, "the title is not added when the page carries its own H1 after ::band");
  assert.ok(copied.includes('::image{src="images/wide.png" alt="A wide chart" layout="full" caption="Wide"}'));
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

// The icon display (pageActions.display "icons"): the group as the projector writes it for the flat fixture with
// actions view, copy, x, reddit and share. procedures/newsroom/tests/test_standard_frontend.py pins this markup.
const ICON = (name: string) => `<svg class="markus-action-icon" aria-hidden="true" focusable="false" data-icon="${name}"></svg>`;
const ICON_GROUP =
  '<div class="markus-page-actions markus-page-actions-header markus-page-actions-icons" role="group" aria-label="Page actions" data-papyrus-page-actions ' +
  'data-markdown="/orchids.md" data-title="Orchids of the Marsh" data-canonical="https://almanac.example.org/orchids.html" data-share>' +
  '<ul class="markus-actions-icons" aria-label="Read and post this page">' +
  `<li><a class="markus-action-link markus-icon-action" data-action="view" href="/orchids.md" aria-label="View as Markdown" title="View as Markdown">${ICON("file-text")}</a></li>` +
  `<li><a class="markus-action-link markus-icon-action" data-action="x" href="https://x.com/intent/post?text=Orchids%20of%20the%20Marsh&amp;url=https%3A%2F%2Falmanac.example.org%2Forchids.html" target="_blank" rel="noopener noreferrer" aria-label="Post on X" title="Post on X">${ICON("x")}</a></li>` +
  `<li><a class="markus-action-link markus-icon-action" data-action="reddit" href="https://www.reddit.com/submit?url=https%3A%2F%2Falmanac.example.org%2Forchids.html&amp;title=Orchids%20of%20the%20Marsh" target="_blank" rel="noopener noreferrer" aria-label="Post on Reddit" title="Post on Reddit">${ICON("reddit")}</a></li>` +
  "</ul>" +
  `<button type="button" class="markus-copy-md markus-icon-action" data-action="copy" aria-label="Copy Markdown" title="Copy Markdown">${ICON("copy")}</button>` +
  '<span class="markus-actions-status" role="status" aria-live="polite"></span></div>';
const iconHtml = html.replace(/<div class="markus-page-actions.*?<\/span><\/div>/s, ICON_GROUP);
assert.ok(iconHtml.includes("markus-page-actions-icons"), "the fixture page has a group to replace");

async function openIcons(context: BrowserContext, options: { share?: boolean } = {}): Promise<Page> {
  await context.route("**/*", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/orchids.html") return route.fulfill({ contentType: "text/html", body: iconHtml });
    if (path === "/orchids.md") return route.fulfill({ contentType: "text/markdown", body: markdown });
    if (path.startsWith("/_plugins/papyrus-page-actions")) return route.fulfill({ contentType: "text/javascript", body: script });
    if (path.includes("markus-components")) return route.fulfill({ contentType: "text/css", body: css });
    if (path.endsWith(".css")) return route.fulfill({ contentType: "text/css", body: "" });
    return route.fulfill({ status: 404, body: "" });
  });
  const page = await context.newPage();
  await page.addInitScript((share) => {
    (window as unknown as { events: unknown[] }).events = [];
    (window as unknown as { gtag: (...a: unknown[]) => void }).gtag = (...args) => (window as unknown as { events: unknown[] }).events.push(args);
    (window as unknown as { shared: unknown[] }).shared = [];
    if (share) (navigator as unknown as { share: (data: unknown) => Promise<void> }).share = async (data) => void (window as unknown as { shared: unknown[] }).shared.push(data);
  }, options.share ?? false);
  await page.goto(`${ORIGIN}/orchids.html`);
  return page;
}

const reported = (page: Page) => page.evaluate(() => (window as unknown as { events: unknown[][] }).events.map((entry) => entry.slice(1)));

test("the icon display adds a Share menu button that follows the ARIA menu pattern", async () => {
  const context = await browser.newContext();
  const page = await openIcons(context);
  const button = page.getByRole("button", { name: "Share", exact: true });
  assert.equal(await button.getAttribute("aria-haspopup"), "menu");
  assert.equal(await button.getAttribute("aria-expanded"), "false");
  assert.equal(await page.getByRole("menu", { name: "Share" }).isVisible(), false, "the popup starts closed");
  await button.focus();
  await page.keyboard.press("ArrowDown");
  assert.equal(await button.getAttribute("aria-expanded"), "true");
  assert.deepEqual(await page.getByRole("menuitem").allTextContents(), ["Share the web page", "Share the Markdown"]);
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Share the web page");
  await page.keyboard.press("Escape");
  assert.equal(await button.getAttribute("aria-expanded"), "false");
  assert.equal(await page.getByRole("menu", { name: "Share" }).isVisible(), false);
  await context.close();
});

test("sharing hands the device share sheet only the title and the address, and reports through gtag", async () => {
  const context = await browser.newContext();
  const page = await openIcons(context, { share: true });
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await page.getByRole("menuitem", { name: "Share the web page" }).click();
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await page.getByRole("menuitem", { name: "Share the Markdown" }).click();
  const shared = await page.evaluate(() => (window as unknown as { shared: unknown[] }).shared);
  assert.deepEqual(shared, [
    { title: "Orchids of the Marsh", url: "https://almanac.example.org/orchids.html" },
    { title: "Orchids of the Marsh", url: "https://almanac.example.org/orchids.md" },
  ]);
  assert.deepEqual(await reported(page), [["page_action", { action: "share_page" }], ["page_action", { action: "share_markdown" }]]);
  await context.close();
});

test("without a share sheet the address is copied and confirmed in the live region", async () => {
  const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
  const page = await openIcons(context);
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await page.getByRole("menuitem", { name: "Share the Markdown" }).click();
  await page.getByRole("status").filter({ hasText: "Link copied" }).waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), "https://almanac.example.org/orchids.md");
  await context.close();
});

test("the post links report their action, and they are plain links that carry only the title and address", async () => {
  const context = await browser.newContext();
  const page = await openIcons(context);
  await page.evaluate(() => document.addEventListener("click", (event) => event.preventDefault(), true)); // stay on the page; the link's own handler still runs
  await page.getByRole("link", { name: "Post on X" }).dispatchEvent("click");
  assert.deepEqual(await reported(page), [["page_action", { action: "x" }]]);
  const href = (await page.getByRole("link", { name: "Post on Reddit" }).getAttribute("href")) ?? "";
  assert.ok(href.startsWith("https://www.reddit.com/submit?url=") && !href.includes("Marsh%20orchids"));
  await context.close();
});

test("without JavaScript the icon links work and there is no Share button", async () => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await openIcons(context);
  for (const name of ["View as Markdown", "Post on X", "Post on Reddit"]) assert.ok(await page.getByRole("link", { name }).isVisible(), name);
  assert.equal(await page.getByRole("button", { name: "Share", exact: true }).count(), 0);
  await context.close();
});

test("at phone width the actions fit, each target is at least 44 px, and the popup stays on screen", async () => {
  const context = await browser.newContext({ viewport: { width: 375, height: 700 } });
  const page = await openIcons(context);
  await page.getByRole("button", { name: "Share", exact: true }).click();
  const box = await page.getByRole("menu", { name: "Share" }).boundingBox();
  assert.ok(box && box.x >= 0 && box.x + box.width <= 375, `popup ${JSON.stringify(box)}`);
  for (const control of await page.locator(".markus-icon-action, .markus-actions-menu-button").all()) {
    const target = await control.boundingBox();
    assert.ok(target && target.width >= 44 && target.height >= 44, `target ${JSON.stringify(target)}`);
  }
  assert.ok((await page.evaluate(() => document.documentElement.scrollWidth)) <= 375, "no horizontal scroll");
  await context.close();
});
