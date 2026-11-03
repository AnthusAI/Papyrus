/** Fixture-only browser acceptance for star ratings on the real References view (PPY-3247f1). No production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://card-suggestions.test";
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
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ contents: path === "navigation"
        ? "import {useSyncExternalStore} from 'react'; const subscribe = (notify) => {window.addEventListener('popstate',notify);return () => window.removeEventListener('popstate',notify);}; export const usePathname = () => useSyncExternalStore(subscribe,() => window.location.pathname);"
        : "export const loadReferenceAttachmentsForLineageId = async () => []; export const loadStoragePathUrl = async () => ({url:null}); export const loadStoragePathText = async () => ({text:null,error:null}); export const loadModelPayloadsForOwner = async () => []; export const uploadModelPayloadForOwner = async () => ({ id: \"upload\" });", loader: "js", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "card-suggestions-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
import { ReferenceLinksStoreProvider, createMemoryReferenceLinksStore } from "./components/reference-links-context";
const params = new URLSearchParams(location.search);
const count = Number(params.get('count') || 3);
const rows = Array.from({ length: count }, (_, n) => ({
  id: 'r' + n + '-v1', lineageId: 'r' + n, versionState: 'current', versionNumber: 1, corpusId: 'fixture-corpus', externalItemId: 's' + n, title: 'Reference ' + n,
  sourceUri: 'https://example.test/' + n, importedAt: '2026-10-20T10:00:00Z', curationStatus: 'pending',
}));
const concept = (id, hashtag) => ({ kind: 'concept', lineageId: id, title: hashtag.slice(1), hashtag, nodeKey: 'concept--' + id, nodeKind: 'concept', host: null, sourceUri: null, sourcePublishedAt: null, addedAt: null });
const reference = (id, title) => ({ kind: 'reference', lineageId: id, title, hashtag: null, nodeKey: null, nodeKind: null, host: 'other.test', sourceUri: 'https://other.test/' + id, sourcePublishedAt: null, addedAt: '2026-10-01' });
const items = [...rows.map((row) => reference(row.lineageId, row.title)), concept('c1', '#voice'), concept('c2', '#speech'), concept('c3', '#translation'), reference('x1', 'A related report'), reference('x2', 'Another related report'), reference('x3', 'A third report')];
const link = (id, subject, object, objectKind, similarity) => ({ id, subjectKind: 'reference', subjectLineageId: subject, objectKind, objectLineageId: object, state: 'suggested', provenance: 'suggested', similarity });
// Reference 0 has three concept suggestions and three Reference suggestions; the others have none.
const links = [link('l1', 'r0', 'c1', 'semanticNode', 0.9), link('l2', 'r0', 'c2', 'semanticNode', 0.8), link('l3', 'r0', 'c3', 'semanticNode', 0.4), link('l4', 'r0', 'x1', 'reference', 0.85), link('l5', 'r0', 'x2', 'reference', 0.6), link('l6', 'r0', 'x3', 'reference', 0.3)];
window.fixtureCalls = [];
window.fixtureReads = [];
const store = createMemoryReferenceLinksStore({ items, links, onCall: (call) => window.fixtureCalls.push(call) });
const counted = { ...store, listForReference: async (lineage) => { window.fixtureReads.push(lineage); return store.listForReference(lineage); } };
function Fixture() {
  const [references] = useState(rows);
  return <ReferenceLinksStoreProvider store={counted}><NewsroomReferencesView demo references={references} onReview={async () => undefined} /></ReferenceLinksStoreProvider>;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = `body{margin:0;font:16px sans-serif}button,textarea,select{font:inherit} [data-newsroom-list-row]{text-align:left;padding:12px;margin:4px} [data-radix-scroll-area-viewport]{max-height:75vh} [role=dialog]{position:fixed;inset:5vh 0 0;background:white;overflow:auto;z-index:60}`;

async function setup(options = "", width = 1280) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom/references${options}`);
  return { browser, page, errors };
}

const includeRated = async (page: Page) => { await page.locator('[data-feed-show-button="all"]').click(); };
const card = (page: Page, id: string) => page.locator(`[data-feed-card="${id}"]`);
const calls = (page: Page) => page.evaluate(() => (window as unknown as { fixtureCalls: Array<Record<string, unknown>> }).fixtureCalls);
const reads = (page: Page) => page.evaluate(() => (window as unknown as { fixtureReads: string[] }).fixtureReads);

const scenarios: Record<string, () => Promise<void>> = {
  /** The card shows the two most likely suggested concepts and the two most likely References, most likely first, with Accept and Reject on each. */
  async the_most_likely_suggestions() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").locator("[data-card-suggestion]").first().waitFor();
      const rows = card(page, "r0").locator("[data-card-suggestion]");
      assert.equal(await rows.count(), 4, "two concepts and two References, not all six");
      assert.deepEqual(await rows.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-card-suggestion"))), ["l1", "l2", "l4", "l5"], "most likely first within each kind");
      assert.equal(await card(page, "r1").locator("[data-card-suggestion]").count(), 0, "a card with none shows nothing");
      assert.equal(await card(page, "r0").locator("[data-card-suggestion] select").count(), 0, "no dropdowns");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** One tap on Accept or Reject records the decision with the Related section's own store call, and the suggestion leaves the card. */
  async one_tap_decides() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").locator('[data-card-suggestion="l1"]').waitFor();
      await card(page, "r0").locator('[data-card-suggestion="l1"] [data-card-suggestion-accept]').click();
      await card(page, "r0").locator('[data-card-suggestion="l1"]').waitFor({ state: "detached" });
      await card(page, "r0").locator('[data-card-suggestion="l4"] [data-card-suggestion-reject]').click();
      await card(page, "r0").locator('[data-card-suggestion="l4"]').waitFor({ state: "detached" });
      assert.deepEqual((await calls(page)).filter((call) => call.type === "decide"), [{ type: "decide", relationId: "l1", decision: "accept" }, { type: "decide", relationId: "l4", decision: "reject" }]);
      assert.equal(await card(page, "r0").getAttribute("data-feed-rated"), null, "deciding a suggestion is not a vote on the Reference");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Suggestions are read for the cards on screen only, a few at a time: a long feed does not read every Reference at once. */
  async only_what_is_on_screen_is_read() {
    const { browser, page, errors } = await setup("?count=40");
    try {
      await card(page, "r0").waitFor();
      await page.waitForTimeout(800);
      const first = await reads(page);
      assert.ok(first.length > 0 && first.length < 40, `${first.length} reads for 40 cards: only the visible ones`);
      assert.equal(new Set(first).size, first.length, "no Reference is read twice");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone: large Accept and Reject targets, nothing scrolls sideways, Lucide icons only. */
  async phone() {
    const { browser, page, errors } = await setup("", 375);
    try {
      await card(page, "r0").locator('[data-card-suggestion="l1"]').waitFor();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "nothing scrolls sideways");
      const box = (await card(page, "r0").locator('[data-card-suggestion="l1"] [data-card-suggestion-accept]').boundingBox())!;
      assert.ok(box.height >= 40, "a large tap target");
      for (const icon of await card(page, "r0").locator("[data-card-suggestions] svg").all()) assert.ok(await icon.evaluate((svg) => [...svg.classList].some((name) => name.startsWith("lucide"))), "Lucide icons only");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

export async function runCardSuggestionsScenario(name: string) {
  assert.ok(scenarios[name], `Unknown card suggestions scenario: ${name}`);
  await scenarios[name]();
  console.log(`Card suggestions scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : Object.keys(scenarios)) await runCardSuggestionsScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
