/** Fixture-only browser acceptance for the real References view. No production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://reference-review.test";
let bundle: Promise<string> | undefined;
let tailwindCss: Promise<string> | undefined;

/** The real Tailwind build of app/tailwind.css, so sizes and breakpoints are the shipped ones. */
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
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "reference-review-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
const fixture = [
  {id:'reference-a-v1',lineageId:'reference-a',versionState:'current',versionNumber:1,corpusId:'fixture-corpus',externalItemId:'source-a',title:'Pending reference A',sourceUri:'https://example.org/source-a',curationStatus:'pending',importedAt:'2026-10-22T10:00:00Z'},
  {id:'reference-b-v1',lineageId:'reference-b',versionState:'current',versionNumber:1,corpusId:'fixture-corpus',externalItemId:'source-b',title:'Pending reference B',sourceUri:'https://example.org/source-b',curationStatus:'pending',importedAt:'2026-10-21T10:00:00Z'},
  {id:'reference-c-v1',lineageId:'reference-c',versionState:'current',versionNumber:1,corpusId:'fixture-corpus',externalItemId:'source-c',title:'Pending reference C',sourceUri:'https://example.org/source-c',curationStatus:'pending',importedAt:'2026-10-20T10:00:00Z'}
];
const fixtureOptions = sessionStorage.getItem('fixtureOptions') ?? location.search;
sessionStorage.setItem('fixtureOptions',fixtureOptions);
const params = new URLSearchParams(fixtureOptions);
const initialReferenceLineageId = location.pathname.split('/')[3] || null;
window.fixtureRequests = [];
window.fixturePending = [];
window.fixtureFailNext = false;
function Fixture() {
  const [references,setReferences] = useState(() => JSON.parse(localStorage.getItem('references') || 'null') || (params.has('empty') ? [] : fixture));
  // The production reason code belongs to curation Message metadata, not Reference.metadata.
  const [reviewReasons,setReviewReasons] = useState(() => new Map(JSON.parse(localStorage.getItem('reviewReasons') || '[]')));
  const [reviewSectionIds,setReviewSectionIds] = useState(() => new Map(JSON.parse(localStorage.getItem('reviewSectionIds') || '[]')));
  const [predictionState,setPredictionState] = useState(params.get('predictions') || 'ready');
  window.fixtureRefresh = (note,reason) => {
    setReferences(current => current.map(row => row.lineageId==='reference-a'?{...row,curationStatusReason:note}:row));
    setReviewReasons(current => new Map([...current,['reference-a',reason]]));
  };
  const decision = {decisionRelationId:'decision-a',decisionId:'prediction-a',label:'include',confidence:0.79,version:null,reviewRecommended:true,reviewReason:'program',reviewDetail:'Fixture review request',classes:['include','exclude'],positiveLabel:'include',question:null,reviewControl:'thumbs',cyclotronId:'fixture-publication',decidedAt:null,provenance:null};
  const section = {decisionRelationId:'section-a',cyclotronId:'fixture-internal',sectionId:'fixture-section',confidence:0.73,probabilities:[{sectionId:'fixture-section',probability:0.73}],decidedAt:null};
  async function save(reference,action,options={}) {
    window.fixtureRequests.push({referenceId:reference.id,action,options});
    await new Promise((resolve) => window.fixturePending.push(resolve));
    if(window.fixtureFailNext) {window.fixtureFailNext=false;throw new Error('Fixture write failed. Try again.');}
    const status = {accept:'accepted',reject:'rejected',archive:'archived'}[action];
    setReferences(current => {
      const next = current.map(row => row.lineageId === reference.lineageId ? {...row,curationStatus:status,curationStatusReason:options.note?.trim() || null} : row);
      localStorage.setItem('references',JSON.stringify(next));
      return next;
    });
    setReviewReasons(current => {
      const next = new Map(current);
      if(action==='reject') next.set(reference.lineageId,options.reasonCode);
      else next.delete(reference.lineageId);
      localStorage.setItem('reviewReasons',JSON.stringify([...next]));
      return next;
    });
    setReviewSectionIds(current => {
      const next = new Map(current);
      if(action==='accept' && options.sectionId) next.set(reference.lineageId,options.sectionId);
      else next.delete(reference.lineageId);
      localStorage.setItem('reviewSectionIds',JSON.stringify([...next]));
      return next;
    });
  }
  return <NewsroomReferencesView references={references} reviewReasons={reviewReasons} reviewSectionIds={reviewSectionIds} initialReferenceLineageId={initialReferenceLineageId} disabled={params.has('readonly')}
    decisions={params.has('decision')?new Map([['reference-a',decision]]):new Map()}
    sections={params.has('decision')?[{id:'fixture-section',title:'Fixture Section'}]:[]}
    sectionSuggestions={params.has('decision')?new Map([['reference-a',section]]):new Map()}
    predictionState={predictionState} predictionError={predictionState==='error'?'Fixture prediction service unavailable':null}
    onRetryPredictions={() => setPredictionState('ready')}
    onReview={save} />;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = `body{margin:0;font:16px sans-serif}button,textarea,select{font:inherit} [data-newsroom-list-detail-shell]{display:flex} [data-news-desk-reference-detail]{padding:8px} [data-newsroom-card-grid]{display:flex;flex-direction:column} [data-newsroom-list-row]{text-align:left;padding:12px;margin:4px} [data-radix-scroll-area-viewport]{max-height:75vh} [role=dialog]{position:fixed;inset:5vh 0 0;background:white;overflow:auto;z-index:60} @media(max-width:767px){[data-newsroom-list-detail-shell]{display:none}}`;

async function setup(options = "", width = 1280) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(2500);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    const history = url.searchParams.has("deep-link") ? `<script>history.replaceState(null,"","/newsroom/references");history.pushState(null,"","/newsroom/references/reference-a");</script>` : "";
    return route.fulfill({ contentType: "text/html", body: `<html><head><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root"></div>${history}<script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom/references${options}`);
  // The page opens as a feed; these scenarios are about the list and queue, one tap away.
  const toggle = page.locator("[data-reference-view=list]");
  await toggle.waitFor();
  await toggle.click();
  return { browser, page, errors };
}

const detail = (page: Page) => page.locator('[data-news-desk-reference-detail="reference-a"]:visible');
async function selectA(page: Page) {
  await page.locator('[data-newsroom-card-id="reference-a"]').click();
  await detail(page).waitFor();
  assert.ok(page.url().includes("/references/reference-a"), "selection has a refreshable detail URL");
}
async function settle(page: Page, fail = false) {
  await page.evaluate((shouldFail) => {
    const fixture = window as unknown as { fixtureFailNext: boolean; fixturePending: Array<() => void> };
    fixture.fixtureFailNext = shouldFail;
    fixture.fixturePending.splice(0).forEach((resolve) => resolve());
  }, fail);
}
async function requestCount(page: Page) {
  return page.evaluate(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length);
}
/** What the view last asked the curation mutation for: the action and the reason it carries. */
async function lastRequest(page: Page) {
  return page.evaluate(() => {
    const requests = (window as unknown as { fixtureRequests: Array<{ action: string; options: { note?: string; reasonCode?: string | null } }> }).fixtureRequests;
    const last = requests[requests.length - 1];
    return { action: last.action, note: last.options.note ?? null, reasonCode: last.options.reasonCode ?? null };
  });
}
async function status(page: Page, expected: string) {
  await page.waitForFunction((value) => document.querySelector('[data-news-desk-reference-detail="reference-a"] [data-reference-curation-status]')?.getAttribute("data-reference-curation-status") === value, expected);
}
async function openSectionPlacement(page: Page) {
  const summary = detail(page).getByText("Section placement (optional)", { exact: true });
  if (!await summary.evaluate((element) => element.parentElement?.hasAttribute("open"))) await summary.click();
}

/** The reason field, now inside the decision control rather than a labelled box on the card. */
const WHY = "[data-review-reason] textarea";
const you = (page: Page, choice: "accept" | "reject") => detail(page).locator(`[data-review-row="you"] [data-review-choice="${choice}"]`);
const reasonChip = (page: Page, code: string) => detail(page).locator(`[data-review-reason="${code}"]`);
async function swipe(page: Page, from: number, to: number) {
  await page.evaluate(`(() => {
    const target = [...document.querySelectorAll("[data-review-gestures]")].find((e) => e.offsetParent);
    const fire = (type, x) => target.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerType: "touch", clientX: x, clientY: 300 }));
    fire("pointerdown", ${from}); fire("pointerup", ${to});
  })()`);
}
const barText = (page: Page) => page.locator("[data-review-queue-position]:visible").innerText();
const openId = (page: Page) => new URL(page.url()).pathname.split("/").pop();

const scenarios: Record<string, () => Promise<void>> = {
  async selection() {
    for (const width of [1280, 375]) {
      const { browser, page, errors } = await setup("", width);
      try {
        await selectA(page);
        const text = await detail(page).innerText();
        assert.match(text, /no prediction/i);
        assert.ok(!/Agree|Overrule|agreed/i.test(text), "one vocabulary: Accept and Reject only");
        for (const choice of ["accept", "reject"] as const) {
          assert.equal(await you(page, choice).getAttribute("aria-disabled"), null, "controls are never silently disabled");
          assert.ok((await you(page, choice).boundingBox())!.height >= 48, "large tap target");
        }
        assert.equal(await detail(page).locator("select").count(), 0, "no dropdowns");
        if (width === 1280) {
          await detail(page).locator(WHY).fill("Keep my pending draft while filtering.");
          await page.getByRole("tab", { name: /^All/ }).click();
          await detail(page).waitFor();
          assert.equal(await detail(page).locator(WHY).inputValue(), "Keep my pending draft while filtering.");
          await page.getByRole("tab", { name: /^Pending/ }).click();
          await detail(page).waitFor();
          assert.ok(new URL(page.url()).pathname.endsWith("/reference-a"), "filter changes preserve the detail route");
          await page.locator('[data-newsroom-card-id="reference-b"]').click();
          await page.locator('[data-news-desk-reference-detail="reference-b"]:visible').waitFor();
          await page.goBack();
          await detail(page).waitFor();
          await page.goBack();
          await page.waitForFunction(() => !document.querySelector('[data-news-desk-reference-detail]'));
          assert.equal(new URL(page.url()).pathname, "/newsroom/references");
        }
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
    const { browser, page, errors } = await setup("?deep-link=1");
    try {
      await detail(page).waitFor();
      await page.locator('[data-newsroom-card-id="reference-b"]').click();
      await page.locator('[data-news-desk-reference-detail="reference-b"]:visible').waitFor();
      await page.goBack(); await detail(page).waitFor();
      await page.goBack();
      await page.waitForFunction(() => !document.querySelector('[data-news-desk-reference-detail]'));
      assert.equal(new URL(page.url()).pathname, "/newsroom/references", "the original deep-link prop does not pin a reference after Back");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async feedback() {
    const { browser, page, errors } = await setup();
    try {
      await selectA(page);
      const panel = detail(page);
      await you(page, "accept").click();
      assert.equal(await requestCount(page), 1);
      await panel.getByText("Saving…").waitFor();
      await settle(page); await status(page, "accepted");
      await panel.locator("[data-review-saved]").waitFor();
      assert.equal(await you(page, "accept").getAttribute("aria-pressed"), "true");
      await you(page, "accept").click();
      assert.equal(await you(page, "accept").getAttribute("aria-pressed"), "true", "tapping the selected answer never unselects it");
      assert.equal(await requestCount(page), 1, "re-tapping the selected answer sends nothing");
      await panel.locator(WHY).fill("A useful source for the publication.");
      await panel.locator(WHY).blur();
      await settle(page);
      await page.waitForFunction(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.curationStatusReason === "A useful source for the publication.");
      await page.reload(); await detail(page).waitFor();
      assert.equal(await detail(page).locator(WHY).inputValue(), "A useful source for the publication.");
      // Switching to Reject with a Why already written saves at once: a typed reason is a reason. It carries
      // no code the editor did not pick — the curation Lambda reads the words for the code they name.
      const before = await requestCount(page);
      await you(page, "reject").click();
      assert.equal(await you(page, "reject").getAttribute("aria-pressed"), "true", "the tapped answer shows as selected at once");
      await settle(page); await status(page, "rejected");
      assert.ok(await requestCount(page) > before, "the Reject is sent without waiting for a chip");
      assert.equal(await detail(page).getByText("Choose a reason, or say why above, to save your Reject.").count(), 0, "nothing asks for a reason");
      assert.deepEqual(await lastRequest(page), { action: "reject", note: "A useful source for the publication.", reasonCode: null },
        "the words go with the Reject and no reason code is invented for them");
      // A chip still refines the reason: a second save, sent once the first one lands.
      const sent = await requestCount(page);
      await reasonChip(page, "out_of_scope").click();
      await settle(page); await page.waitForFunction((count) => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length > count, sent); await settle(page);
      await status(page, "rejected");
      await page.reload(); await detail(page).waitFor(); await status(page, "rejected");
      assert.equal(await reasonChip(page, "out_of_scope").getAttribute("aria-pressed"), "true");
      assert.equal(await you(page, "reject").getAttribute("aria-pressed"), "true");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async recovery() {
    const { browser, page, errors } = await setup();
    try {
      await selectA(page);
      const panel = detail(page);
      await panel.locator(WHY).fill("Keep my explanation on failure.");
      await you(page, "accept").dblclick();
      assert.equal(await requestCount(page), 1, "a double click starts one mutation");
      await settle(page, true);
      await panel.getByRole("alert").filter({ hasText: "Fixture write failed" }).waitFor();
      await status(page, "pending");
      assert.equal(await panel.locator(WHY).inputValue(), "Keep my explanation on failure.");
      assert.equal(await you(page, "accept").getAttribute("aria-pressed"), "false", "a failed save does not show as the answer");
      await you(page, "accept").click(); await settle(page); await status(page, "accepted");
      assert.equal(await requestCount(page), 2);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async revision_from_message() {
    const { browser, page, errors } = await setup();
    try {
      await selectA(page);
      await detail(page).locator(WHY).fill("The source addresses a different audience.");
      await you(page, "reject").click();   // with a Why typed, this saves at once, carrying the words and no code
      await reasonChip(page, "out_of_scope").click();   // and the chip refines it once that lands
      await settle(page); await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 2); await settle(page);
      await status(page, "rejected");
      await page.reload(); await detail(page).waitFor(); await status(page, "rejected");
      assert.equal(await reasonChip(page, "out_of_scope").getAttribute("aria-pressed"), "true", "reason is loaded from the persisted curation Message");
      assert.equal(await detail(page).locator(WHY).inputValue(), "The source addresses a different audience.");
      await detail(page).locator(WHY).fill("");
      await detail(page).locator(WHY).blur();
      assert.equal(await requestCount(page), 1, "clearing the note saves without reselecting the persisted reason");
      await settle(page);
      await page.waitForFunction(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.curationStatusReason === null);
      await page.evaluate(() => (window as unknown as {fixtureRefresh: (note: string, reason: string) => void}).fixtureRefresh("Latest saved explanation.", "policy_exclusion"));
      await page.waitForFunction(() => (document.querySelector('textarea') as HTMLTextAreaElement)?.value === "Latest saved explanation.");
      assert.equal(await reasonChip(page, "policy_exclusion").getAttribute("aria-pressed"), "true", "untouched feedback follows live message updates");
      await detail(page).locator(WHY).fill("My unsaved draft.");
      await page.evaluate(() => (window as unknown as {fixtureRefresh: (note: string, reason: string) => void}).fixtureRefresh("Another editor saved this.", "unavailable"));
      assert.equal(await detail(page).locator(WHY).inputValue(), "My unsaved draft.", "live updates preserve a dirty draft");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async predictions() {
    const { browser, page, errors } = await setup("?decision=1");
    try {
      await selectA(page);
      const cyclotron = detail(page).locator("[data-decision-control]");
      assert.match(await cyclotron.locator("[data-review-choice][data-predicted]").innerText().then((t) => t.replace(/\s+/g, " ").trim()), /^accept predicted$/i);
      assert.equal(await cyclotron.locator("[data-confidence-value]").innerText(), "79%", "the confidence is in the bar");
      assert.equal(await cyclotron.locator("[data-verdict]").count(), 0, "no verdict before the human answers");
      await you(page, "accept").click(); await settle(page); await status(page, "accepted");
      const match = cyclotron.locator('[data-verdict="match"]');
      await match.waitFor();
      assert.ok(await match.locator("svg").count() === 1, "a match carries an icon, not colour alone");
      assert.match(await match.innerText(), /matches your answer/);
      await you(page, "reject").click(); await reasonChip(page, "out_of_scope").click(); await settle(page);
      await status(page, "rejected");
      const miss = cyclotron.locator('[data-verdict="miss"]');
      await miss.waitFor();
      assert.ok(await miss.locator("svg").count() === 1);
      assert.match(await miss.innerText(), /differs from your answer/);
      assert.ok(!/0%|100%|version 0/.test(await detail(page).innerText()), "missing confidence and version are never fabricated");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
    for (const via of ["button", "key"]) {
      const { browser: sectionBrowser, page: sectionPage, errors: sectionErrors } = await setup("?decision=1");
      try {
        await selectA(sectionPage);
        await openSectionPlacement(sectionPage);
        await detail(sectionPage).getByRole("radio", { name: /Fixture Section/ }).check();
        if (via === "button") await you(sectionPage, "accept").click();
        else { await sectionPage.locator("body").click({ position: { x: 2, y: 2 } }); await sectionPage.keyboard.press("a"); }
        const requests = await sectionPage.evaluate(() => (window as unknown as {fixtureRequests:Array<{options:{sectionId?:string}}>} ).fixtureRequests);
        assert.equal(requests[0]?.options.sectionId, "fixture-section", `${via} keeps the editor's selected Section`);
        await settle(sectionPage); await status(sectionPage, "accepted");
        await sectionPage.reload(); await detail(sectionPage).waitFor();
        await openSectionPlacement(sectionPage);
        assert.equal(await detail(sectionPage).getByRole("radio", { name: /Fixture Section/ }).isChecked(), true, "the recorded choice survives a page load");
        assert.deepEqual(sectionErrors, []);
      } finally { await sectionBrowser.close(); }
    }
  },
  async prediction_loading() {
    const { browser, page, errors } = await setup("?predictions=loading");
    try {
      await selectA(page);
      await page.getByText(/Loading predictions/i).waitFor();
      await detail(page).locator('[data-prediction-state="loading"]').waitFor();
      assert.match(await detail(page).locator("[data-prediction-caption]").innerText(), /reading the prediction/i);
      assert.equal(await you(page, "accept").getAttribute("aria-disabled"), null);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async prediction_failure() {
    const { browser, page, errors } = await setup("?predictions=error");
    try {
      await selectA(page);
      await page.getByText(/Predictions unavailable/i).waitFor();
      assert.ok(!/no prediction$/im.test(await detail(page).innerText()), "failed reads are not reported as missing data");
      await page.getByRole("button", { name: "Retry predictions", exact: true }).click();
      await detail(page).locator('[data-prediction-state="none"]').waitFor();
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async readonly() {
    const { browser, page, errors } = await setup("?readonly=1");
    try {
      await selectA(page);
      await detail(page).locator("[data-review-disabled-reason]").waitFor();
      assert.match(await detail(page).innerText(), /Editor access is required/);
      assert.equal(await you(page, "accept").getAttribute("aria-disabled"), "true");
      await you(page, "accept").dispatchEvent("click");
      await you(page, "reject").dispatchEvent("click");
      assert.equal(await requestCount(page), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async queue() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup("", width);
      try {
        await selectA(page);
        const bar = page.locator("[data-review-queue-bar]:visible");
        await bar.waitFor();
        assert.equal(await barText(page), "1 of 3");
        await page.waitForFunction(`(() => { const b=[...document.querySelectorAll("[data-review-queue-bar]")].find((e)=>e.getBoundingClientRect().width>0); const r=b.getBoundingClientRect(); return r.bottom <= innerHeight + 1 && r.top > innerHeight * 0.4; })()`);
        const box = (await bar.boundingBox())!;
        assert.ok(box.y + box.height <= 900 + 1 && box.y > 400, `the bar sits at the bottom, within thumb reach (y=${box.y} h=${box.height})`);
        const next = bar.getByRole("button", { name: "Next", exact: true });
        assert.ok((await next.boundingBox())!.height >= 44, "large Next target");
        await next.click();
        await page.locator('[data-news-desk-reference-detail="reference-b"]:visible').waitFor();
        assert.equal(openId(page), "reference-b", "one URL per item");
        assert.equal(await barText(page), "2 of 3");
        await bar.getByRole("button", { name: "Previous", exact: true }).click();
        await detail(page).waitFor();
        assert.equal(await barText(page), "1 of 3");
        await swipe(page, 300, 100); // swipe left: Next
        await page.locator('[data-news-desk-reference-detail="reference-b"]:visible').waitFor();
        await swipe(page, 100, 300); // swipe right: Previous
        await detail(page).waitFor();
        if (width === 1440) {
          await page.locator("body").click({ position: { x: 2, y: 2 } });
          await page.keyboard.press("ArrowRight");
          await page.locator('[data-news-desk-reference-detail="reference-b"]:visible').waitFor();
          await page.keyboard.press("ArrowLeft");
          await detail(page).waitFor();
        }
        // Decide, then move on: the decided item keeps its place until the editor moves.
        await you(page, "accept").click(); await settle(page); await status(page, "accepted");
        assert.equal(await barText(page), "1 of 3");
        await bar.getByRole("button", { name: "Next", exact: true }).click();
        await page.locator('[data-news-desk-reference-detail="reference-b"]:visible').waitFor();
        assert.equal(await barText(page), "1 of 2", "decided items leave the pending queue");
        await bar.getByRole("button", { name: "Next", exact: true }).click();
        await page.locator('[data-news-desk-reference-detail="reference-c"]:visible').waitFor();
        await bar.getByRole("button", { name: "Next", exact: true }).click();
        await page.locator("[data-review-caught-up]:visible").waitFor();
        assert.match(await page.locator("[data-review-caught-up]:visible").innerText(), /All caught up/);
        await bar.getByRole("button", { name: "Previous", exact: true }).click();
        await page.locator('[data-news-desk-reference-detail="reference-c"]:visible').waitFor();
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
  async card_layout() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup("?decision=1", width);
      try {
        await selectA(page);
        const rows = await page.evaluate(`(() => {
          const panel = [...document.querySelectorAll("[data-review-card]")].find((e) => e.offsetParent);
          const top = (sel) => panel.querySelector(sel).getBoundingClientRect().top;
          return { root: panel.getBoundingClientRect().width, cyclotron: top("[data-confidence-bar]"), you: top('[data-review-row="you"]'), why: panel.querySelector("textarea").getBoundingClientRect().width, scrollX: document.documentElement.scrollWidth - innerWidth };
        })()`) as { root: number; cyclotron: number; you: number; why: number; scrollX: number };
        assert.ok(rows.cyclotron < rows.you, "the prediction bar sits above the buttons");
        assert.ok(rows.why >= rows.root - 2, "the Why textarea spans the card");
        assert.ok(rows.scrollX <= 0, "no horizontal page scroll");
        // One control: the bar above the two buttons, and the buttons and the reason field in the same column.
        const control = await page.evaluate(`(() => {
          const panel = [...document.querySelectorAll("[data-review-card]")].find((e) => e.offsetParent);
          const box = (sel) => { const r = panel.querySelector(sel).getBoundingClientRect(); return { x: r.x, w: r.width, y: r.y }; };
          return { bar: box("[data-confidence-bar]"), accept: box('[data-review-choice="accept"]'), reject: box('[data-review-choice="reject"]'),
            field: box("[data-review-reason] textarea") };
        })()`) as Record<"bar" | "accept" | "reject" | "field", { x: number; w: number; y: number }>;
        assert.ok(control.bar.y < control.accept.y, "the prediction bar sits above the buttons");
        assert.ok(control.accept.y === control.reject.y && control.accept.x < control.reject.x, "Accept left, Reject right, on one row");
        assert.ok(Math.abs(control.accept.w - control.reject.w) < 0.5, "the two buttons are the same width");
        const left = control.accept.x;
        const right = control.reject.x + control.reject.w;
        for (const [name, part] of [["the bar", control.bar], ["the reason field", control.field]] as const) {
          assert.ok(Math.abs(part.x - left) < 0.5 && Math.abs(part.x + part.w - right) < 0.5, `${name} spans the same column as the buttons`);
        }
        assert.ok(control.field.y > control.accept.y, "the reason field sits under the buttons");
        for (const icon of await page.locator("[data-review-card] button svg, [data-review-queue-bar] svg").all()) assert.ok(await icon.evaluate((svg) => svg.classList.contains("lucide") || [...svg.classList].some((c) => c.startsWith("lucide"))), "icons are Lucide");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
  async empty() {
    const { browser, page, errors } = await setup("?empty=1");
    try {
      await page.getByText("No private references imported yet.", { exact: true }).waitFor();
      assert.equal(await page.locator("[data-newsroom-card-id]").count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

export async function runReferenceEditorScenario(name: string) {
  assert.ok(scenarios[name], `Unknown editor reference scenario: ${name}`);
  await scenarios[name]();
  console.log(`Reference editor scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : Object.keys(scenarios)) await runReferenceEditorScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
