/**
 * The Newsroom search results page (PPY-5beaab): word hits first, labelled "Title match", then the Related ones; each result says its kind and its status in
 * words; status options are buttons. Fixture-only: an isolated browser, the real Tailwind build, a stand-in for the `searchReferences` query. Nothing leaves the page.
 *   tsx scripts/test-newsroom-search-results.ts
 * SEARCH_SHOTS_DIR=<dir> also writes screenshots of the results page (375 and 1440 wide, light and dark).
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import {
  SEARCH_KIND_LABEL,
  searchKindExplanation,
  searchResultKind,
  searchStatusWord,
  showForStatus,
  splitSearchResults,
  statusFromLocation,
  type ReferenceSearchMatch,
} from "../lib/reference-search";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://newsroom-search.test";
const shots = process.env.SEARCH_SHOTS_DIR;
let bundle: Promise<string> | undefined;
let tailwindCss: Promise<string> | undefined;

function compiledTailwind(): Promise<string> {
  tailwindCss ??= (async () => {
    const file = `${root}app/tailwind.css`;
    const { default: postcss } = await import("postcss");
    const { default: tailwind } = await import("@tailwindcss/postcss");
    return (await postcss([tailwind() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
  })();
  return tailwindCss;
}

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, logLevel: "silent",
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "newsroom-search-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NewsroomSearchResults } from "./components/newsroom-search-results";

const params = new URLSearchParams(location.search);
const NOW = Date.parse("2026-11-05T12:00:00Z");
const day = (days) => new Date(NOW - days * 86400000).toISOString();
const make = (id, title, fields = {}) => ({ id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id,
  title, sourceUri: "https://" + (fields.host ?? "example.org") + "/" + id, curationStatus: "pending", feedArrivalAt: day(fields.age ?? 2), createdAt: day(fields.age ?? 2), ...fields });
const TITLE_HITS = [
  { reference: make("sound-leak", "I discovered a sound that leaks your exact location", { host: "youtube.com", age: 1 }), matchedBy: ["keyword"], matchedFields: ["title"] },
  { reference: make("sound-design", "Sound design for open-world games", { host: "gamedev.example", age: 9, curationStatus: "accepted" }), matchedBy: ["keyword", "meaning"], matchedFields: ["title"] },
  { reference: make("by-author", "Notes from the field recorder", { host: "field.example", age: 30, curationStatus: "rejected", authors: ["Ada Sound"] }), matchedBy: ["keyword"], matchedFields: ["authors"] },
];
const RELATED = [
  { reference: make("quiet-channels", "Quiet audio side channels reveal where you are, researchers find in a new long study of phones", { host: "arxiv.example", age: 4, curationStatus: "accepted" }), matchedBy: ["meaning"], matchedFields: [] },
  { reference: make("acoustic", "Acoustic fingerprints of phone speakers", { host: "security.example", age: 12, curationStatus: "rejected" }), matchedBy: ["meaning"], matchedFields: [] },
  { reference: make("ultrasonic", "Ultrasonic tracking beacons in shopping apps", { host: "news.example", age: 40 }), matchedBy: ["meaning"], matchedFields: [] },
];
const ALL = [...TITLE_HITS, ...RELATED];
const wanted = (show) => (match) => show === "all" || (show === "unrated" && match.reference.curationStatus === "pending") || match.reference.curationStatus === show;
window.calls = [];
const LANES = { keyword: { status: "ok" }, meaning: { status: "ok" } };
const search = async (input) => {
  window.calls.push({ query: input.query, show: input.show, cursor: input.cursor });
  await new Promise((resolve) => setTimeout(resolve, params.has("slow") ? 400 : 20));
  if (params.has("fail")) throw new Error("The search could not be reached.");
  if (params.has("empty") || input.query === "nothing") return { items: [], nextCursor: null, lanes: LANES };
  const items = ALL.filter(wanted(input.show));
  if (params.has("paged") && !input.cursor) return { items: items.slice(0, 3), nextCursor: "next", lanes: LANES };
  if (params.has("paged")) return { items: items.slice(3), nextCursor: null, lanes: LANES };
  return { items, nextCursor: null, lanes: params.has("words-only") ? { keyword: { status: "ok" }, meaning: { status: "failed", message: "x" } } : LANES };
};
createRoot(document.getElementById("root")).render(
  <NewsroomSearchResults hrefFor={(id) => "/newsroom/references/" + id} initialQuery={params.get("q") ?? "sound"} initialStatus={params.get("status") ?? "any"} now={NOW} search={search} syncAddress={false} />
);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const LIGHT = "--background:#f4f1ea;--foreground:#1c1c1c;--muted-foreground:#5f5b52;--card:#fbf9f4;--primary:#46560f;--primary-foreground:#fff;--ring:#46560f;--feed-card:#fbf9f4;--feed-control:#e8e3d8;--feed-footer:#f0ece2";
const DARK = "--background:#14130f;--foreground:#ece8dc;--muted-foreground:#a8a498;--card:#1d1c17;--primary:#c6f432;--primary-foreground:#1c1c1c;--ring:#c6f432;--feed-card:#1d1c17;--feed-control:#2d2b23;--feed-footer:#24231d";
const fixtureCss = `body{margin:0;font:16px/1.5 system-ui,sans-serif;background:var(--background);color:var(--foreground)}button,input{font:inherit}:root{${LIGHT}}html.dark{${DARK}}`;

type Scheme = "light" | "dark";

async function setup(options = "", width = 1440, scheme: Scheme = "light", height = 900) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme, deviceScaleFactor: width < 600 ? 2 : 1 });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript; charset=utf-8", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html class="${scheme === "dark" ? "dark" : ""}"><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="px-4 py-3"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom/search${options}`);
  return { browser, page, errors };
}

async function run(options: string, widths: number[], body: (page: Page, width: number) => Promise<void>) {
  for (const width of widths) {
    const { browser, page, errors } = await setup(options, width);
    try {
      await body(page, width);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  }
}

const calls = (page: Page) => page.evaluate(() => (window as unknown as { calls: Array<{ query: string; show: string; cursor: string | null }> }).calls);
const results = (page: Page) => page.locator("[data-search-result]");
const ids = (page: Page) => results(page).evaluateAll((elements) => elements.map((element) => element.getAttribute("data-search-result")));

const match = (matchedBy: string[], matchedFields: string[], curationStatus = "pending"): ReferenceSearchMatch => ({ reference: { curationStatus } as never, matchedBy: matchedBy as never, matchedFields });

const scenarios: Record<string, () => Promise<void>> = {
  /** The words, with no browser. */
  async unit() {
    assert.equal(searchResultKind(match(["keyword"], ["title"])), "title");
    assert.equal(searchResultKind(match(["keyword", "meaning"], ["title", "authors"])), "title");
    assert.equal(searchResultKind(match(["keyword"], ["authors"])), "word");
    assert.equal(searchResultKind(match(["meaning"], [])), "related");
    assert.deepEqual(["title", "word", "related"].map((kind) => SEARCH_KIND_LABEL[kind as never]), ["Title match", "Word match", "Related"]);
    assert.match(searchKindExplanation(match(["keyword"], ["title"])), /Your words are in the title\./);
    assert.match(searchKindExplanation(match(["meaning"], [])), /Close in meaning/);
    assert.deepEqual(["pending", "accepted", "rejected", undefined].map((status) => searchStatusWord({ curationStatus: status } as never)), ["Pending", "Accepted", "Rejected", "Pending"]);
    assert.deepEqual(["any", "pending", "accepted", "rejected"].map((status) => showForStatus(status as never)), ["all", "unrated", "accepted", "rejected"]);
    assert.equal(statusFromLocation("q=x&status=rejected"), "rejected");
    assert.equal(statusFromLocation("status=bogus"), "any");
    const split = splitSearchResults([match(["meaning"], []), match(["keyword"], ["title"]), match(["keyword", "meaning"], ["authors"])]);
    assert.equal(split.wordHits.length, 2);
    assert.equal(split.related.length, 1);
  },

  /** Searching goes straight to results: no second ask, the word hits first, the related after, each saying what it is in words. */
  async results() {
    await run("", [375, 1440], async (page, width) => {
      await results(page).first().waitFor();
      assert.deepEqual(await ids(page), ["sound-leak", "sound-design", "by-author", "quiet-channels", "acoustic", "ultrasonic"]);
      assert.deepEqual(await calls(page), [{ query: "sound", show: "all", cursor: null }], "one request, with no second search needed");
      const first = results(page).first();
      assert.match(await first.locator("[data-search-kind-label]").innerText(), /Title match/);
      assert.match(await first.locator("[data-search-status-label]").innerText(), /Pending/);
      assert.match(await first.locator("[data-search-why]").innerText(), /Your words are in the title/);
      assert.match(await results(page).nth(2).locator("[data-search-kind-label]").innerText(), /Word match/);
      const kinds = await page.locator("[data-search-kind-label]").allInnerTexts();
      assert.deepEqual(kinds.map((text) => text.trim()), ["Title match", "Title match", "Word match", "Related", "Related", "Related"]);
      const statuses = await page.locator("[data-search-status-label]").allInnerTexts();
      assert.deepEqual(statuses.map((text) => text.trim()), ["Pending", "Accepted", "Rejected", "Accepted", "Rejected", "Pending"], "pending, accepted and rejected are said in words");
      assert.equal(await page.locator("[data-search-group]").count(), 2);
      assert.equal(await page.locator("select").count(), 0, "buttons, never a dropdown");
      assert.equal(await page.locator("[data-search-status]").count(), 4);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `no sideways scroll at ${width}`);
      // Every kind and status carries an icon beside its words, and nothing is a bordered box.
      assert.equal(await page.locator("[data-search-kind-label] svg").count(), 6);
      const borders = await page.evaluate(() => [...document.querySelectorAll("[data-search-result], [data-search-status], [data-search-input], [data-search-submit]")].map((element) => getComputedStyle(element).borderTopWidth));
      assert.ok(borders.every((value) => value === "0px"), `no borders: ${borders.join(",")}`);
      const hit = await results(page).first().boundingBox();
      assert.ok(hit && hit.x >= 0 && hit.x + hit.width <= width, "the card fits the screen");
    });
  },

  /** The status buttons narrow the search and say which one is chosen. */
  async status() {
    await run("", [375, 1440], async (page) => {
      await results(page).first().waitFor();
      await page.locator('[data-search-status="rejected"]').click();
      await page.locator('[data-search-status="rejected"][aria-pressed="true"]').waitFor();
      await page.waitForFunction(() => document.querySelector("[data-search-result]")?.getAttribute("data-search-result") === "by-author");
      assert.deepEqual(await ids(page), ["by-author", "acoustic"]);
      assert.equal((await calls(page)).at(-1)?.show, "rejected");
      await page.locator('[data-search-status="pending"]').click();
      await page.waitForFunction(() => document.querySelector("[data-search-result]")?.getAttribute("data-search-result") === "sound-leak" && document.querySelectorAll("[data-search-result]").length === 2);
      assert.deepEqual(await ids(page), ["sound-leak", "ultrasonic"]);
      assert.equal((await calls(page)).at(-1)?.show, "unrated");
      await page.locator('[data-search-status="any"]').click();
      await page.waitForFunction(() => document.querySelectorAll("[data-search-result]").length === 6);
    });
  },

  /** A new query from the page itself, an empty answer, a failure, the words-only notice, and more results. */
  async states() {
    await run("", [375, 1440], async (page) => {
      await results(page).first().waitFor();
      await page.locator("[data-search-input]").fill("nothing");
      await page.locator("[data-search-submit]").click();
      await page.locator("[data-search-empty]").waitFor();
      assert.match(await page.locator("[data-search-empty]").innerText(), /Nothing matches/);
      assert.equal((await calls(page)).at(-1)?.query, "nothing");
    });
    await run("?status=rejected&empty", [375], async (page) => {
      await page.locator("[data-search-empty]").waitFor();
      assert.match(await page.locator("[data-search-empty]").innerText(), /among rejected References/);
      await page.locator("[data-search-status-clear]").click();
      assert.equal((await calls(page)).at(-1)?.show, "all");
    });
    await run("?fail", [375], async (page) => {
      await page.locator("[data-search-error]").waitFor();
      assert.match(await page.locator("[data-search-error]").innerText(), /could not be reached/);
      await page.locator("[data-search-retry]").click();
      await page.waitForFunction(() => (window as unknown as { calls: unknown[] }).calls.length === 2);
    });
    await run("?words-only", [375], async (page) => {
      await page.locator("[data-search-notice]").waitFor();
      assert.match(await page.locator("[data-search-notice]").innerText(), /words only/);
    });
    await run("?paged", [375, 1440], async (page) => {
      await page.locator("[data-search-more]").waitFor();
      assert.equal(await results(page).count(), 3);
      await page.locator("[data-search-more]").click();
      await page.waitForFunction(() => document.querySelectorAll("[data-search-result]").length === 6);
      assert.equal(await page.locator("[data-search-more]").count(), 0);
      assert.equal((await calls(page)).at(-1)?.cursor, "next");
    });
    await run("?q=", [375], async (page) => {
      await page.locator("[data-search-idle]").waitFor();
      assert.equal(await results(page).count(), 0);
      assert.deepEqual(await calls(page), []);
    });
  },
};

async function screenshots() {
  if (!shots) return;
  fs.mkdirSync(shots, { recursive: true });
  for (const [width, height] of [[375, 900], [1440, 1100]] as const) {
    for (const scheme of ["light", "dark"] as const) {
      const { browser, page } = await setup("", width, scheme, height);
      try {
        await results(page).first().waitFor();
        await page.waitForTimeout(300);
        await page.screenshot({ path: `${shots}/search-results-${width}-${scheme === "light" ? "day" : "night"}.png`, fullPage: true });
      } finally { await browser.close(); }
    }
  }
}

/** SEARCH_EXPORT_DIR=<dir>: write the page as two self-contained HTML files (day and night) for `npx playwright screenshot`. */
async function exportPages(dir: string) {
  fs.mkdirSync(dir, { recursive: true });
  const script = (await browserBundle()).replace(/<\/script/g, "<\\/script");
  const tailwind = await compiledTailwind();
  for (const scheme of ["light", "dark"] as const) {
    const html = `<html class="${scheme === "dark" ? "dark" : ""}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="px-4 py-3"></div><script>${script}</script></body></html>`;
    fs.writeFileSync(`${dir}/search-${scheme === "light" ? "day" : "night"}.html`, html);
  }
}

async function main() {
  if (process.env.SEARCH_EXPORT_DIR) { await exportPages(process.env.SEARCH_EXPORT_DIR); return; }
  const wanted = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (wanted && wanted !== name) continue;
    await scenario();
    console.log(`ok ${name}`);
  }
  if (!wanted || wanted === "shots") await screenshots();
}

main().catch((error) => { console.error(error); process.exit(1); });
