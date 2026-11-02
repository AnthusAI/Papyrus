/**
 * Link suggestions in "What needs me", and the phone detail that covers the whole screen. Fixture-only: an isolated browser, the real
 * Tailwind build, an in-memory links store behind the real NotificationCenter. Nothing leaves the page.
 *   tsx scripts/test-needs-me-links.ts [unit|queue|detail|concept|more|sheet|sheets]   (no name runs them all)
 * NEEDS_ME_SHOTS_DIR=<dir> also writes screenshots (phone and desktop, light and dark).
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { compareSuggestions, isOpenSuggestion, lineagesOfSuggestionRows, suggestionsFromRows } from "../lib/link-suggestions";
import { buildNeedsMeItems, linkSuggestionItems, waitingTextFor } from "../lib/needs-me-items";
import { countNeedsMe, matchesFilter, rankNeedsMe } from "../lib/needs-me-ranking";
import { localPreviewLinkSuggestionItems, localPreviewLinkSuggestions } from "../lib/local-preview-reference-links";
import { createMemoryReferenceLinksStore } from "../components/reference-links-context";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://needs-me-links.test";
const shots = process.env.NEEDS_ME_SHOTS_DIR;
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
      builder.onResolve({ filter: /(review-client)$/ }, () => ({ path: "network", namespace: "fixture" }));
      builder.onResolve({ filter: /monitoring-client$/ }, () => ({ path: "monitoring", namespace: "fixture" }));
      builder.onResolve({ filter: /news-desk-taxonomy-client$/ }, () => ({ path: "taxonomy", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/link$/ }, () => ({ path: "link", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({
        contents: path === "monitoring"
          ? "export const loadMonitoringPage = async () => ({ state: 'unavailable' }); export const loadMonitoringEmailSubmission = async () => ({ state: 'unavailable' }); export const decideMonitoringEmailSubmission = async () => ({ state: 'unavailable' });"
          : path === "taxonomy"
          ? "export const loadModelPayloadsForOwner = async () => []; export const loadStoragePathText = async () => ''; export const loadReferenceAttachmentsForLineageId = async () => []; export const loadStoragePathUrl = async () => ({ url: null }); export const uploadModelPayloadForOwner = async () => ({ id: 'upload' });"
          : path === "navigation"
          ? "export const usePathname = () => window.location.pathname; export const useRouter = () => ({ push(href) { window.pushed = href; } });"
          : path === "link"
            ? "import {createElement} from 'react'; export default function Link({href, children, prefetch, ...rest}) { return createElement('a', {href, ...rest}, children); }"
            : path === "network"
              ? "export const loadReviews = async () => ({ state: 'ready', requests: [], readIds: [], userKey: 'u1' }); export const loadStoryTitles = async () => ({ titles: {}, deleted: [] }); export const markReviewRead = async () => {};"
              : "export {};",
        loader: "js", resolveDir: root,
      }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "needs-me-links-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NotificationCenter } from "./components/notification-center";
import { ReferenceLinksStoreProvider, createMemoryReferenceLinksStore } from "./components/reference-links-context";
import { localPreviewLinkSuggestionItems, localPreviewLinkSuggestions } from "./lib/local-preview-reference-links";

const params = new URLSearchParams(location.search);
window.calls = [];
const store = createMemoryReferenceLinksStore({
  items: localPreviewLinkSuggestionItems(), links: localPreviewLinkSuggestions(),
  suggestedPageSize: params.has("size") ? Number(params.get("size")) : undefined,
  onCall: (call) => window.calls.push(call),
});
let failures = params.has("fail") ? 1 : 0;
const own = params.has("context") ? {} : { loadLinkSuggestions: (cursor) => store.listSuggested(cursor) };
const api = {
  loadReviews: async () => ({ state: "ready", requests: [], readIds: [], userKey: "u1" }),
  loadStoryTitles: async () => ({ titles: {}, deleted: [] }),
  answerReviewRequest: async (request) => request,
  saveReviewReason: async (request) => request,
  markReviewRead: async () => {},
  loadHeldEmails: async () => [],
  ...own,
  ...(params.has("context") ? {} : { decideLink: async (relationId, decision, reason) => {
    if (failures > 0) { failures -= 1; throw new Error("The decision could not be saved."); }
    await store.decide({ relationId, decision, ...(reason ? { note: reason } : {}) });
  } }),
};
const center = <NotificationCenter actorLabel="Ed Itor" api={api} decisions={new Map()} demo={false} humanCuratedReferenceLineageIds={new Set()} references={[]} />;
createRoot(document.getElementById("root")).render(params.has("context") ? <ReferenceLinksStoreProvider store={store}>{center}</ReferenceLinksStoreProvider> : center);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const LIGHT = "--background:#f4f1ea;--foreground:#1c1c1c;--muted-foreground:#6b6b6b;--card:#fbf9f4;--primary:#46560f;--primary-foreground:#fff;--ring:#46560f;--feed-card:#fbf9f4;--feed-control:#e8e3d8;--feed-footer:#f0ece2";
const DARK = "--background:#14130f;--foreground:#ece8dc;--muted-foreground:#a29e92;--card:#1d1c17;--primary:#c6f432;--primary-foreground:#1c1c1c;--ring:#c6f432;--feed-card:#1d1c17;--feed-control:#2b2a23;--feed-footer:#23221c";
const fixtureCss = `html,body{height:100%}body{margin:0;font:16px sans-serif;background:var(--background);color:var(--foreground)}#root{height:100%;box-sizing:border-box}:root{${LIGHT};--feed-radius-xl:16px;--feed-radius-lg:14px;--feed-radius-md:12px;--feed-radius-pill:999px;--feed-quiet:.6;--feed-verdict-match-fill:#059669;--feed-verdict-miss-fill:#dc2626;--border:transparent;--input:#e8e3d8;--accent:#e8e3d8;--accent-foreground:#1c1c1c;--muted:#e8e3d8;--popover:#fbf9f4;--popover-foreground:#1c1c1c;--secondary:#e8e3d8;--secondary-foreground:#1c1c1c;--destructive:#b91c1c}@media (prefers-color-scheme:dark){:root{${DARK};--input:#2b2a23;--accent:#2b2a23;--accent-foreground:#ece8dc;--muted:#2b2a23;--popover:#1d1c17;--popover-foreground:#ece8dc;--secondary:#2b2a23;--secondary-foreground:#ece8dc}}button,textarea{font:inherit}`;

type Scheme = "light" | "dark";

export async function setup(options = "", width = 1440, height = 900, scheme: Scheme = "light") {
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
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width, viewport-fit=cover"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom${options}`);
  return { browser, page, errors };
}

const calls = (page: Page) => page.evaluate(() => (window as unknown as { calls: Array<Record<string, unknown>> }).calls);
const cards = (page: Page) => page.locator('[data-needs-me-card="link_suggestion"]');
const titles = async (page: Page) => (await cards(page).locator("[data-feed-title]").allInnerTexts());
const detail = (page: Page) => page.locator("[data-link-suggestion-detail]");

async function run(options: string, sizes: Array<[number, number]>, body: (page: Page, width: number) => Promise<void>) {
  for (const [width, height] of sizes) {
    const { browser, page, errors } = await setup(options, width, height);
    try {
      await body(page, width);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  }
}

async function shoot(name: string, options: string, width: number, height: number, act: (page: Page) => Promise<void>) {
  if (!shots) return;
  fs.mkdirSync(shots, { recursive: true });
  for (const scheme of ["dark", "light"] as const) {
    const { browser, page } = await setup(options, width, height, scheme);
    try {
      await act(page);
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${shots}/${name}-${width}x${height}-${scheme}.png` });
    } finally { await browser.close(); }
  }
}

const PHONE: [number, number] = [390, 844];
const DESKTOP: [number, number] = [1440, 900];

const openLinks = async (page: Page) => {
  await cards(page).first().waitFor();
  await page.locator('[data-notification-filter="links"]').click();
};
const openFirst = async (page: Page) => {
  await openLinks(page);
  await cards(page).first().locator("[data-feed-open]").click();
  await detail(page).first().waitFor();
};

const scenarios: Record<string, () => Promise<void>> = {
  /** Pure: the rows, the ranking, the items, the counts. */
  async unit() {
    const refs = localPreviewLinkSuggestionItems();
    const resolve = (kind: "concept" | "reference", id: string) => refs.find((item) => item.kind === kind && item.lineageId === id) ?? null;
    const row = (id: string, score: number | null, state = "suggested", objectKind = "reference", objectLineageId = "preview-reference-lineage-4") => ({
      id, relationState: state, predicate: "related_to", subjectKind: "reference", subjectLineageId: "preview-reference-lineage-1", objectKind, objectLineageId, score,
    });
    assert.equal(isOpenSuggestion(row("a", 0.5)), true);
    assert.equal(isOpenSuggestion(row("a", 0.5, "current")), false, "a decided link is not a suggestion");
    assert.equal(isOpenSuggestion({ ...row("a", 0.5), predicate: "cites" }), false);
    assert.equal(isOpenSuggestion({ ...row("a", 0.5), subjectKind: "item" }), false);
    const ranked = suggestionsFromRows([row("low", 0.4), row("none", null), row("high", 0.93), row("rejected", 0.99, "rejected"), row("gone", 0.8, "suggested", "reference", "missing"), row("high", 0.93)], resolve);
    assert.deepEqual(ranked.map((entry) => entry.relationId), ["high", "low", "none"], "most likely first, no close match last, nothing unresolved or already decided, no repeats");
    assert.deepEqual(lineagesOfSuggestionRows([row("a", 0.5), row("b", 0.5, "suggested", "semanticNode", "preview-concept-translation")]), { concepts: ["preview-concept-translation"], references: ["preview-reference-lineage-1", "preview-reference-lineage-4"] });
    assert.ok(compareSuggestions({ ...ranked[0], createdAt: "2026-10-30T00:00:00Z", similarity: 0.5 }, { ...ranked[0], relationId: "z", createdAt: "2026-10-01T00:00:00Z", similarity: 0.5 }) < 0, "equal matches: the newer first");

    const store = createMemoryReferenceLinksStore({ items: refs, links: localPreviewLinkSuggestions(), suggestedPageSize: 3 });
    const first = await store.listSuggested!(null);
    assert.equal(first.suggestions.length, 3);
    assert.deepEqual(first.suggestions.map((entry) => entry.similarity), [0.91, 0.84, 0.72]);
    assert.ok(first.cursor);
    const second = await store.listSuggested!(first.cursor);
    assert.deepEqual(second.suggestions.map((entry) => entry.similarity), [0.66]);
    assert.equal(second.cursor, null, "the last page ends the queue");

    // In the feed: ranked by close match, never skipped for confidence, decided state follows the visit's decisions.
    const items = linkSuggestionItems([...first.suggestions, ...second.suggestions], new Map([[first.suggestions[0].relationId, { choice: "reject" as const, note: "Different harbour." }]]));
    assert.ok(items.every((item) => item.type === "link_suggestion" && item.id.startsWith("link#") && item.askedForReview && !item.hardGate));
    assert.deepEqual(items.map((item) => item.decisionState), ["rejected", "open", "open", "open"]);
    const ranking = rankNeedsMe(items.map((item) => ({ ...item, decisionState: "open" as const })), { threshold: { threshold: 0.9, examples: 20 } });
    assert.equal(ranking.auto.length, 0, "a suggestion with no prediction is never decided automatically");
    assert.deepEqual(ranking.feed.map((item) => item.importance), [0.91, 0.84, 0.72, 0.66]);
    const counts = countNeedsMe(items);
    assert.equal(counts.links, 3, "only open suggestions count");
    assert.equal(matchesFilter(items[0], "links"), true);
    assert.equal(matchesFilter(items[0], "references"), false);
    assert.equal(waitingTextFor(counts), "3 link suggestions waiting for you");
    assert.equal(buildNeedsMeItems({ references: [], decisions: undefined, previews: new Map(), captures: undefined, visitRated: new Set(), requests: [], stay: new Set(), storyTitles: {}, storyExcerpts: {}, deletedStories: new Set(), emails: [], emailsDecided: new Map(), linkSuggestions: first.suggestions }).length, 3);
    console.log("Needs me links scenario passed: unit");
  },

  /** The queue: one card per suggestion, most likely first, in a Links filter that counts them. */
  async queue() {
    await run("", [PHONE, DESKTOP], async (page, width) => {
      await cards(page).first().waitFor();
      assert.equal(await cards(page).count(), 4);
      const pill = page.locator('[data-notification-filter="links"]');
      assert.equal((await pill.innerText()).replace(/\s+/g, " "), "Links 4");
      assert.ok((await page.locator("[data-notification-summary]").innerText()).includes("4 link suggestions waiting for you"));
      assert.deepEqual(await titles(page), [
        "Council minutes on the harbour dredging contract and Harbour dredging: contractor letter",
        "Port authority audit, second quarter and #voice-cloning",
        "Zoning variance hearing, draft transcript and Port authority audit, second quarter",
        "Harbour dredging: contractor letter and #translation (concept)",
      ], "ranked by close match, 0.91 first");
      const first = cards(page).first();
      assert.ok((await first.innerText()).includes("Link suggestion"), "the type is named in words");
      assert.ok((await first.innerText()).includes("close match 0.91"));
      assert.equal(await first.locator("[data-review-choice]").count(), 2, "Accept and Reject on the card");
      assert.equal(await page.locator("#root select").count(), 0, "no dropdowns");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth) <= 0, true, `no horizontal scroll at ${width}px`);
      for (const svg of await page.locator("#root svg").all()) assert.ok(await svg.evaluate((node) => [...node.classList].some((name) => name.startsWith("lucide"))), "every icon is a Lucide icon");
      await page.locator('[data-notification-filter="links"]').click();
      assert.equal(await cards(page).count(), 4);
      await page.locator('[data-notification-filter="references"]').click();
      assert.equal(await cards(page).count(), 0, "other filters leave links out");
    });
    console.log("Needs me links scenario passed: queue");
  },

  /** Paged: only the first page arrives; Load more reads the next and places it at once. */
  async more() {
    await run("?size=2", [DESKTOP], async (page) => {
      await cards(page).first().waitFor();
      assert.equal(await cards(page).count(), 2, "the first page only");
      assert.deepEqual((await calls(page)).filter((call) => call.type === "listSuggested"), [{ type: "listSuggested", cursor: null }]);
      const more = page.locator("[data-needs-me-more-links]");
      assert.ok((await more.innerText()).includes("Load more link suggestions"));
      await more.click();
      await page.waitForFunction(() => document.querySelectorAll('[data-needs-me-card="link_suggestion"]').length === 4);
      assert.deepEqual((await calls(page)).filter((call) => call.type === "listSuggested"), [{ type: "listSuggested", cursor: null }, { type: "listSuggested", cursor: "2" }]);
      assert.equal(await page.locator("[data-needs-me-more-links]").count(), 0, "the queue ended, so no button");
      assert.equal(await page.locator("[data-feed-new-items]").count(), 0, "the new page is placed, not parked behind a pill");
    });
    console.log("Needs me links scenario passed: more");
  },

  /** The detail: both References side by side on a wide pane with both dates, the shared Accept / Reject with a reason, and the same decide-link call as the Related section. */
  async detail() {
    await run("", [DESKTOP, PHONE], async (page, width) => {
      await openFirst(page);
      await page.waitForTimeout(500); // the phone's sheet slides in
      const pane = detail(page).first();
      const text = await pane.innerText();
      assert.ok(text.includes("Should these be linked?") && text.includes("Suggested") && text.includes("close match 0.91"));
      const [subject, object] = [pane.locator('[data-link-end="subject"]'), pane.locator('[data-link-end="object"]')];
      assert.ok((await subject.innerText()).includes("Council minutes on the harbour dredging contract"));
      assert.ok((await object.innerText()).includes("Harbour dredging: contractor letter"));
      assert.equal(await subject.locator("[data-related-dates]").innerText(), "published 2026-10-27 · added 2026-10-28");
      assert.equal(await object.locator("[data-related-dates]").innerText(), "published 2026-10-12 · added 2026-10-30");
      const [a, b] = [await subject.boundingBox(), await object.boundingBox()];
      assert.ok(a && b);
      if (width >= 1000) assert.ok(a.x + a.width <= b.x + 1 && Math.abs(a.y - b.y) < 2, "side by side on a wide pane");
      else assert.ok(a.y + a.height <= b.y + 1, "stacked on a phone");
      assert.equal(await pane.locator('[data-review-choice="accept"]').count(), 1);
      assert.equal(await pane.locator('[data-review-choice="reject"]').count(), 1);
      assert.equal(await pane.locator("select").count(), 0, "no dropdowns");
      const why = pane.getByLabel("Why? (optional)");
      assert.equal(await why.count(), 1, "the optional reason box is there");
      await why.fill("Same contract, same harbour.");
      await pane.locator('[data-review-choice="accept"]').click();
      await page.waitForFunction(() => (window as unknown as { calls: Array<{ type: string }> }).calls.some((call) => call.type === "decide"));
      assert.deepEqual((await calls(page)).filter((call) => call.type === "decide"), [{ type: "decide", relationId: "preview-suggestion-1", decision: "accept", note: "Same contract, same harbour." }], "the same decide-link call, with the decision and reason");
      // Like every Needs me item: the decided one stays showing its answer, and Next goes on to the next suggestion.
      assert.ok((await pane.innerText()).includes("Decided here"), "the decided suggestion says so");
      await page.locator("[data-review-queue-bar] button[aria-label='Next']:visible").first().click();
      await page.locator('[data-link-suggestion-detail="preview-suggestion-2"]').first().waitFor();
    });
    console.log("Needs me links scenario passed: detail");
  },

  /** The page itself gives the feed no link calls: it reads and decides through the related-links store the Related section uses. */
  async context() {
    await run("?context=1", [DESKTOP], async (page) => {
      await openFirst(page);
      const pane = detail(page).first();
      await pane.getByLabel("Why? (optional)").fill("Same harbour.");
      await pane.locator('[data-review-choice="reject"]').click();
      await page.waitForFunction(() => (window as unknown as { calls: Array<{ type: string }> }).calls.some((call) => call.type === "decide"));
      assert.deepEqual((await calls(page)).filter((call) => call.type !== "listSuggested"), [{ type: "decide", relationId: "preview-suggestion-1", decision: "reject", note: "Same harbour." }], "the store's own decide, exactly as the Related section calls it");
    });
    console.log("Needs me links scenario passed: context");
  },

  /** Reject, with and without a reason, and a refusal that leaves the item undecided. */
  async reject() {
    await run("?fail=1", [DESKTOP], async (page) => {
      await openFirst(page);
      const pane = detail(page).first();
      await pane.locator('[data-review-choice="reject"]').click();
      await pane.getByRole("alert").first().waitFor();
      assert.deepEqual((await calls(page)).filter((call) => call.type === "decide"), [], "a refused decision records nothing");
      await pane.locator('[data-review-choice="reject"]').click();
      await page.waitForFunction(() => (window as unknown as { calls: Array<{ type: string }> }).calls.some((call) => call.type === "decide"));
      assert.deepEqual((await calls(page)).filter((call) => call.type === "decide"), [{ type: "decide", relationId: "preview-suggestion-1", decision: "reject" }], "no reason, no note");
    });
    console.log("Needs me links scenario passed: reject");
  },

  /** A Reference and a concept: the concept shows as a hash chip beside the Reference. */
  async concept() {
    await run("", [DESKTOP, PHONE], async (page) => {
      await openLinks(page);
      await cards(page).nth(1).locator("[data-feed-open]").click();
      const pane = detail(page).first();
      await pane.waitFor();
      const concept = pane.locator('[data-link-end="object"] [data-related-concept]');
      assert.equal(await concept.locator("[data-related-hashtag]").innerText(), "#voice-cloning");
      assert.equal(await concept.locator("svg").count(), 1, "a hash icon");
      assert.ok((await pane.locator('[data-link-end="subject"]').innerText()).includes("Port authority audit, second quarter"));
      assert.equal(await pane.locator('[data-link-end="subject"] [data-related-dates]').innerText(), "published 2026-09-30 · added 2026-10-30");
    });
    console.log("Needs me links scenario passed: concept");
  },

  /** On a phone the detail is its own full screen: the whole viewport, header on top, body filling, Previous / Next at the bottom. */
  async sheet() {
    await run("", [PHONE], async (page) => {
      await openFirst(page);
      const popup = page.locator('[data-needs-me-sheet="fullscreen"]');
      await popup.waitFor();
      await page.waitForTimeout(400);
      const box = await popup.boundingBox();
      assert.ok(box);
      assert.deepEqual([Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)], [0, 0, 390, 844], "the sheet is the whole viewport");
      assert.equal(await page.evaluate(() => [[5, 5], [385, 5], [5, 839], [385, 839], [195, 422]].every(([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest('[data-needs-me-sheet="fullscreen"]')))), true, "nothing of the index shows at the corners or the middle");
      const header = await page.locator('[data-needs-me-sheet="fullscreen"] > div').first().boundingBox();
      assert.ok(header && header.y < 1, "the header is at the top");
      const body = await page.locator("[data-needs-me-sheet-body]").boundingBox();
      const bar = await page.locator("[data-needs-me-sheet-footer] [data-review-queue-bar]").boundingBox();
      assert.ok(body && bar);
      assert.ok(Math.abs(bar.y + bar.height - 844) < 2, "Previous / Next sits at the bottom edge");
      assert.ok(body.y + body.height <= bar.y + 1, "the body ends where the bar starts");
      assert.ok(body.height > 0.7 * 844 - 120 && body.height > 560, `the body fills the space (${Math.round(body.height)}px), not a 70% box`);
      assert.equal(await page.evaluate(() => document.querySelector("[data-needs-me-sheet-body]")!.scrollHeight >= document.querySelector("[data-needs-me-sheet-body]")!.clientHeight), true);
      assert.equal(await popup.evaluate((node) => getComputedStyle(node).borderTopWidth), "0px", "no border");
      assert.equal(await popup.evaluate((node) => getComputedStyle(node).borderTopLeftRadius), "0px", "no rounded top: it is the screen");
      await page.keyboard.press("Escape");
      await popup.waitFor({ state: "detached" });
    });
    console.log("Needs me links scenario passed: sheet");
  },

  /** Longer than the screen: the body scrolls inside the sheet and the bar stays pinned. */
  async sheetScroll() {
    await run("", [[390, 560]], async (page) => {
      await openFirst(page);
      const body = page.locator("[data-needs-me-sheet-body]");
      await body.waitFor();
      await page.waitForTimeout(500);
      assert.equal(await body.evaluate((node) => node.scrollHeight > node.clientHeight), true, "the detail is taller than the space, so it scrolls");
      const before = await page.locator("[data-needs-me-sheet-footer]").boundingBox();
      await body.evaluate((node) => { node.scrollTop = node.scrollHeight; });
      const after = await page.locator("[data-needs-me-sheet-footer]").boundingBox();
      assert.deepEqual(before, after, "the bar does not move");
      assert.ok(after && Math.abs(after.y + after.height - 560) < 2, "pinned at the bottom");
      assert.equal(await page.locator('[data-review-choice="reject"]').last().isVisible(), true);
    });
    console.log("Needs me links scenario passed: sheetScroll");
  },

  async screenshots() {
    if (!shots) return;
    const link = async (page: Page, index = 0) => {
      await openLinks(page);
      await cards(page).nth(index).locator("[data-feed-open]").click();
      await detail(page).first().waitFor();
    };
    await shoot("needs-me-link-detail", "", 1440, 900, (page) => link(page));
    await shoot("needs-me-link-detail", "", 390, 844, (page) => link(page));
    await shoot("needs-me-link-concept-detail", "", 390, 844, (page) => link(page, 1));
    await shoot("needs-me-link-feed", "", 390, 844, async (page) => { await openLinks(page); });
    await shoot("needs-me-mobile-sheet-fullscreen", "", 390, 844, async (page) => { await link(page); await page.locator("[data-needs-me-sheet-body]").waitFor(); });
    console.log(`Screenshots written to ${shots}`);
  },
};

async function main() {
  const wanted = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (wanted && wanted !== name) continue;
    if (name === "screenshots" && !shots) continue;
    await scenario();
  }
}

if (process.argv[1]?.endsWith("test-needs-me-links.ts")) main().catch((failure) => { console.error(failure); process.exit(1); });
