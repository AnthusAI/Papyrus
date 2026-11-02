/** Fixture-only browser acceptance for the "Accepted automatically" filter of the real References view. No production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://auto-accepted.test";
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
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "auto-accepted-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
const params = new URLSearchParams(location.search);
const total = params.has('empty') ? 0 : Number(params.get('total') || 5);
const reasonFor = (n, rule) => rule
  ? "Accepted automatically by the ferry-notices monitor's rule (every collected item): it delivers only items that match the rule, so there is no relevance prediction and the match is the acceptance. An editor can still Reject it."
  : "Accepted automatically by the Cyclotron: it was " + (99 - (n % 9)) + ".0% sure this is relevant, at or above the 90.0% learned from 42 editor votes (estimated accept rate 97.6%, 95% lower bound 91.0%, target 90%), and nobody voted within 2.0 days, the 90% quantile of how long editors take. An editor can still Reject it.";
// Newest first: index 0 is the latest acceptance. Every third one is an editor's own acceptance, which the list must never show.
const rows = Array.from({length: total * 2}, (_, n) => {
  const human = n % 3 === 2;
  const rule = !human && n % 4 === 1;
  return {id:'r'+n+'-v1',lineageId:'r'+n,versionState:'current',versionNumber:1,corpusId:'fixture-corpus',externalItemId:'s'+n,title:(human?'Editor accepted ':'Automatically accepted ')+n,sourceUri:'https://example.org/s'+n,
    curationStatus:'accepted',curationStatusUpdatedAt:new Date(Date.parse('2026-11-01T12:00:00Z')-n*3600000).toISOString(),
    curationStatusUpdatedBy:human?'editor@example.test':rule?'auto:rule':'auto:cyclotron',curationStatusReason:human?'Primary source.':reasonFor(n,rule),importedAt:'2026-10-20T10:00:00Z'};
});
const automatic = rows.filter(r => r.curationStatusUpdatedBy.startsWith('auto:'));
window.fixtureRequests = [];
window.fixturePending = [];
window.fixtureReads = [];
function Fixture() {
  const [references,setReferences] = useState(rows);
  async function save(reference,action,options={}) {
    window.fixtureRequests.push({referenceId:reference.id,action,options});
    await new Promise((resolve) => window.fixturePending.push(resolve));
    const status = {accept:'accepted',reject:'rejected',archive:'archived'}[action];
    setReferences(current => current.map(row => row.lineageId === reference.lineageId ? {...row,curationStatus:status,curationStatusUpdatedBy:'editor@example.test',curationStatusUpdatedAt:new Date('2026-11-02T00:00:00Z').toISOString(),curationStatusReason:options.note?.trim() || null} : row));
  }
  // One database page holds 4 rows, as a pager would; the page size asked for is ignored on purpose.
  async function loadAutoAccepted({nextToken}) {
    window.fixtureReads.push(nextToken ?? null);
    const start = Number(nextToken || 0), size = 4;
    const items = automatic.slice(start, start + size);
    const next = start + items.length;
    return {items, nextToken: next < automatic.length ? String(next) : null, hasMore: next < automatic.length};
  }
  const decision = {decisionRelationId:'decision-0',decisionId:'prediction-0',label:'include',confidence:0.97,version:null,reviewRecommended:false,reviewReason:null,reviewDetail:null,classes:['include','exclude'],positiveLabel:'include',question:null,reviewControl:'thumbs',cyclotronId:'fixture-publication',decidedAt:null,provenance:null};
  return <NewsroomReferencesView references={references} loadAutoAccepted={loadAutoAccepted} onReview={save}
    decisions={params.has('decision')?new Map([['r0',decision]]):new Map()} />;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = `body{margin:0;font:16px sans-serif}button,textarea,select{font:inherit} [data-newsroom-list-row]{text-align:left;padding:12px;margin:4px} [data-radix-scroll-area-viewport]{max-height:75vh} [role=dialog]{position:fixed;inset:5vh 0 0;background:white;overflow:auto;z-index:60}`;

async function setup(options = "?status=auto-accepted", width = 1280) {
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

const list = (page: Page) => page.locator("[data-auto-accepted-list]");
const items = (page: Page) => page.locator("[data-auto-accepted-item]");
const itemIds = async (page: Page) => items(page).evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-auto-accepted-item")));
const settle = (page: Page) => page.evaluate(() => (window as unknown as { fixturePending: Array<() => void> }).fixturePending.splice(0).forEach((resolve) => resolve()));
const requests = (page: Page) => page.evaluate(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests);

const scenarios: Record<string, () => Promise<void>> = {
  /** ?status=auto-accepted opens the list on the filter, newest first, with the reason and the confidence under each card. */
  async opens_from_the_address() {
    const { browser, page, errors } = await setup("?status=auto-accepted&decision=1");
    try {
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      const tab = page.getByRole("tab", { name: /^Accepted automatically/ });
      assert.equal(await tab.getAttribute("aria-selected"), "true", "the filter is selected by the address");
      assert.equal(await tab.locator(".inline-flex, [data-slot=badge]").count(), 0, "no count: the Newsroom summary cannot keep one right");
      assert.deepEqual(await itemIds(page), ["r0", "r1", "r3", "r4"], "automatic acceptances only, newest first, one database page");
      assert.equal(await page.getByText(/Editor accepted/).count(), 0, "an editor's acceptance is never listed");
      const first = items(page).first();
      assert.match(await first.locator("[data-auto-accepted-by]").innerText(), /Accepted by the Cyclotron/);
      assert.match(await first.locator("[data-auto-accepted-confidence]").innerText(), /97% sure/, "the Cyclotron's own verdict, when the page has it");
      assert.match(await first.locator("[data-auto-accepted-reason]").innerText(), /learned from 42 editor votes/);
      const byRule = items(page).nth(1);
      assert.match(await byRule.locator("[data-auto-accepted-by]").innerText(), /monitor's rule/, "the reason tells a rule from the Cyclotron");
      assert.equal(await byRule.locator("[data-auto-accepted-confidence]").count(), 0, "a rule has no confidence");
      assert.equal(await items(page).nth(2).locator("[data-auto-accepted-confidence]").innerText().then((text) => /% sure/.test(text)), true, "confidence falls back to the reason's own words");
      assert.equal(await first.locator('[data-review-row="you"] [data-review-choice]').count(), 2, "the same Accept and Reject controls");
      assert.equal(await page.locator("[data-auto-accepted-list] select").count(), 0, "no dropdowns");
      assert.match(new URL(page.url()).search, /status=auto-accepted/);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Choosing the filter from the tabs writes the address; Show more reads the next database page and never repeats a card. */
  async pages_and_address() {
    const { browser, page, errors } = await setup("");
    try {
      await page.locator("[data-reference-view=list]").click();
      await page.getByRole("tab", { name: /^Accepted automatically/ }).click();
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      assert.match(new URL(page.url()).search, /status=auto-accepted/, "the address follows the filter");
      const firstPage = await itemIds(page);
      assert.equal(firstPage.length, 4);
      // Reaching the end of the list reads the next page by itself; the button is the same read for a reader who does not scroll.
      const grew = await page.waitForFunction(() => document.querySelectorAll("[data-auto-accepted-item]").length > 4, null, { timeout: 1500 }).then(() => true, () => false);
      // The button may be replaced by the automatic read while it is being tapped; either way the next page must arrive.
      if (!grew) await page.getByRole("button", { name: "Show more" }).click({ timeout: 1500 }).catch(() => undefined);
      await page.waitForFunction(() => document.querySelectorAll("[data-auto-accepted-item]").length > 4);
      const all = await itemIds(page);
      assert.equal(new Set(all).size, all.length, "no card twice");
      assert.deepEqual(all.slice(0, 4), firstPage, "earlier cards do not move");
      const reads = await page.evaluate(() => (window as unknown as { fixtureReads: unknown[] }).fixtureReads);
      assert.deepEqual(reads.slice(0, 2), [null, "4"], "one database page per read, from the newest end");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Reject asks for a reason in the same box as elsewhere, and a recorded Reject takes the card out of the list. */
  async reject_leaves_the_list() {
    const { browser, page, errors } = await setup();
    try {
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      const card = page.locator('[data-auto-accepted-item="r1"]');
      await card.locator('[data-review-choice="reject"]').click();
      await card.locator("[data-review-reason] textarea").waitFor();
      assert.equal(await card.locator("[data-review-reason] textarea").inputValue(), "", "the router's acceptance reason is not put in the editor's mouth");
      assert.match(await card.locator("[data-review-reason] label").innerText(), /required to reject/i, "a Reject needs words, as everywhere else");
      assert.equal(await card.locator("[data-review-record]").isDisabled(), true, "nothing is sent without a reason");
      assert.equal((await requests(page) as unknown[]).length, 0);
      await card.locator("[data-review-reason] textarea").fill("Off our beat.");
      await card.locator("[data-review-record]").click();
      await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 1);
      const [request] = await requests(page) as Array<{ referenceId: string; action: string; options: { note?: string } }>;
      assert.equal(request.action, "reject");
      assert.equal(request.referenceId, "r1-v1");
      assert.equal(request.options.note, "Off our beat.");
      await settle(page);
      await page.waitForFunction(() => !document.querySelector('[data-auto-accepted-item="r1"]'));
      assert.deepEqual(await itemIds(page), ["r0", "r3", "r4"], "the others stay where they were");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Accept confirms: the box is offered first and the explanation is optional. Recorded as the editor's own vote, and the card leaves the list. */
  async confirm_with_explanation() {
    const { browser, page, errors } = await setup();
    try {
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      const card = page.locator('[data-auto-accepted-item="r0"]');
      assert.equal(await card.locator('[data-review-choice="accept"]').getAttribute("aria-pressed"), "false", "an automatic acceptance is not yet the editor's answer");
      await card.locator('[data-review-choice="accept"]').click();
      await card.locator("[data-review-reason] textarea").waitFor();
      assert.equal(await card.locator("[data-review-reason] textarea").inputValue(), "", "the router's acceptance reason is not put in the editor's mouth");
      assert.doesNotMatch(await card.locator("[data-review-reason] label").innerText(), /required to accept/i, "no reason is required to Accept");
      assert.match(await card.locator("[data-review-reason] label").innerText(), /optional/i, "an Accept does not need words");
      assert.match(await card.locator("[data-feed-saved]").innerText(), /Say why if you like/);
      assert.equal(await card.locator("[data-review-record]").isDisabled(), false, "Record is available without words");
      assert.equal((await requests(page) as unknown[]).length, 0, "nothing is sent until the editor records it");
      await card.locator("[data-review-reason] textarea").fill("Exactly our beat.");
      await card.locator("[data-review-record]").click();
      await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 1);
      const [request] = await requests(page) as Array<{ referenceId: string; action: string; options: { note?: string } }>;
      assert.deepEqual([request.action, request.referenceId, request.options.note], ["accept", "r0-v1", "Exactly our beat."]);
      await settle(page);
      await page.waitForFunction(() => !document.querySelector('[data-auto-accepted-item="r0"]'));
      assert.deepEqual(await itemIds(page), ["r1", "r3", "r4"], "the others stay where they were");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Confirming without a word is allowed, and words typed before the tap go with it at once. */
  async confirm_without_explanation() {
    const { browser, page, errors } = await setup();
    try {
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      const card = page.locator('[data-auto-accepted-item="r0"]');
      await card.locator('[data-review-choice="accept"]').click();
      await card.locator("[data-review-record]").click();
      await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 1);
      const [first] = await requests(page) as Array<{ action: string; options: { note?: string } }>;
      assert.equal(first.action, "accept");
      assert.ok(!first.options.note, "no explanation sent, rather than an empty one");
      await settle(page);
      await page.waitForFunction(() => !document.querySelector('[data-auto-accepted-item="r0"]'));
      const typed = page.locator('[data-auto-accepted-item="r1"]');
      await typed.locator("[data-review-reason] textarea").fill("Fine.");
      await typed.locator('[data-review-choice="accept"]').click();
      await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 2);
      assert.equal(((await requests(page)) as Array<{ options: { note?: string } }>)[1].options.note, "Fine.", "words typed first go with the tap");
      await settle(page);
      await page.waitForFunction(() => !document.querySelector('[data-auto-accepted-item="r1"]'));
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The detail pane treats an automatic acceptance the same way as the card: Accept confirms, with the optional box. */
  async detail_matches_the_card() {
    const { browser, page, errors } = await setup();
    try {
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      await page.locator('[data-auto-accepted-item="r0"] [data-feed-open]').click();
      const detail = page.locator('[data-news-desk-reference-detail="r0"]:visible');
      await detail.waitFor();
      assert.equal(await detail.locator('[data-review-row="you"] [data-review-choice="accept"]').getAttribute("aria-pressed"), "false");
      await detail.locator('[data-review-row="you"] [data-review-choice="accept"]').click();
      assert.match(await detail.locator("[data-feed-saved]").innerText(), /Say why if you like/);
      assert.equal((await requests(page) as unknown[]).length, 0);
      await detail.locator("[data-review-record]").click();
      await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 1);
      assert.equal(((await requests(page)) as Array<{ action: string }>)[0].action, "accept");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async empty_state() {
    const { browser, page, errors } = await setup("?status=auto-accepted&empty=1");
    try {
      await page.locator("[data-auto-accepted-empty]").waitFor();
      assert.match(await page.locator("[data-auto-accepted-empty]").innerText(), /Nothing has been accepted automatically yet/);
      assert.equal(await items(page).count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone: nothing scrolls sideways, tap targets are large, and the icons are Lucide. */
  async phone() {
    const { browser, page, errors } = await setup("?status=auto-accepted&decision=1", 375);
    try {
      await page.locator('[data-auto-accepted-list="ready"]').waitFor();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "nothing scrolls sideways");
      const reject = items(page).first().locator('[data-review-choice="reject"]');
      assert.ok((await reject.boundingBox())!.height >= 40, "a large tap target");
      for (const icon of await list(page).locator("svg").all()) assert.ok(await icon.evaluate((svg) => [...svg.classList].some((name) => name.startsWith("lucide")) || svg.getAttribute("viewBox") === "0 0 24 24"), "icons are Lucide");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

export async function runAutoAcceptedListScenario(name: string) {
  assert.ok(scenarios[name], `Unknown auto-accepted list scenario: ${name}`);
  await scenarios[name]();
  console.log(`Auto-accepted list scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : Object.keys(scenarios)) await runAutoAcceptedListScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
