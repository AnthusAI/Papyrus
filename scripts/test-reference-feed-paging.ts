/**
 * Fixture-only browser acceptance for the References feed loading lazily: the page mounts the real view over a fake paged source standing in
 * for the two indexes (2,000 synthetic References), and the test counts the requests the page makes and the size of each. 375 and 1440
 * pixels. No network, no production reads.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://reference-paging.test";
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
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /news-desk-taxonomy-client$/ }, () => ({ path: "taxonomy", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({
        contents: path === "navigation"
          ? "import {useSyncExternalStore} from 'react'; const subscribe = (notify) => {window.addEventListener('popstate',notify);return () => window.removeEventListener('popstate',notify);}; export const usePathname = () => useSyncExternalStore(subscribe,() => window.location.pathname);"
          : `export const loadReferenceAttachmentsForLineageId = async (lineage) => { window.fake.attachmentReads.push(lineage); return []; };
export const loadStoragePathUrl = async () => ({url:null,error:null});
export const loadStoragePathText = async () => ({text: null, error: null});
export const loadModelPayloadsForOwner = async () => [];
export const uploadModelPayloadForOwner = async () => ({ id: "upload" });`,
        loader: "js", resolveDir: root,
      }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "reference-paging-fixture.tsx", contents: `
import { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
import { compareFeedRecords } from "./lib/reference-feed-pages";
import { referenceFeedKeys } from "./lib/reference-feed-keys";

const params = new URLSearchParams(location.search);
const TOTAL = Number(params.get("total") || 2000);
const RATED = Number(params.get("rated") || 300);
const START = Date.parse("2026-10-01T00:00:00Z");
const LATENCY = Number(params.get("latency") || 40);

const make = (n, status) => {
  const id = "r" + String(n).padStart(5, "0");
  const probability = n % 9 === 0 ? null : ((n * 37) % 100) / 100;
  const base = { id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title: "Reference " + id,
    sourceUri: "https://" + id + ".example.org/story", curationStatus: status, createdAt: new Date(START + n * 60000).toISOString(), predictedAcceptProbability: probability };
  return { ...base, ...referenceFeedKeys(base) };
};
// Rated References are every seventh one; the rest are unrated.
let rows = Array.from({ length: TOTAL }, (_, n) => make(n, n % 7 === 0 && n / 7 < RATED ? (n % 2 ? "accepted" : "rejected") : "pending"));
const byLineage = () => new Map(rows.map((row) => [row.lineageId, row]));
window.fake = { pages: [], companions: [], references: [], news: [], attachmentReads: [], rated: 0, inflight: 0 };
const delay = (value) => { window.fake.inflight += 1; return new Promise((resolve) => setTimeout(() => { window.fake.inflight -= 1; resolve(value); }, LATENCY)); };
window.fakeAdd = () => { const n = rows.length + 1; const row = make(n, "pending"); const fresh = new Date(Date.now() + 60000).toISOString(); const patched = { ...row, createdAt: fresh, ...referenceFeedKeys({ ...row, createdAt: fresh }) }; rows = [...rows, patched]; return patched.lineageId; };
window.expectedOrder = (sort, show) => rows
  .filter((row) => show === "all" || row.curationStatus === "pending")
  .sort(compareFeedRecords(sort)).map((row) => row.lineageId);

const source = {
  async fetchPage(request) {
    const wanted = rows.filter((row) => (request.stream === "rated") === (row.curationStatus !== "pending")).sort(compareFeedRecords(request.sort));
    const start = request.nextToken ? Number(request.nextToken) : 0;
    const items = wanted.slice(start, start + request.limit);
    window.fake.pages.push({ stream: request.stream, sort: request.sort, limit: request.limit, returned: items.length, token: request.nextToken });
    return delay({ items, nextToken: start + request.limit < wanted.length ? String(start + request.limit) : null });
  },
  async fetchCompanions(references) {
    window.fake.companions.push(references.map((row) => row.lineageId));
    return delay({
      attachments: references.map((row) => ({ id: "a-" + row.lineageId, referenceId: row.id, referenceLineageId: row.lineageId, referenceVersionKey: "reference#" + row.id, role: "source", sortKey: "1", sourceUri: row.sourceUri })),
      decisions: new Map(references.filter((row) => row.predictedAcceptProbability !== null).map((row) => [row.lineageId, {
        decisionRelationId: "d-" + row.lineageId, decisionId: "d-" + row.lineageId, label: row.predictedAcceptProbability >= 0.5 ? "include" : "exclude",
        confidence: row.predictedAcceptProbability >= 0.5 ? row.predictedAcceptProbability : 1 - row.predictedAcceptProbability, version: 1, reviewRecommended: false,
        reviewReason: null, reviewDetail: null, classes: ["include", "exclude"], positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null }])),
    });
  },
  async fetchReference(id) { window.fake.references.push(id); return delay(byLineage().get(id) ?? null); },
  async countNew({ since, known }) { window.fake.news.push(since); return delay(rows.filter((row) => row.curationStatus === "pending" && row.feedArrivalAt > since && !known.has(row.lineageId)).length); },
  async hasRated() { window.fake.rated += 1; return delay(rows.some((row) => row.curationStatus !== "pending")); },
};

function Fixture() {
  const [saved, setSaved] = useState([]);
  async function review(reference, action) {
    window.fake.reviews = [...(window.fake.reviews || []), { id: reference.lineageId, action }];
    rows = rows.map((row) => row.lineageId === reference.lineageId ? { ...row, curationStatus: action === "accept" ? "accepted" : "rejected" } : row);
  }
  return <div style={{ height: "100dvh", display: "flex", flexDirection: "column", padding: 12 }}>
    <NewsroomReferencesView onReview={review} references={[]} source={source} initialReferenceLineageId={params.get("open") || undefined} />
  </div>;
}
createRoot(document.getElementById("root")).render(<Fixture />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

type Fake = { inflight: number; pages: Array<{ stream: string; sort: string; limit: number; returned: number; token: string | null }>; companions: string[][]; references: string[]; news: string[]; attachmentReads: string[]; rated: number; reviews?: Array<{ id: string; action: string }> };
const fake = (page: Page) => page.evaluate(() => (window as unknown as { fake: Fake }).fake);
const cardIds = (page: Page) => page.locator("[data-feed-card]").evaluateAll((cards) => cards.map((card) => card.getAttribute("data-feed-card")!));
const expected = (page: Page, sort: string, show: string) => page.evaluate(([s, h]) => (window as unknown as { expectedOrder: (sort: string, show: string) => string[] }).expectedOrder(s!, h!), [sort, show]);
/** Wait until the page has no request in flight and none starts for a moment. */
async function settle(page: Page, ms = 250) {
  for (let quiet = 0; quiet < 2;) {
    await page.waitForTimeout(ms / 2);
    quiet = (await page.evaluate(() => (window as unknown as { fake: Fake }).fake.inflight)) === 0 ? quiet + 1 : 0;
  }
}

async function setup(width: number, options = "", path = "/newsroom/references") {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const context = await browser.newContext({ viewport: { width, height: 800 } });
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    if (url.pathname === "/api/newsroom/source-frameable") return route.fulfill({ contentType: "application/json", body: JSON.stringify({ frameable: false }) });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>body{margin:0;font:16px sans-serif}button,textarea{font:inherit}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}${path}${options}`);
  return { browser, page, errors };
}

/** Scroll the feed's own scroller to the bottom, as a reader would. */
async function scrollToEnd(page: Page) {
  await page.locator("[data-reference-feed-scroll]").first().evaluate((viewport) => { viewport.scrollTop = viewport.scrollHeight; });
}

const scenarios: Record<string, () => Promise<void>> = {
  /** The first visit reads one page of 24 and its companions; scrolling to the end reads exactly one more; Load more is the fallback. */
  async first_page() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width, "?latency=300");
      try {
        await page.locator("[data-feed-card]").first().waitFor();
        await settle(page);
        let seen = await fake(page);
        assert.deepEqual(seen.pages.map((entry) => [entry.stream, entry.sort, entry.limit, entry.returned]), [["unrated", "best", 24, 24]], "one page request of 24, for the unrated stream in Best bets order");
        assert.equal(seen.companions.length, 1, "one request for the page's attachments and decisions");
        assert.equal(seen.companions[0]!.length, 24, "for the 24 References on the page and no others");
        assert.equal(await page.locator("[data-feed-card]").count(), 24);
        assert.equal(seen.attachmentReads.length, 0, "no attachment is read one Reference at a time");
        assert.deepEqual(await cardIds(page), (await expected(page, "best", "unrated")).slice(0, 24), "the first page is the top of Best bets");
        assert.equal(await page.locator("[data-feed-load-more]").count(), 1, "a Load more button is there as the fallback");

        await scrollToEnd(page);
        await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length >= 48);
        await settle(page);
        seen = await fake(page);
        assert.equal(await page.locator("[data-feed-card]").count(), 48, "scrolling to the end loaded exactly one more page");
        assert.deepEqual(seen.pages.map((entry) => entry.limit), [24, 24], "every page is 24");
        assert.equal(seen.pages[1]!.token, "24", "the second page continues the first");
        assert.deepEqual(seen.companions.map((ids) => ids.length), [24, 24], "the second page's companions are the second page's References only");
        assert.deepEqual(await cardIds(page), (await expected(page, "best", "unrated")).slice(0, 48));

        // The skeleton row has the final cards' shape and is shown while a page is on its way.
        await page.evaluate(() => { document.querySelector<HTMLButtonElement>("[data-feed-load-more]")!.click(); });
        await page.locator("[data-reference-feed-skeleton=more]").waitFor({ state: "attached" });
        assert.ok(await page.locator("[data-reference-feed-skeleton=more] > div").first().evaluate((el) => el.getBoundingClientRect().height) > 150, "a skeleton card in the final card shape");
        await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length >= 72);
        assert.equal((await fake(page)).pages.length, 3);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Include rated: two cursors merged by the sort's key; each stream is paged only as far as the page needs. */
  async include_rated() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await page.locator("[data-feed-card]").first().waitFor();
        await page.locator("[data-feed-show-button=all]").click();
        await page.waitForFunction(() => (window as unknown as { fake: Fake }).fake.pages.some((entry) => entry.stream === "rated"));
        await page.locator("[data-feed-card]").nth(23).waitFor();
        await settle(page);
        const seen = await fake(page);
        const rated = seen.pages.filter((entry) => entry.stream === "rated");
        assert.equal(rated.length, 1, "the rated stream was asked for once, a page of 24");
        assert.equal(rated[0]!.limit, 24);
        const ids = await cardIds(page);
        assert.deepEqual(ids, (await expected(page, "best", "all")).slice(0, 24), "both streams merged in Best bets order");
        assert.ok(await page.locator("[data-feed-rated]").count() > 0, "answered cards show their vote in the merged list");
        await page.locator("[data-feed-sort-button=newest]").click();
        await page.waitForFunction(() => document.querySelector("[data-reference-feed]")?.getAttribute("data-feed-sort") === "newest");
        await page.locator("[data-feed-card]").nth(23).waitFor();
        await settle(page);
        assert.deepEqual(await cardIds(page), (await expected(page, "newest", "all")).slice(0, 24), "merged by arrival in Newest");
        // Scrolling pulls from whichever stream is next, and never shows a card twice.
        for (let step = 0; step < 3; step += 1) { await scrollToEnd(page); await settle(page, 400); }
        const more = await cardIds(page);
        assert.equal(new Set(more).size, more.length, "no card twice");
        assert.deepEqual(more, (await expected(page, "newest", "all")).slice(0, more.length));
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Scrolling and rating leave every card where it is. */
  async nothing_reshuffles() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await page.locator("[data-feed-card]").nth(23).waitFor();
        await settle(page);
        const positions = () => page.locator("[data-feed-card]").evaluateAll((cards) => cards.map((card) => {
          const box = card.getBoundingClientRect();
          const scroller = card.closest("[data-reference-feed-scroll]")!;
          return [card.getAttribute("data-feed-card"), Math.round(box.top - scroller.getBoundingClientRect().top + scroller.scrollTop), Math.round(box.left)];
        }));
        const before = await positions();
        await scrollToEnd(page);
        await page.waitForFunction(() => document.querySelectorAll("[data-feed-card]").length >= 48);
        await settle(page);
        const after = await positions();
        assert.deepEqual(after.slice(0, 24), before, "the first page did not move or change order while the next page loaded");
        // Rate one: it keeps its place, shows its answer, and the Reference is not read again.
        const target = before[5]![0] as string;
        await page.locator(`[data-feed-card="${target}"] [data-review-choice=accept]`).first().evaluate((el) => (el as HTMLElement).click());
        await settle(page, 500);
        const rated = await positions();
        assert.deepEqual(rated.map((entry) => entry[0]), after.map((entry) => entry[0]), "rating a card changes no card's place");
        assert.equal(await page.locator(`[data-feed-card="${target}"]`).getAttribute("data-feed-rated"), "accept");
        assert.deepEqual((await fake(page)).reviews, [{ id: target, action: "accept" }]);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** New arrivals wait behind the pill; the cheap check runs on focus; showing them starts the visit over. */
  async new_arrivals() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await page.locator("[data-feed-sort-button=newest]").click();
        await page.locator("[data-feed-card]").nth(23).waitFor();
        await settle(page);
        const before = await cardIds(page);
        assert.equal(await page.locator("[data-feed-new-items]").count(), 0);
        const added = await page.evaluate(() => (window as unknown as { fakeAdd: () => string }).fakeAdd());
        await page.evaluate(() => window.dispatchEvent(new Event("focus")));
        await page.locator("[data-feed-new-items]").waitFor();
        assert.equal((await page.locator("[data-feed-new-items]").innerText()).trim(), "1 new item: show");
        assert.deepEqual(await cardIds(page), before, "the pill never moves a card");
        const seen = await fake(page);
        assert.ok(seen.news.length >= 1, "the check was a request of its own");
        assert.equal(seen.pages.length, 2, "and loaded no page: the two pages are the first visit's Best bets then Newest");
        await page.locator("[data-feed-new-items]").click();
        await page.waitForFunction((id) => document.querySelector("[data-feed-card]")?.getAttribute("data-feed-card") === id, added);
        assert.equal(await page.locator("[data-feed-new-items]").count(), 0);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** A link to a Reference far down the feed opens it from one read of that Reference, not from the feed. */
  async deep_link() {
    for (const width of [375, 1440]) {
      const target = "r01500";
      const { browser, page, errors } = await setup(width, "", `/newsroom/references/${target}`);
      try {
        await page.locator("[data-review-card]").locator("visible=true").first().waitFor();
        await settle(page);
        const seen = await fake(page);
        assert.deepEqual(seen.references, [target], "that one Reference was read by its id");
        assert.ok(seen.companions.some((ids) => ids.length === 1 && ids[0] === target), "with its own attachments and decision, in a request of one");
        const loaded = seen.pages.reduce((total, entry) => total + entry.returned, 0);
        assert.ok(loaded <= 24, "no more than the first page of the feed was read to show it (" + loaded + ")");
        assert.ok(await page.getByText("Reference " + target).first().isVisible());
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Previous and Next follow the loaded cards, and Next at the end reads the next page. */
  async next_loads_more() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await page.locator("[data-feed-card]").nth(23).waitFor();
        await settle(page);
        const ids = await cardIds(page);
        await page.locator(`[data-feed-card="${ids[23]}"] [data-feed-open]`).click();
        await page.locator("[data-review-queue-position]").waitFor();
        assert.equal((await page.locator("[data-review-queue-position]").innerText()).trim(), "24 of 24+", "the count says more can be read");
        await page.locator("[data-review-queue-bar] button[aria-label=Next]").click();
        await page.waitForFunction(() => (window as unknown as { fake: Fake }).fake.pages.length === 2);
        await page.waitForFunction(() => document.querySelector("[data-review-queue-position]")?.textContent?.trim() === "25 of 48+");
        const expectedIds = await expected(page, "best", "unrated");
        assert.ok(await page.locator(`[data-news-desk-reference-detail="${expectedIds[24]}"]`).first().isVisible(), "the first card of the next page is open");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Reference paging scenario passed: ${name}`);
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
