import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { chromium, type Browser, type Page } from "playwright";

// Behaviour of the standard front end's Mermaid support in a real browser. The page is shaped like a projected article;
// the loader and the library are the shipped assets, served from the page's own origin.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const assets = resolve(root, "src/papyrus_content/projection/standard/assets");
const loader = readFileSync(resolve(assets, "papyrus-mermaid.js"), "utf8");
const library = readFileSync(resolve(assets, "mermaid.min.js"), "utf8");
const ORIGIN = "https://almanac.example.org";
const LIBRARY_PATH = "/_plugins/mermaid-11.17.2.min.js";

const FLOW = 'flowchart TD\n  A["Start"] --> B{"Choose"}\n  B -->|yes| C["Done"]\n  B -.->|no| D["Retry"]';
const HOSTILE = 'flowchart TD\n  A["<img src=x onerror=window.pwned=1>"] --> B["<script>window.pwned=2</script>"]';
const BROKEN = "flowchart TD\n  A -->";

const escape = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const block = (source: string) => `<pre><code class="language-mermaid">${escape(source)}\n</code></pre>`;
function article(sources: string[], withLoader = true): string {
  const tag = `<script src="/_plugins/papyrus-mermaid-v1.js?v=t" data-library="${LIBRARY_PATH}"></script>`;
  return `<!doctype html><html><head><title>t</title></head><body style="--papyrus-ink:#202020;--papyrus-bg:#fafafa"><main><article><p>Hi</p>${sources.map(block).join("")}</article></main>${withLoader ? tag : ""}</body></html>`;
}

let browser: Browser;
before(async () => {
  browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
});
after(async () => {
  await browser.close();
});

async function open(sources: string[], options: { javaScript?: boolean; colorScheme?: "light" | "dark"; path?: string } = {}): Promise<{ page: Page; requested: string[] }> {
  const context = await browser.newContext({ javaScriptEnabled: options.javaScript ?? true, colorScheme: options.colorScheme ?? "light" });
  const requested: string[] = [];
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    requested.push(url.origin + url.pathname);
    if (url.pathname === "/a.html") return route.fulfill({ contentType: "text/html", body: article(sources) });
    if (url.pathname === "/none.html") return route.fulfill({ contentType: "text/html", body: article([], false) });
    if (url.pathname.startsWith("/_plugins/papyrus-mermaid")) return route.fulfill({ contentType: "text/javascript", body: loader });
    if (url.pathname === LIBRARY_PATH) return route.fulfill({ contentType: "text/javascript", body: library });
    return route.fulfill({ status: 404, body: "" });
  });
  const page = await context.newPage();
  await page.goto(`${ORIGIN}${options.path ?? "/a.html"}`);
  return { page, requested };
}

test("a Mermaid block becomes a diagram with a text alternative and its source kept", async () => {
  const { page, requested } = await open([FLOW]);
  await page.locator(".papyrus-diagram-canvas svg").waitFor();
  assert.equal(await page.locator(".papyrus-diagram-canvas").getAttribute("role"), "img");
  assert.match((await page.locator(".papyrus-diagram-canvas").getAttribute("aria-label")) ?? "", /^Diagram \(flowchart\)/);
  assert.ok((await page.locator(".papyrus-diagram-canvas svg title").count()) >= 1, "the SVG carries a title");
  assert.ok((await page.locator(".papyrus-diagram-canvas").innerText()).includes("Retry"));
  assert.ok((await page.locator(".papyrus-diagram-source pre").textContent() ?? "").includes("B -.->|no| D"), "the source stays in the page");
  assert.ok(requested.every((entry) => entry.startsWith(ORIGIN)), `nothing leaves the origin: ${requested.join(", ")}`);
});

test("a page without a diagram never requests the library", async () => {
  const { page, requested } = await open([], { path: "/none.html" });
  await page.waitForTimeout(300);
  assert.equal(await page.locator("script[src]").count(), 0, "no script at all");
  assert.ok(!requested.some((entry) => entry.includes("mermaid")), requested.join(", "));
});

test("with JavaScript off the source is a readable pre", async () => {
  const { page } = await open([FLOW], { javaScript: false });
  assert.equal(await page.locator(".papyrus-diagram").count(), 0);
  assert.ok((await page.locator("pre code.language-mermaid").innerText()).includes("A[\"Start\"] --> B"));
});

test("HTML in diagram text is shown as text and never runs", async () => {
  const { page } = await open([HOSTILE]);
  await page.locator(".papyrus-diagram-canvas svg").waitFor();
  await page.waitForTimeout(300);
  assert.equal(await page.evaluate(() => (window as unknown as { pwned?: number }).pwned), undefined);
  assert.equal(await page.locator(".papyrus-diagram-canvas img, .papyrus-diagram-canvas script").count(), 0);
  assert.ok((await page.locator(".papyrus-diagram-canvas").innerText()).includes("<img"), "the markup is displayed as text");
});

test("a diagram that cannot be drawn leaves its source and says so", async () => {
  const { page } = await open([BROKEN, FLOW]);
  await page.locator(".papyrus-diagram-canvas svg").waitFor();
  assert.equal(await page.locator(".papyrus-diagram").count(), 1, "the good diagram still draws");
  assert.match(await page.getByRole("status").innerText(), /could not be drawn/);
  assert.ok(((await page.locator("pre code.language-mermaid").first().textContent()) ?? "").includes("A -->"));
  assert.equal(await page.locator("body > [id^=dpapyrus-mermaid]").count(), 0, "no error artefact is left in the page");
});

test("the diagram follows the site's colour tokens and uses no colour coding", async () => {
  const { page } = await open([FLOW]);
  await page.locator(".papyrus-diagram-canvas svg").waitFor();
  const colours = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".papyrus-diagram-canvas svg path.flowchart-link, .papyrus-diagram-canvas svg .node rect, .papyrus-diagram-canvas svg .node polygon")).map((element) => {
      const style = getComputedStyle(element);
      return [style.stroke, style.fill].join("|");
    }),
  );
  assert.ok(colours.length > 0);
  assert.ok(colours.some((entry) => entry.includes("rgb(32, 32, 32)")), `the token ink is used: ${colours.join(" ; ")}`);
});
