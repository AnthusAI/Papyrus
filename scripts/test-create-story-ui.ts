/** Fixture-only browser acceptance for Create Story on the real References view (PPY-3c11bd). The local preview backend builds the draft; no production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://create-story.test";
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
        ? "import {useSyncExternalStore} from 'react'; const subscribe = (notify) => {window.addEventListener('popstate',notify);return () => window.removeEventListener('popstate',notify);}; export const usePathname = () => useSyncExternalStore(subscribe,() => window.location.pathname); export const useRouter = () => ({ push: (href) => { (window.fixturePushed ||= []).push(href); }, replace: () => {} }); export const useSearchParams = () => new URLSearchParams(window.location.search);"
        : "export const loadReferenceAttachmentsForLineageId = async () => []; export const loadStoragePathUrl = async () => ({url:null}); export const loadStoragePathText = async () => ({text:null,error:null}); export const loadModelPayloadsForOwner = async () => []; export const uploadModelPayloadForOwner = async () => ({ id: \"upload\" });", loader: "js", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "create-story-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
// r0 pending, r1 rejected, r2 accepted by an editor, r3 pending, r4 accepted automatically.
const status = ['pending', 'rejected', 'accepted', 'pending', 'accepted'];
const rows = status.map((curationStatus, n) => ({
  id: 'r' + n + '-v1', lineageId: 'r' + n, versionState: 'current', versionNumber: 1, corpusId: 'fixture-corpus', externalItemId: 's' + n, title: 'Reference ' + n,
  sourceUri: 'https://example.test/' + n, importedAt: '2026-10-2' + n + 'T10:00:00Z', curationStatus,
  ...(curationStatus !== 'pending' && n !== 4 ? { curationActorKind: 'human', curationStatusUpdatedBy: 'editor@example.test', curationStatusUpdatedAt: '2026-11-01T10:00:00Z' } : {}),
  ...(n === 4 ? { curationActorKind: 'cyclotron', curationStatusUpdatedBy: 'auto:cyclotron', curationStatusUpdatedAt: '2026-11-01T11:00:00Z', curationStatusReason: 'Accepted automatically by the Cyclotron.' } : {}),
}));
window.fixtureVotes = [];
window.fixturePushed = [];
function Fixture() {
  const [references, setReferences] = useState(rows);
  async function review(reference, action, options = {}) {
    window.fixtureVotes.push({ referenceId: reference.id, action, reason: options.note ?? null });
    const next = { accept: 'accepted', reject: 'rejected', archive: 'archived' }[action];
    setReferences((current) => current.map((row) => row.lineageId === reference.lineageId ? { ...row, curationStatus: next, curationActorKind: 'human' } : row));
  }
  return <NewsroomReferencesView demo references={references} onReview={review} />;
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

const card = (page: Page, id: string) => page.locator(`[data-feed-card="${id}"]`);
const includeRated = async (page: Page) => { await page.locator('[data-feed-show-button="all"]').click(); };
const votes = (page: Page) => page.evaluate(() => (window as unknown as { fixtureVotes: unknown[] }).fixtureVotes);
const pushed = (page: Page) => page.evaluate(() => (window as unknown as { fixturePushed: string[] }).fixturePushed);

const scenarios: Record<string, () => Promise<void>> = {
  /** One tap on a pending Reference makes the Story, records the editor's Accept with no reason, and opens the Story. */
  async one_tap_on_a_pending_reference() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      assert.match(await card(page, "r0").locator("[data-create-story-note]").innerText(), /accepts this reference/i, "the button says it also accepts");
      await card(page, "r0").locator("[data-create-story-button]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      assert.match((await pushed(page))[0]!, /\/newsroom\/articles\/demo-article-new-1/, "the Story opens in the article editor");
      assert.deepEqual(await votes(page), [{ referenceId: "r0-v1", action: "accept", reason: null }], "the editor's Accept, no reason asked");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A rejected Reference says so on the button, and creating a Story does not overturn the vote. */
  async a_rejected_reference_stays_rejected() {
    const { browser, page, errors } = await setup();
    try {
      await includeRated(page);
      await card(page, "r1").waitFor();
      assert.match(await card(page, "r1").locator("[data-create-story-note]").innerText(), /rejected\. its vote stays/i);
      await card(page, "r1").locator("[data-create-story-button]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      assert.deepEqual(await votes(page), [], "no vote was recorded");
      assert.equal(await card(page, "r1").getAttribute("data-feed-rated"), "reject");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** An accepted Reference makes a Story without a second vote and without a note. */
  async an_accepted_reference() {
    const { browser, page, errors } = await setup();
    try {
      await includeRated(page);
      await card(page, "r2").waitFor();
      assert.equal(await card(page, "r2").locator("[data-create-story-note]").count(), 0, "nothing to explain");
      await card(page, "r2").locator("[data-create-story-button]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      assert.deepEqual(await votes(page), []);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A second tap offers the existing Story instead of making a duplicate; Create another is a deliberate choice. */
  async a_second_tap_offers_the_existing_story() {
    const { browser, page, errors } = await setup();
    try {
      await includeRated(page);
      await card(page, "r2").waitFor();
      const button = card(page, "r2").locator("[data-create-story-button]");
      await button.click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      await button.click();
      const offered = card(page, "r2").locator("[data-create-story-existing]");
      await offered.waitFor();
      assert.equal((await pushed(page)).length, 1, "no second Story and no second navigation");
      assert.equal(await offered.locator("[data-create-story-open]").count(), 1, "the existing Story is offered");
      await offered.locator("[data-create-story-another]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 2);
      assert.notEqual((await pushed(page))[0], (await pushed(page))[1], "the second Story has its own address");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** An automatic acceptance is confirmed as the editor's own vote, with no reason asked. */
  async an_automatic_acceptance_is_confirmed() {
    const { browser, page, errors } = await setup();
    try {
      await includeRated(page);
      await card(page, "r4").waitFor();
      assert.match(await card(page, "r4").locator("[data-create-story-note]").innerText(), /confirms the automatic acceptance/i);
      await card(page, "r4").locator("[data-create-story-button]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      assert.deepEqual(await votes(page), [{ referenceId: "r4-v1", action: "accept", reason: null }]);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The post is one more button beside it, never a dialog or a dropdown; Lucide icons only. */
  async a_post_without_a_dialog() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      assert.equal(await card(page, "r0").locator("[data-create-story] select, [role=dialog]").count(), 0);
      await card(page, "r0").locator("[data-create-story-post]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      assert.equal(await page.locator("[role=dialog]").count(), 0, "no dialog");
      for (const icon of await card(page, "r3").locator("[data-create-story] svg").all()) assert.ok(await icon.evaluate((svg) => [...svg.classList].some((name) => name.startsWith("lucide"))), "Lucide icons only");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The detail pane has the same action. */
  async the_detail_pane_has_it() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      await card(page, "r0").locator("[data-feed-open]").click();
      const detail = page.locator("[data-newsroom-list-detail-shell] [data-create-story]");
      await detail.waitFor();
      await detail.locator("[data-create-story-button]").click();
      await page.waitForFunction(() => ((window as unknown as { fixturePushed: string[] }).fixturePushed ?? []).length === 1);
      assert.deepEqual(await votes(page), [{ referenceId: "r0-v1", action: "accept", reason: null }]);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone: a large target, nothing scrolls sideways. */
  async phone() {
    const { browser, page, errors } = await setup("", 375);
    try {
      await card(page, "r0").waitFor();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "nothing scrolls sideways");
      const box = (await card(page, "r0").locator("[data-create-story-button]").boundingBox())!;
      assert.ok(box.height >= 40 && box.width >= 120, "a large tap target");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

export async function runCreateStoryScenario(name: string) {
  assert.ok(scenarios[name], `Unknown Create Story scenario: ${name}`);
  await scenarios[name]();
  console.log(`Create Story scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : Object.keys(scenarios)) await runCreateStoryScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
