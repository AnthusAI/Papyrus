/** Fixture-only browser acceptance for star ratings on the real References view (PPY-3247f1). No production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://stars.test";
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
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "stars-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
// r0 pending and unrated, r1 pending with 2 stars, r2 accepted by an editor with 5 stars, r3 accepted automatically.
const rows = [0, 1, 2, 3].map((n) => ({
  id: 'r' + n + '-v1', lineageId: 'r' + n, versionState: 'current', versionNumber: 1, corpusId: 'fixture-corpus', externalItemId: 's' + n, title: 'Reference ' + n,
  sourceUri: 'https://example.test/' + n, importedAt: '2026-10-2' + n + 'T10:00:00Z',
  curationStatus: n >= 2 ? 'accepted' : 'pending',
  ...(n === 2 ? { curationActorKind: 'human', curationStatusUpdatedBy: 'editor@example.test', curationStatusUpdatedAt: '2026-11-01T10:00:00Z', starRating: 5, starRatedBy: 'editor@example.test', starRatedAt: '2026-11-01T10:00:00Z' } : {}),
  ...(n === 3 ? { curationActorKind: 'cyclotron', curationStatusUpdatedBy: 'auto:cyclotron', curationStatusUpdatedAt: '2026-11-01T11:00:00Z', curationStatusReason: 'Accepted automatically by the Cyclotron.' } : {}),
  ...(n === 1 ? { starRating: 2, starRatedBy: 'editor@example.test', starRatedAt: '2026-11-01T10:00:00Z' } : {}),
}));
window.fixtureStars = [];
window.fixtureVotes = [];
window.fixtureFailStars = false;
function Fixture() {
  const [references, setReferences] = useState(rows);
  async function review(reference, action) {
    window.fixtureVotes.push({ referenceId: reference.id, action });
    const status = { accept: 'accepted', reject: 'rejected', archive: 'archived' }[action];
    setReferences((current) => current.map((row) => row.lineageId === reference.lineageId ? { ...row, curationStatus: status, curationActorKind: 'human' } : row));
  }
  async function setStars(reference, stars) {
    window.fixtureStars.push({ referenceId: reference.id, stars });
    if (window.fixtureFailStars) throw new Error('The rating could not be saved.');
    setReferences((current) => current.map((row) => row.lineageId === reference.lineageId ? { ...row, starRating: stars, starRatedBy: stars === null ? null : 'editor@example.test',
      // The server accepts a pending Reference that is rated, as the same person; an accepted or rejected one keeps its status.
      ...(stars !== null && row.curationStatus === 'pending' ? { curationStatus: 'accepted', curationActorKind: 'human', curationStatusUpdatedBy: 'editor@example.test' } : {}) } : row));
  }
  return <NewsroomReferencesView references={references} onReview={review} onSetStars={setStars} />;
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
const filled = (page: Page, id: string) => card(page, id).locator("[data-star][data-filled]").count();
const starLog = (page: Page) => page.evaluate(() => (window as unknown as { fixtureStars: unknown[] }).fixtureStars);
const voteLog = (page: Page) => page.evaluate(() => (window as unknown as { fixtureVotes: unknown[] }).fixtureVotes);

const scenarios: Record<string, () => Promise<void>> = {
  /** One tap sets the rating, another tap on the same star clears it; filled and empty differ by shape; no dropdown. */
  async tap_sets_and_clears() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      assert.equal(await filled(page, "r0"), 0, "an unrated Reference shows five empty stars");
      assert.equal(await card(page, "r0").locator("[data-star]").count(), 5);
      await card(page, "r0").locator('[data-star="4"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r0"] [data-star-rating]')?.getAttribute("data-stars") === "4");
      assert.equal(await filled(page, "r0"), 4);
      assert.deepEqual(await starLog(page), [{ referenceId: "r0-v1", stars: 4 }]);
      const shapes = await card(page, "r0").locator("[data-star] svg").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("fill")));
      assert.deepEqual(shapes, ["currentColor", "currentColor", "currentColor", "currentColor", "none"], "filled versus outline by shape, not colour");
      assert.match(await card(page, "r0").locator("[data-star-rating-words]").innerText(), /4 of 5 stars/i, "the count is written as well");
      await card(page, "r0").locator('[data-star="4"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r0"] [data-star-rating]')?.getAttribute("data-stars") === "0");
      assert.deepEqual(await starLog(page), [{ referenceId: "r0-v1", stars: 4 }, { referenceId: "r0-v1", stars: null }], "the second tap clears");
      assert.equal(await page.locator("[data-star-rating] select").count(), 0, "no dropdowns");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Stars work with a vote in either order, need no reason, and never change the vote. */
  async with_a_vote_in_either_order() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      await card(page, "r0").locator('[data-star="5"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r0"] [data-star-rating]')?.getAttribute("data-stars") === "5");
      // Rating a pending Reference accepts it in the same action: no separate vote is sent from the page.
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r0"]')?.getAttribute("data-feed-rated") === "accept");
      assert.deepEqual(await voteLog(page), [], "the acceptance rides on the rating; the page sends no separate vote");
      assert.equal(await filled(page, "r0"), 5, "the accepted card keeps its stars");
      // The other order: vote first, then stars, with no reason typed.
      await card(page, "r1").locator('[data-review-choice="accept"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r1"]')?.getAttribute("data-feed-rated") === "accept");
      await card(page, "r1").locator('[data-star="3"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r1"] [data-star-rating]')?.getAttribute("data-stars") === "3");
      assert.equal(await card(page, "r1").getAttribute("data-feed-rated"), "accept");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A tap lights that star and every star to its left, in every position, by shape and by the written count. */
  async stars_fill_to_the_left() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      for (const tapped of [2, 5, 3]) {
        await card(page, "r0").locator(`[data-star="${tapped}"]`).click();
        await page.waitForFunction((n) => document.querySelector('[data-feed-card="r0"] [data-star-rating]')?.getAttribute("data-stars") === String(n), tapped);
        const shapes = await card(page, "r0").locator("[data-star] svg").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("fill")));
        assert.deepEqual(shapes, [1, 2, 3, 4, 5].map((n) => (n <= tapped ? "currentColor" : "none")), `star ${tapped} lights itself and every star to its left`);
        assert.match(await card(page, "r0").locator("[data-star-rating-words]").innerText(), new RegExp(`${tapped} of 5 stars`, "i"));
      }
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A rating that already exists is shown, on the card of a Reference an editor accepted and on one the Cyclotron accepted. */
  async shows_what_is_saved() {
    const { browser, page, errors } = await setup();
    try {
      await includeRated(page);
      await card(page, "r2").waitFor();
      assert.equal(await filled(page, "r2"), 5);
      assert.equal(await filled(page, "r1"), 2);
      assert.equal(await filled(page, "r3"), 0, "an automatic acceptance can be rated too");
      await card(page, "r3").locator('[data-star="1"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r3"] [data-star-rating]')?.getAttribute("data-stars") === "1");
      assert.equal(await card(page, "r3").locator('[data-review-choice][aria-pressed="true"]').count(), 0, "rating the automatic acceptance does not confirm it");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The list shows a small solid star and the number; the detail pane has the control and stays in step with the card. */
  async list_and_detail() {
    const { browser, page, errors } = await setup();
    try {
      await includeRated(page);
      await card(page, "r2").waitFor();
      await card(page, "r2").locator("[data-feed-open]").click();
      const detail = page.locator("[data-newsroom-list-detail-shell] [data-star-rating]");
      await detail.waitFor();
      assert.equal(await detail.getAttribute("data-stars"), "5", "the detail shows the saved rating");
      await detail.locator('[data-star="2"]').click();
      await page.waitForFunction(() => document.querySelector('[data-feed-card="r2"] [data-star-rating]')?.getAttribute("data-stars") === "2");
      assert.equal(await filled(page, "r2"), 2, "the card follows what was set in the detail");
      await page.locator("[data-reference-view=list]").click();
      await page.getByRole("tab", { name: /^All/ }).click();
      const row = page.locator('[data-newsroom-card-id="r2"]');
      await row.waitFor();
      assert.equal(await row.locator("[data-stars-mark]").getAttribute("data-stars-mark"), "2");
      assert.equal(await page.locator('[data-newsroom-card-id="r0"] [data-stars-mark]').count(), 0, "an unrated row shows none");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A failed save says so, keeps the vote, and the card goes back to the saved rating. */
  async a_failed_save_is_said() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "r0").waitFor();
      await page.evaluate(() => { (window as unknown as { fixtureFailStars: boolean }).fixtureFailStars = true; });
      await card(page, "r0").locator('[data-star="3"]').click();
      await card(page, "r0").getByRole("alert").waitFor();
      assert.match(await card(page, "r0").getByRole("alert").innerText(), /could not be saved/);
      assert.equal(await filled(page, "r0"), 0, "back to what is saved");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone: five large targets in one row, nothing scrolls sideways, every icon is Lucide. */
  async phone() {
    const { browser, page, errors } = await setup("", 375);
    try {
      await card(page, "r0").waitFor();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "nothing scrolls sideways");
      const boxes = await card(page, "r0").locator("[data-star]").evaluateAll((nodes) => nodes.map((node) => { const box = node.getBoundingClientRect(); return { height: box.height, width: box.width, top: Math.round(box.top) }; }));
      assert.ok(boxes.every((box) => box.height >= 40 && box.width >= 40), "large tap targets");
      assert.equal(new Set(boxes.map((box) => box.top)).size, 1, "one row");
      for (const icon of await card(page, "r0").locator("[data-star-rating] svg").all()) assert.ok(await icon.evaluate((svg) => [...svg.classList].some((name) => name.startsWith("lucide"))), "Lucide icons only");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

export async function runReferenceStarsScenario(name: string) {
  assert.ok(scenarios[name], `Unknown reference stars scenario: ${name}`);
  await scenarios[name]();
  console.log(`Reference stars scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : Object.keys(scenarios)) await runReferenceStarsScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
