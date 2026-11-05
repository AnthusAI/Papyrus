import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { chromium, type Browser, type Page } from "playwright";

// Paged Reference lists in a real browser: the first page without a script and the link to the next static page; with a script the link becomes a button, more cards
// load as the reader scrolls (a few at a time), then the button asks, a keyboard press carries focus to the first new card, a failed load can be tried again, nothing
// above the new cards moves, and a phone-width page never scrolls sideways. The site is the standard projector's own output for a synthetic snapshot:
//   python -m procedures.newsroom.tests.build_reference_list_site <directory>      (REFERENCE_LIST_SITE=<directory> names it)
//   REFERENCE_LIST_SCREENSHOTS=<dir> also saves the screenshots (top of the list, mid-load, the Load more button) at 375 and 1440 px.
const site = process.env.REFERENCE_LIST_SITE ? resolve(process.env.REFERENCE_LIST_SITE) : "";
const screenshots = process.env.REFERENCE_LIST_SCREENSHOTS;
const TYPES: Record<string, string> = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".md": "text/markdown" };

type Harness = { origin: string; server: Server; delay: { json: number }; fail: { json: boolean }; requests: string[] };

function serve(directory: string): Promise<Harness> {
  const harness = { delay: { json: 0 }, fail: { json: false }, requests: [] as string[] } as Harness;
  const server = createServer((request, response) => {
    const path = decodeURIComponent((request.url ?? "/").split("?")[0]);
    harness.requests.push(path);
    const respond = () => {
      let file = join(directory, path);
      if (path.endsWith("/")) file = join(file, "index.html");
      if (path.endsWith(".json") && harness.fail.json) {
        response.writeHead(500).end("broken");
        return;
      }
      if (!existsSync(file) || !statSync(file).isFile()) {
        response.writeHead(404, { "content-type": "text/plain" }).end("not found");
        return;
      }
      response.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" }).end(readFileSync(file));
    };
    if (path.endsWith(".json") && harness.delay.json > 0) setTimeout(respond, harness.delay.json);
    else respond();
  });
  return new Promise((done) => server.listen(0, "127.0.0.1", () => {
    harness.server = server;
    harness.origin = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
    done(harness);
  }));
}

let browser: Browser;
let harness: Harness;
before(async () => {
  assert.ok(site && existsSync(site), "REFERENCE_LIST_SITE must name a directory built by procedures.newsroom.tests.build_reference_list_site");
  browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  harness = await serve(site);
});
after(async () => {
  await browser.close();
  harness.server.close();
});

const ACCEPTED = 130;
const FIRST = 6;

async function open(width: number, javaScriptEnabled = true, delay = 0) {
  harness.delay.json = delay;
  const context = await browser.newContext({ viewport: { width, height: width < 600 ? 812 : 900 }, javaScriptEnabled });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !/favicon|Failed to load resource/.test(message.text())) problems.push(message.text());
  });
  await page.goto(`${harness.origin}/wire/`);
  return { context, page, problems };
}

const accepted = (page: Page) => page.locator('section[data-select="recent"]');
const cards = (page: Page) => accepted(page).locator("[data-reference-grid] > li");
const shot = async (page: Page, name: string, width: number) => {
  if (!screenshots) return;
  mkdirSync(screenshots, { recursive: true });
  await page.screenshot({ path: join(screenshots, `${name}-${width}.png`) });
};

/** Scroll the end of the accepted list into view until the script stops loading by itself and asks for the button. */
async function scrollUntilAsked(page: Page) {
  const status = accepted(page).locator("[data-reference-status]");
  for (let turn = 0; turn < 40; turn += 1) {
    if ((await status.textContent())?.includes("Press Load more")) return;
    await accepted(page).locator("[data-reference-more]").scrollIntoViewIfNeeded();
    await page.waitForTimeout(150);
  }
  assert.fail("the list never asked for the button");
}

for (const width of [375, 1440]) {
  test(`${width}px: the first page, then more as the reader scrolls, then the button, then the end`, async () => {
    const { context, page, problems } = await open(width, true, 900);
    try {
      assert.equal(await cards(page).count(), FIRST, "the first page is in the HTML");
      assert.equal(await accepted(page).locator("a.home-page-load-more").count(), 0, "the script turned the link into a button");
      const button = accepted(page).locator("button.home-page-load-more");
      assert.equal(await button.count(), 1);
      assert.equal(await accepted(page).locator("[data-reference-status]").getAttribute("aria-live"), "polite");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "no sideways scroll at the top");
      await shot(page, "top-of-list", width);

      // The end of a short first page is already near the viewport, so the next data file is fetched at once (slowly here). Nothing above the new cards moves.
      const tops = () => cards(page).evaluateAll((items) => items.slice(0, 6).map((item) => Math.round(item.getBoundingClientRect().top + window.scrollY)));
      const before = await tops();
      await accepted(page).locator("[data-reference-more]").scrollIntoViewIfNeeded();   // on a phone the end of the first page is still far below
      await accepted(page).locator("button.home-page-load-more", { hasText: "Loading" }).waitFor();
      assert.equal(await button.getAttribute("aria-disabled"), "true");
      assert.equal(await accepted(page).getAttribute("aria-busy"), "true");
      await shot(page, "mid-load", width);
      await page.waitForFunction((count) => document.querySelectorAll('section[data-select="recent"] [data-reference-grid] > li').length > count, FIRST);
      harness.delay.json = 0;
      assert.deepEqual(await tops(), before, "the cards that were already there did not move");
      assert.match((await accepted(page).locator("[data-reference-status]").textContent()) ?? "", /Loaded \d+ more References?\. Showing \d+\./);

      // A few files load by themselves; then the footer is reachable and the button asks.
      await scrollUntilAsked(page);
      const shown = await cards(page).count();
      assert.ok(shown > FIRST && shown < ACCEPTED, `some but not all are loaded (${shown})`);
      await button.scrollIntoViewIfNeeded();
      assert.equal(await button.innerText(), "Load more");
      await shot(page, "load-more-button", width);

      // A keyboard press loads the next file and carries focus to its first card.
      await button.focus();
      await page.keyboard.press("Enter");
      await page.waitForFunction((count) => document.querySelectorAll('section[data-select="recent"] [data-reference-grid] > li').length > count, shown);
      assert.equal(await page.evaluate(() => document.activeElement?.closest("li")?.hasAttribute("data-key")), true, "focus is on a card");
      assert.equal(await page.evaluate(() => document.activeElement?.closest("li") === document.querySelector("[data-reference-new]")), true, "focus is on the first new card");

      // Keep going to the end: every Reference once, and the control and the sentinel are gone.
      for (let turn = 0; turn < 40 && (await cards(page).count()) < ACCEPTED; turn += 1) {
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        const more = accepted(page).locator("button.home-page-load-more");
        if ((await more.count()) && (await more.isVisible())) await more.click();
        await page.waitForTimeout(150);
      }
      assert.equal(await cards(page).count(), ACCEPTED);
      const keys = await cards(page).evaluateAll((items) => items.map((item) => item.getAttribute("data-key")));
      assert.equal(new Set(keys).size, ACCEPTED, "no Reference twice");
      assert.match((await accepted(page).locator("[data-reference-status]").textContent()) ?? "", /All 130 are shown\./);
      assert.equal(await accepted(page).locator("[data-reference-more]").isHidden(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "no sideways scroll after loading");
      assert.deepEqual(problems, []);
    } finally {
      await context.close();
    }
  });
}

test("without a script the link leads to a real page of cards, and Next goes on", async () => {
  const { context, page } = await open(375, false);
  try {
    assert.equal(await cards(page).count(), FIRST);
    await accepted(page).getByRole("link", { name: "Load more" }).click();
    await page.waitForURL(/\/reference-lists\/wire\/recent\/c[0-9a-f]+\/$/);
    assert.ok((await page.locator("li[data-key]").count()) >= 3);
    await page.getByRole("link", { name: "Next" }).click();
    await page.waitForURL(/\/reference-lists\/wire\/recent\/c[0-9a-f]+\/$/);
    await page.getByRole("link", { name: "Previous" }).waitFor();
  } finally {
    await context.close();
  }
});

test("a failed load says so, keeps the button, and the next press works", async () => {
  const { context, page } = await open(375);
  try {
    harness.fail.json = true;
    const button = accepted(page).locator("button.home-page-load-more");
    await button.scrollIntoViewIfNeeded();
    await button.click();
    await accepted(page).locator("button.home-page-load-more", { hasText: "Try again" }).waitFor();
    assert.match((await accepted(page).locator("[data-reference-status]").textContent()) ?? "", /Could not load more/);
    assert.equal(await cards(page).count(), FIRST, "nothing was added");
    harness.fail.json = false;
    await button.click();
    await page.waitForFunction((count) => document.querySelectorAll('section[data-select="recent"] [data-reference-grid] > li').length > count, FIRST);
  } finally {
    harness.fail.json = false;
    await context.close();
  }
});
