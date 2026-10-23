/** Fixture-only browser acceptance for the real References view. No production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://reference-review.test";
let bundle: Promise<string> | undefined;

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
        : "export const loadReferenceAttachmentsForLineageId = async () => []; export const loadStoragePathUrl = async () => ({url:null});", loader: "js", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "reference-review-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
const fixture = [
  {id:'reference-a-v1',lineageId:'reference-a',versionState:'current',versionNumber:1,corpusId:'fixture-corpus',externalItemId:'source-a',title:'Pending reference A',sourceUri:'https://example.org/source-a',curationStatus:'pending',importedAt:'2026-10-22T10:00:00Z'},
  {id:'reference-b-v1',lineageId:'reference-b',versionState:'current',versionNumber:1,corpusId:'fixture-corpus',externalItemId:'source-b',title:'Pending reference B',sourceUri:'https://example.org/source-b',curationStatus:'pending',importedAt:'2026-10-21T10:00:00Z'}
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
  const decision = {decisionRelationId:'decision-a',decisionId:'prediction-a',label:'include',confidence:null,version:null,reviewRecommended:true,reviewReason:'program',reviewDetail:'Fixture review request',classes:['include','exclude'],positiveLabel:'include',question:null,reviewControl:'thumbs',cyclotronId:'fixture-publication',decidedAt:null,provenance:null};
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
    onReview={save} onRelevanceReview={(reference,curation) => save(reference,curation.action,curation)} />;
}
createRoot(document.getElementById('root')).render(<Fixture/>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = `body{margin:0;font:16px sans-serif}button,textarea,select{font:inherit}button{min-height:36px}textarea{display:block;min-height:80px} [data-newsroom-list-detail-shell]{display:flex} [data-news-desk-reference-detail]{padding:8px} [data-newsroom-card-grid]{display:flex;flex-direction:column} [data-newsroom-list-row]{text-align:left;padding:12px;margin:4px} [data-radix-scroll-area-viewport]{max-height:75vh} [role=dialog]{position:fixed;inset:5vh 0 0;background:white;overflow:auto;z-index:10} @media(max-width:767px){[data-newsroom-list-detail-shell]{display:none}}`;

async function setup(options = "", width = 1280) {
  const script = await browserBundle();
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
    return route.fulfill({ contentType: "text/html", body: `<html><head><style>${fixtureCss}</style></head><body><div id="root"></div>${history}<script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom/references${options}`);
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
async function status(page: Page, expected: string) {
  await page.waitForFunction((value) => document.querySelector('[data-news-desk-reference-detail="reference-a"] [data-reference-curation-status]')?.getAttribute("data-reference-curation-status") === value, expected);
}
async function openSectionPlacement(page: Page) {
  const summary = detail(page).getByText("Section placement (optional)", { exact: true });
  if (!await summary.evaluate((element) => element.parentElement?.hasAttribute("open"))) await summary.click();
}

const scenarios: Record<string, () => Promise<void>> = {
  async selection() {
    for (const width of [1280, 390]) {
      const { browser, page, errors } = await setup("", width);
      try {
        await page.getByRole("tab", { name: /Pending/ }).click();
        await selectA(page);
        assert.match(await detail(page).innerText(), /No prediction recorded/i);
        assert.ok(await detail(page).getByRole("button", { name: "Accept reference", exact: true }).isEnabled());
        assert.ok(await detail(page).getByRole("button", { name: "Reject reference", exact: true }).isEnabled());
        if (width === 1280) {
          await detail(page).getByLabel("Review explanation (optional)", { exact: true }).fill("Keep my pending draft while filtering.");
          await page.getByRole("tab", { name: /^All/ }).click();
          await detail(page).waitFor();
          assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "Keep my pending draft while filtering.");
          await page.getByRole("tab", { name: /^Pending/ }).click();
          await detail(page).waitFor();
          assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "Keep my pending draft while filtering.");
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
      await panel.getByRole("button", { name: "Accept reference", exact: true }).click();
      assert.equal(await requestCount(page), 1);
      await settle(page); await status(page, "accepted");
      assert.equal(await panel.getByRole("button", { name: "Save feedback", exact: true }).isEnabled(), false, "unchanged feedback cannot create another completed write");
      await panel.getByLabel("Review explanation (optional)", { exact: true }).fill("A useful source for the publication.");
      await panel.getByRole("button", { name: "Save feedback", exact: true }).click();
      await settle(page);
      await page.waitForFunction(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.curationStatusReason === "A useful source for the publication.");
      assert.equal(await panel.getByRole("button", { name: "Save feedback", exact: true }).isEnabled(), false, "success marks the saved draft clean");
      await page.reload();
      await detail(page).waitFor();
      assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "A useful source for the publication.");
      await detail(page).getByLabel("Rejection reason", { exact: true }).selectOption("out_of_scope");
      await detail(page).getByLabel("Review explanation (optional)", { exact: true }).fill("");
      await detail(page).getByRole("button", { name: "Reject reference", exact: true }).click();
      await settle(page); await status(page, "rejected");
      await page.reload(); await detail(page).waitFor(); await status(page, "rejected");
      assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "");
      await detail(page).getByLabel("Review explanation (optional)", { exact: true }).fill("The source addresses a different audience.");
      await detail(page).getByRole("button", { name: "Save feedback", exact: true }).click();
      await settle(page);
      await page.waitForFunction(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.curationStatusReason === "The source addresses a different audience.");
      await page.reload(); await detail(page).waitFor(); await status(page, "rejected");
      assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "The source addresses a different audience.");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async recovery() {
    const { browser, page, errors } = await setup();
    try {
      await selectA(page);
      const panel = detail(page);
      await panel.getByRole("button", { name: "Reject reference", exact: true }).click();
      assert.equal(await requestCount(page), 0, "rejection requires a reason before any mutation");
      await panel.getByLabel("Review explanation (optional)", { exact: true }).fill("Keep my explanation on failure.");
      const accept = panel.getByRole("button", { name: "Accept reference", exact: true });
      await accept.dblclick();
      assert.equal(await requestCount(page), 1, "a double click starts one mutation");
      assert.equal(await accept.isEnabled(), false);
      assert.equal(await panel.getByRole("button", { name: "Reject reference", exact: true }).isEnabled(), false);
      await settle(page, true);
      await panel.getByRole("alert").filter({ hasText: "Fixture write failed" }).waitFor();
      await status(page, "pending");
      assert.equal(await panel.getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "Keep my explanation on failure.");
      await accept.click(); await settle(page); await status(page, "accepted");
      assert.equal(await requestCount(page), 2);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async revision_from_message() {
    const { browser, page, errors } = await setup();
    try {
      await selectA(page);
      await detail(page).getByLabel("Rejection reason", { exact: true }).selectOption("out_of_scope");
      await detail(page).getByLabel("Review explanation (optional)", { exact: true }).fill("The source addresses a different audience.");
      await detail(page).getByRole("button", { name: "Reject reference", exact: true }).click();
      await settle(page); await status(page, "rejected");
      await page.reload(); await detail(page).waitFor(); await status(page, "rejected");
      assert.equal(await detail(page).getByLabel("Rejection reason", { exact: true }).inputValue(), "out_of_scope", "reason is loaded from the persisted curation Message");
      assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "The source addresses a different audience.");
      assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.metadata), undefined, "Reference metadata does not supply the reason");
      await detail(page).getByLabel("Review explanation (optional)", { exact: true }).fill("");
      await detail(page).getByRole("button", { name: "Save feedback", exact: true }).click();
      assert.equal(await requestCount(page), 1, "feedback can be revised without reselecting the persisted reason");
      await settle(page);
      await page.waitForFunction(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.curationStatusReason === null);
      await page.reload(); await detail(page).waitFor(); await status(page, "rejected");
      assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "", "an explicit blank clears the saved explanation");
      assert.equal(await detail(page).getByLabel("Rejection reason", { exact: true }).inputValue(), "out_of_scope");
      await page.evaluate(() => (window as unknown as {fixtureRefresh: (note: string, reason: string) => void}).fixtureRefresh("Latest saved explanation.", "policy_exclusion"));
      await page.waitForFunction(() => (document.querySelector('textarea[aria-label="Review explanation (optional)"]') as HTMLTextAreaElement)?.value === "Latest saved explanation.");
      assert.equal(await detail(page).getByLabel("Rejection reason", { exact: true }).inputValue(), "policy_exclusion", "untouched feedback follows live message updates");
      assert.equal(await detail(page).getByRole("button", { name: "Save feedback", exact: true }).isEnabled(), false);
      await detail(page).getByLabel("Review explanation (optional)", { exact: true }).fill("My unsaved draft.");
      await detail(page).getByLabel("Rejection reason", { exact: true }).selectOption("duplicate");
      await page.evaluate(() => (window as unknown as {fixtureRefresh: (note: string, reason: string) => void}).fixtureRefresh("Another editor saved this.", "unavailable"));
      assert.equal(await detail(page).getByLabel("Review explanation (optional)", { exact: true }).inputValue(), "My unsaved draft.");
      assert.equal(await detail(page).getByLabel("Rejection reason", { exact: true }).inputValue(), "duplicate", "live updates preserve a dirty draft");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async predictions() {
    const { browser, page, errors } = await setup("?decision=1");
    try {
      await selectA(page);
      await openSectionPlacement(page);
      const text = await detail(page).innerText();
      assert.match(text, /publication/i);
      assert.match(text, /Section/);
      assert.match(text, /include/);
      assert.match(text, /73%/);
      assert.ok(!/0%|100%|version 0/.test(text), "missing confidence and version are never fabricated");
      await detail(page).getByText("How this suggestion was made", { exact: true }).click();
      assert.ok(!/0 teaching|0 priming|0 training/i.test(await detail(page).innerText()), "unknown teaching counts are not reported as zero");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
    for (const button of ["Accept reference", "Agree (accept)"]) {
      const { browser: sectionBrowser, page: sectionPage, errors: sectionErrors } = await setup("?decision=1");
      try {
        await selectA(sectionPage);
        await openSectionPlacement(sectionPage);
        await detail(sectionPage).getByRole("radio", { name: /Fixture Section/ }).check();
        await detail(sectionPage).getByRole("button", { name: button, exact: true }).click();
        const requests = await sectionPage.evaluate(() => (window as unknown as {fixtureRequests:Array<{options:{sectionId?:string}}>} ).fixtureRequests);
        assert.equal(requests[0]?.options.sectionId, "fixture-section", `${button} keeps the editor's selected Section`);
        await settle(sectionPage); await status(sectionPage, "accepted");
        await sectionPage.reload(); await detail(sectionPage).waitFor();
        await openSectionPlacement(sectionPage);
        assert.equal(await detail(sectionPage).getByRole("radio", { name: /Fixture Section/ }).isChecked(), true, "the recorded choice survives a page load");
        await detail(sectionPage).getByLabel("Review explanation (optional)", { exact: true }).fill("Updated explanation for the accepted source.");
        await detail(sectionPage).getByRole("button", { name: "Save feedback", exact: true }).click();
        const revisions = await sectionPage.evaluate(() => (window as unknown as {fixtureRequests:Array<{options:{sectionId?:string}}>} ).fixtureRequests);
        assert.equal(revisions[0]?.options.sectionId, "fixture-section", "a note-only revision retains the actual recorded Section");
        await settle(sectionPage);
        await sectionPage.waitForFunction(() => JSON.parse(localStorage.getItem("references") || "[]")[0]?.curationStatusReason === "Updated explanation for the accepted source.");
        await detail(sectionPage).getByRole("radio", { name: "No Section", exact: true }).check();
        await detail(sectionPage).getByRole("button", { name: "Save feedback", exact: true }).click();
        await settle(sectionPage);
        await sectionPage.waitForFunction(() => JSON.parse(localStorage.getItem("reviewSectionIds") || "[]").length === 0);
        await sectionPage.reload(); await detail(sectionPage).waitFor();
        await openSectionPlacement(sectionPage);
        assert.equal(await detail(sectionPage).getByRole("radio", { name: "No Section", exact: true }).isChecked(), true, "explicitly removing the Section survives reload despite the suggestion");
        assert.deepEqual(sectionErrors, []);
      } finally { await sectionBrowser.close(); }
    }
    const { browser: advancedBrowser, page: advancedPage, errors: advancedErrors } = await setup("?decision=1");
    try {
      await selectA(advancedPage);
      await detail(advancedPage).getByText("Review with a reason", { exact: true }).click();
      const advanced = detail(advancedPage).locator("[data-reference-relevance-review]");
      await advanced.getByRole("button", { name: "Yes: include", exact: true }).click();
      await advanced.getByRole("button", { name: "Submit review", exact: true }).dblclick();
      assert.equal(await requestCount(advancedPage), 1, "advanced review also protects repeated pending clicks");
      await settle(advancedPage); await status(advancedPage, "accepted");
      assert.equal(await detail(advancedPage).locator("[data-reference-relevance-review]").count(), 0, "a completed advanced submission is removed");
      assert.equal(await detail(advancedPage).getByRole("button", { name: "Submit review", exact: true }).count(), 0);
      assert.equal(await requestCount(advancedPage), 1);
      assert.deepEqual(advancedErrors, []);
    } finally { await advancedBrowser.close(); }
  },
  async prediction_loading() {
    const { browser, page, errors } = await setup("?predictions=loading");
    try {
      await selectA(page);
      await page.getByText(/Loading predictions/i).waitFor();
      assert.ok(!/No prediction recorded/i.test(await detail(page).innerText()), "unfinished reads are not reported as missing data");
      assert.ok(await detail(page).getByRole("button", { name: "Accept reference", exact: true }).isEnabled());
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async prediction_failure() {
    const { browser, page, errors } = await setup("?predictions=error");
    try {
      await selectA(page);
      await page.getByText(/Predictions unavailable/i).waitFor();
      assert.ok(!/No prediction recorded/i.test(await detail(page).innerText()), "failed reads are not reported as missing data");
      await page.getByRole("button", { name: "Retry predictions", exact: true }).click();
      await detail(page).getByText(/No prediction recorded/i).waitFor();
      assert.ok(await detail(page).getByRole("button", { name: "Accept reference", exact: true }).isEnabled());
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
  async readonly() {
    const { browser, page, errors } = await setup("?readonly=1");
    try {
      await selectA(page);
      assert.equal(await detail(page).getByRole("button", { name: "Accept reference", exact: true }).isEnabled(), false);
      assert.equal(await detail(page).getByRole("button", { name: "Reject reference", exact: true }).isEnabled(), false);
      assert.match(await detail(page).innerText(), /editor|permission|read.only/i);
      assert.equal(await requestCount(page), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
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
