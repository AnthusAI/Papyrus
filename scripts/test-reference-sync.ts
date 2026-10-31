/**
 * Fixture-only browser acceptance for the References feed and its detail pane working as one: a vote or a reason in either shows in
 * both, in either order; Previous / Next scrolls to and selects the grid card; our captured record says what we really stored.
 * 375 and 1440 pixels. No network, no production reads.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://reference-sync.test";
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

const organizerCss = () => fs.readFileSync(`${root}components/newsroom-organizer.css`, "utf8");

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
          : `export const loadReferenceAttachmentsForLineageId = async () => [];
export const loadStoragePathUrl = async () => ({url:null,error:null});
export const loadStoragePathText = async (path) => ({text: (window.fixtureTexts || {})[path] ?? null, error: null});
export const loadModelPayloadsForOwner = async (kind, id) => (window.fixturePayloads || {})[id] || [];
export const uploadModelPayloadForOwner = async (input) => { window.fixtureUploads.push({ ownerKind: input.ownerKind, ownerId: input.ownerId, role: input.role, mediaType: input.mediaType, filename: input.filename, byteSize: input.content.size }); if (window.fixtureUploadFails) throw new Error("Attachment upload failed: 403 Forbidden"); return { id: "upload-" + window.fixtureUploads.length }; };`,
        loader: "js", resolveDir: root,
      }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "reference-sync-fixture.tsx", contents: `
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { NewsroomReferencesView } from "./components/newsroom-references-view";

const params = new URLSearchParams(location.search);
const iso = (hours) => new Date(Date.parse("2026-10-27T12:00:00Z") - hours * 3600000).toISOString();
const make = (n) => ({ id: "r" + n + "-v1", lineageId: "r" + n, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: "s" + n, title: "Reference number " + n, sourceUri: "https://site" + n + ".example.org/a", curationStatus: "pending", createdAt: iso(n), sourcePublishedAt: iso(n) });
const fixture = Array.from({ length: 14 }, (_, index) => make(index + 1));
const decision = (label, confidence) => ({ decisionRelationId: "d", decisionId: "d", label, confidence, version: 1, reviewRecommended: false, reviewReason: null, reviewDetail: null, classes: ["include", "exclude"], positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null });
// r1 is the strongest Accept, then r2, r3 ...; r4 is a predicted Reject.
const initialDecisions = new Map([["r1", decision("include", 0.95)], ["r2", decision("include", 0.9)], ["r3", decision("include", 0.85)], ["r4", decision("exclude", 0.9)], ["r5", decision("include", 0.8)]]);
const attachment = (n, role, extra = {}) => ({ id: "att-" + n + "-" + role, referenceId: "r" + n + "-v1", referenceLineageId: "r" + n, referenceVersionKey: "reference#r" + n + "-v1", role, sortKey: "900-" + role, ...extra });
const words = (count) => Array.from({ length: count }, (_, index) => "word" + index).join(" ");
window.fixtureTexts = { "fixture://full": "## Captured article.\\n\\n" + words(600), "fixture://thin": "Only a teaser. " + words(60) };
window.fixturePayloads = { "r1-v1": [{ attachment: { role: "metadata", sortKey: "metadata" }, json: { summary: "A stored summary of the full article." }, text: null, error: null }] };
const attachments = [
  attachment(1, "source", { sourceUri: "https://site1.example.org/a" }),
  attachment(1, "extracted_text", { storagePath: "fixture://full", byteSize: 4200, metadata: JSON.stringify({ textLength: 4200, grobid: { title: "Parsed paper title", authors: ["A. Author", "B. Author"], abstract: "Parsed abstract." } }) }),
  attachment(2, "source", { sourceUri: "https://site2.example.org/a" }),
  attachment(2, "extracted_text", { storagePath: "fixture://thin", byteSize: 420, metadata: JSON.stringify({ textLength: 420 }) }),
  ...fixture.slice(2).map((row, index) => attachment(index + 3, "source", { sourceUri: row.sourceUri })),
];
// Curation before review: one card per Reference (role curation, sort key 003-curation); the bodies are ModelAttachments.
const card = (n, body) => attachments.push(attachment(n, "curation", { sortKey: "003-curation", metadata: JSON.stringify({ kind: "reference-curation", schemaVersion: 1, ...body }) }));
const body = (sortKey, extra) => ({ attachment: { role: "metadata", sortKey }, text: null, json: null, error: null, ...extra });
card(4, { status: "ready", capture: { status: "completed", sourceKind: "html", wordCount: 912, textSortKey: "curation-text" }, signals: { wordCount: 912, endingPattern: "sentence_end" },
  summary: { status: "completed", text: "Curated summary of the article.", stale: false }, grobid: { status: "completed", title: "Curated paper", authorCount: 1, sectionCount: 3, referenceCount: 2, fieldsSortKey: "curation-grobid" }, current: { textSortKey: "curation-text", grobidSortKey: "curation-grobid" } });
window.fixturePayloads["r4-v1"] = [body("curation-text", { text: "Curated article body. " + words(909) }), body("curation-grobid", { json: { title: "Curated paper", authors: [{ name: "Ada L." }], abstract: "A curated abstract.", sections: [1, 2, 3], references: [1, 2] } }), body("metadata", { json: { summary: "Older metadata summary." } })];
card(5, { status: "capture_failed", capture: { status: "failed", reason: "blocked", transient: false }, signals: {}, summary: { status: "skipped" } });
card(6, { status: "capture_failed", capture: { status: "failed", reason: "timeout", transient: true }, signals: {} });
attachments.push(attachment(6, "extracted_text", { storagePath: "fixture://full", byteSize: 4200, metadata: JSON.stringify({ textLength: 4200 }) }));
card(7, { status: "degraded", capture: { status: "completed", wordCount: 800, textSortKey: "curation-text" }, signals: { wordCount: 800, endingPattern: "sentence_end", paywallMarkers: [{ id: "subscribe_to_continue", inTail: true }] }, summary: { status: "failed", reason: "openai_not_configured" }, current: { textSortKey: "curation-text" } });
window.fixturePayloads["r7-v1"] = [body("curation-text", { text: "Teaser article. " + words(798) })];
card(8, { status: "running", capture: { status: "not_run" }, signals: {} });
window.fixtureCorrections = [];
window.fixtureUploads = [];
window.fixtureRequests = [];
window.fixtureFailNext = false;
// ?shell mounts the view the way the newsroom does: inside the organizer's own scroller (.organizer-main) with its bottom tab bar below.
const Frame = params.has("shell")
  ? ({ children }) => <div className="newsroom-organizer" data-kanbus-theme="" data-sidebar-collapsed="true" style={{ "--kb-theme-paper": "#f4f1e8", "--kb-theme-ink": "#1d1d1b", "--org-paper": "#f4f1e8", "--org-ink": "#1d1d1b" }}>
      <div className="organizer-workspace" style={{ minHeight: 0, display: "flex", flexDirection: "column" }}><main className="organizer-main" data-category-steering="">{children}</main></div>
      <nav className="organizer-bottom-nav" aria-label="Primary newsroom navigation"><ul>{["Work", "References", "Stories", "Messages", "More"].map((name) => <li key={name}><a href="#">{name}</a></li>)}</ul></nav>
    </div>
  : ({ children }) => <div style={{ height: "100dvh", display: "flex", flexDirection: "column", padding: 12 }}>{children}</div>;

function Fixture() {
  const [references, setReferences] = useState(fixture);
  const [reasons, setReasons] = useState(new Map());
  const [decisions, setDecisions] = useState(initialDecisions);
  // A background refresh: the strongest predictions are swapped for the weakest (a re-rank would move everything) and a new item arrives.
  window.fixtureReshuffle = () => setDecisions(new Map([["r1", decision("exclude", 0.95)], ["r2", decision("exclude", 0.9)], ["r5", decision("include", 0.99)], ["r9", decision("include", 0.98)], ["r10", decision("include", 0.97)]]));
  window.fixtureAddItem = () => setReferences((current) => [make(15), ...current]);
  async function save(reference, action, options = {}) {
    window.fixtureRequests.push({ id: reference.lineageId, action, note: options.note ?? null, reasonCode: options.reasonCode ?? null });
    await new Promise((resolve) => setTimeout(resolve, Number(window.fixtureDelay || 0)));
    if (window.fixtureFailNext) { window.fixtureFailNext = false; throw new Error("Fixture write failed. Try again."); }
    const status = { accept: "accepted", reject: "rejected", archive: "archived" }[action];
    setReferences((current) => current.map((row) => row.lineageId === reference.lineageId ? { ...row, curationStatus: status, curationStatusReason: options.note?.trim() || null, curationStatusUpdatedAt: new Date().toISOString() } : row));
    setReasons((current) => { const next = new Map(current); if (action === "reject") next.set(reference.lineageId, options.reasonCode); else next.delete(reference.lineageId); return next; });
  }
  return <Frame>
    <NewsroomReferencesView decisions={decisions} onCorrectCapture={params.has("nocorrect") ? undefined : async (input) => {
      window.fixtureCorrections.push(input);
      if (!input.pdfAttachmentId) return;
      if (window.fixtureReadFails) throw new Error("That PDF has no text we can read; it looks like a scan. Paste the text instead.");
      window.fixturePayloads[input.referenceId] = [body("curation-edit-0001-text", { text: "Text read from the uploaded PDF. " + words(40) })];
      return { ok: true, edits: [{ kind: "text", sortKey: "curation-edit-0001-text", via: "editor_pdf" }] };
    }} onReview={save} referenceAttachments={attachments} references={references} reviewReasons={reasons} />
  </Frame>;
}
createRoot(document.getElementById("root")).render(<Fixture />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(width: number, options = "") {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 800 } });
  page.setDefaultTimeout(6000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    // Only site1 lets itself be framed; every other source refuses, as most news sites do.
    if (url.pathname === "/api/newsroom/source-frameable") return route.fulfill({ contentType: "application/json", body: JSON.stringify({ frameable: (url.searchParams.get("url") ?? "").includes("site1.") }) });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style>${options.includes("shell") ? `<style>${organizerCss()}</style>` : ""}<style>body{margin:0;font:16px sans-serif}button,textarea{font:inherit}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom/references${options}`);
  await page.locator("[data-feed-card]").first().waitFor();
  return { browser, page, errors };
}

const card = (page: Page, id: string) => page.locator(`[data-feed-card="${id}"]`);
const review = (page: Page) => page.locator("[data-review-card]").locator("visible=true").first();
const requests = (page: Page) => page.evaluate(() => (window as unknown as { fixtureRequests: Array<Record<string, unknown>> }).fixtureRequests);
const open = async (page: Page, id: string) => { await card(page, id).locator("[data-feed-open]").click(); await review(page).waitFor(); };
/** Below 1024 the detail takes the feed's place at the full width: go Back to see the cards again. From 1024 it sits beside the feed. */
const closeDetail = async (page: Page, width: number) => { if (width < 1024) { await page.locator("[data-reference-back]:visible").click(); await card(page, "r1").waitFor(); } };
const rgbOf = (locator: ReturnType<Page["locator"]>, property: "color" | "backgroundColor") => locator.evaluate((el, prop) => {
  const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
  const context = canvas.getContext("2d")!; context.fillStyle = "#000"; context.fillStyle = getComputedStyle(el)[prop as "color"]; context.fillRect(0, 0, 1, 1);
  const [r, g, b] = context.getImageData(0, 0, 1, 1).data; return { r, g, b };
}, property);
const WHY = /^Reason/;

const scenarios: Record<string, () => Promise<void>> = {
  /** The curation card is read first (status, words, signals, summary, GROBID fields, the curation-text body); extracted_text is the fallback. */
  async curation_card() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        const badge = (id: string) => card(page, id).locator("[data-capture-badge]");
        assert.equal(await badge("r4").getAttribute("data-capture-badge"), "full");
        assert.equal(await badge("r4").getAttribute("data-capture-curation"), "ready", "the badge follows the curation status");
        assert.equal(await badge("r5").getAttribute("data-capture-badge"), "none", "capture_failed with no other text is No text");
        assert.equal(await badge("r6").getAttribute("data-capture-badge"), "full", "capture_failed but an extracted_text exists: the fallback is used");
        assert.equal(await badge("r7").getAttribute("data-capture-badge"), "thin", "a paywall phrase at the end makes a long capture doubtful");
        assert.ok((await badge("r7").innerText()).includes("Maybe cut off"));
        assert.equal(await badge("r8").getAttribute("data-capture-badge"), "running");

        const panelOf = () => review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await open(page, "r4");
        let panel = panelOf();
        await panel.locator("[data-capture-text]").waitFor();
        assert.equal(await panel.locator("[data-capture-status]").getAttribute("data-capture-source"), "curation");
        assert.equal(await panel.locator("[data-capture-label]").innerText(), "Full text captured");
        assert.ok((await panel.locator("[data-capture-text]").innerText()).includes("Curated article body."), "the curation-text body is shown");
        assert.ok((await panel.locator("[data-capture-words]").innerText()).includes("912 words"));
        assert.ok((await review(page).locator("[data-review-summary]").innerText()).includes("Curated summary of the article."), "the card's own summary wins over metadata.json, shown with the title");
        const rows = await panel.locator("[data-capture-structured]").innerText();
        assert.ok(rows.includes("Curated paper") && rows.includes("Ada L.") && rows.includes("A curated abstract.") && rows.includes("3 sections") && rows.includes("2 cited works"), "the GROBID fields");
        await closeDetail(page, width);

        await open(page, "r5");
        panel = panelOf();
        assert.equal(await panel.locator("[data-capture-label]").innerText(), "No text captured");
        assert.ok((await panel.locator("[data-capture-detail]").innerText()).includes("refused our request"), "the typed reason in words");
        await closeDetail(page, width);

        await open(page, "r6");
        panel = panelOf();
        await panel.locator("[data-capture-text]").waitFor();
        assert.equal(await panel.locator("[data-capture-status]").getAttribute("data-capture-source"), "extracted", "extracted_text is the fallback");
        assert.equal(await panel.locator("[data-capture-label]").innerText(), "Full text captured");
        await closeDetail(page, width);

        await open(page, "r7");
        panel = panelOf();
        await panel.locator("[data-capture-text]").waitFor();
        assert.equal(await panel.locator("[data-capture-label]").innerText(), "Captured, but it may be cut off or paywalled");
        assert.ok((await panel.locator("[data-capture-detail]").innerText()).includes("subscribe or sign-in phrase"));
        assert.ok((await panel.locator("[data-capture-curation-note]").innerText()).includes("summary"), "a degraded card says a stage is unfinished");
        await closeDetail(page, width);

        await open(page, "r8");
        assert.equal(await panelOf().locator("[data-capture-label]").innerText(), "Being captured now");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** "Paste or correct the text": the editor's text and verdict go to correctReferenceCapture, and the panel shows them. */
  async correct_capture() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await open(page, "r5");
        const panel = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await panel.locator("[data-capture-correct]").click();
        const save = panel.locator("[data-capture-correction-save]");
        await save.click({ force: true });
        assert.equal(await page.evaluate(() => (window as unknown as { fixtureCorrections: unknown[] }).fixtureCorrections.length), 0, "a verdict is required, and the form says so in words");
        assert.ok(await panel.locator("[data-capture-correction-reason]").isVisible());
        await panel.locator("[data-capture-correction-text]").fill("The whole article, pasted by an editor.");
        await panel.locator("[data-capture-assessment=complete]").click();
        await save.click();
        await panel.locator("[data-capture-correction-saved]").waitFor();
        assert.deepEqual(await page.evaluate(() => (window as unknown as { fixtureCorrections: unknown[] }).fixtureCorrections), [{ referenceId: "r5-v1", text: "The whole article, pasted by an editor.", assessment: "complete" }]);
        assert.ok((await panel.locator("[data-capture-text]").innerText()).includes("pasted by an editor"), "the panel shows the new text");
        assert.ok((await panel.locator("[data-capture-assessment-note]").innerText()).includes("complete"), "and the verdict");
        assert.ok(await panel.locator("[data-capture-summary-stale]").isVisible(), "the summary is marked as awaiting the next run");
        await closeDetail(page, width);
        // A verdict alone is just a label on the capture.
        await open(page, "r4");
        const second = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await second.locator("[data-capture-correct]").click();
        await second.locator("[data-capture-assessment=incomplete]").click();
        await second.locator("[data-capture-correction-save]").click();
        await second.locator("[data-capture-correction-saved]").waitFor();
        const sent = await page.evaluate(() => (window as unknown as { fixtureCorrections: Array<Record<string, unknown>> }).fixtureCorrections);
        assert.deepEqual(sent[1], { referenceId: "r4-v1", assessment: "incomplete" });
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
    // Without the action there is no edit button.
    const { browser, page } = await setup(1440, "?nocorrect=1");
    try {
      await open(page, "r5");
      assert.equal(await page.locator("[data-capture-correct]").count(), 0);
    } finally { await browser.close(); }
  },

  /** "Upload a PDF": the file is stored as an attachment of the Reference, then correctReferenceCapture gets its id with the verdict. */
  async upload_pdf() {
    const pdf = { name: "paper.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 fixture") };
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await open(page, "r5");
        const panel = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await panel.locator("[data-capture-upload]").click();
        const input = panel.locator("[data-capture-upload-input]");
        assert.equal(await input.getAttribute("accept"), "application/pdf");
        // A verdict comes first, as with pasted text; choosing a file without one does nothing.
        await panel.locator("[data-capture-upload-choose]").click({ force: true });
        assert.ok(await panel.locator("[data-capture-upload-reason]").isVisible());
        await panel.locator("[data-capture-assessment=incomplete]").click();
        await input.setInputFiles(pdf);
        await panel.locator("[data-capture-correction-saved]").waitFor();
        assert.deepEqual(await page.evaluate(() => (window as unknown as { fixtureUploads: unknown[] }).fixtureUploads), [{ ownerKind: "reference", ownerId: "r5-v1", role: "curation-upload-pdf", mediaType: "application/pdf", filename: "paper.pdf", byteSize: pdf.buffer.length }]);
        assert.deepEqual(await page.evaluate(() => (window as unknown as { fixtureCorrections: unknown[] }).fixtureCorrections), [{ referenceId: "r5-v1", pdfAttachmentId: "upload-1", assessment: "incomplete" }]);
        assert.ok((await panel.locator("[data-capture-text]").innerText()).includes("Text read from the uploaded PDF"), "the panel shows the new text");
        assert.equal((await panel.locator("[data-capture-from-pdf]").innerText()).trim(), "Text from a PDF you uploaded");
        assert.ok((await panel.locator("[data-capture-assessment-note]").innerText()).includes("incomplete"));
        assert.deepEqual(errors, []);
        await closeDetail(page, width);
        // The server refuses a scan: the reason shows in words and nothing is shown as replaced.
        await page.evaluate(() => { (window as unknown as { fixtureReadFails: boolean }).fixtureReadFails = true; });
        await open(page, "r6");
        const second = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await second.locator("[data-capture-upload]").click();
        await second.locator("[data-capture-assessment=incorrect]").click();
        await second.locator("[data-capture-upload-input]").setInputFiles(pdf);
        assert.ok((await second.locator("[data-capture-upload-error]").innerText()).includes("looks like a scan"));
        assert.equal(await second.locator("[data-capture-from-pdf]").count(), 0);
        // A failed upload reads in words too.
        await page.evaluate(() => { (window as unknown as { fixtureUploadFails: boolean }).fixtureUploadFails = true; });
        await second.locator("[data-capture-upload-input]").setInputFiles(pdf);
        assert.ok((await second.locator("[data-capture-upload-error]").innerText()).includes("Attachment upload failed"));
      } finally { await browser.close(); }
    }
    // Without the correction action there is no upload button.
    const { browser, page } = await setup(1440, "?nocorrect=1");
    try {
      await open(page, "r5");
      assert.equal(await page.locator("[data-capture-upload]").count(), 0);
    } finally { await browser.close(); }
  },

  /** Vote, then reason: the reason is saved onto the existing decision after a pause or on blur, and both views show it. */
  async vote_then_reason() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await card(page, "r1").locator("[data-review-choice=accept]").click();
        await card(page, "r1").locator("[data-verdict=match]").waitFor();
        await open(page, "r1");
        assert.equal(await review(page).locator("[data-review-choice=accept]").getAttribute("aria-pressed"), "true", "the detail pane shows the vote made on the card");
        assert.ok((await review(page).locator("[data-predicted]").innerText()).toLowerCase().includes("confirmed"), "and its green match state");
        await review(page).getByLabel(WHY).fill("Exactly the audience we serve.");
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 2, undefined, { timeout: 4000 });
        assert.deepEqual((await requests(page))[1], { id: "r1", action: "accept", note: "Exactly the audience we serve.", reasonCode: null }, "the reason is saved onto the decision, after a pause");
        await review(page).locator("[data-review-saved]").waitFor();
        await closeDetail(page, width);
        await card(page, "r1").locator("[data-review-saved]").waitFor();
        assert.equal(await requests(page).then((all) => all.length), 2, "one decision, updated once");
        // On blur the reason saves at once.
        await card(page, "r2").locator("[data-review-choice=accept]").click();
        await open(page, "r2");
        await review(page).getByLabel(WHY).fill("Quick note.");
        await review(page).getByLabel(WHY).blur();
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 4, undefined, { timeout: 800 });
        assert.equal(((await requests(page))[3] as { note: string }).note, "Quick note.");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Reason, then vote: the vote carries the reason. A typed reason is never lost, even when a save fails. */
  async reason_then_vote() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await open(page, "r3");
        const why = review(page).getByLabel(WHY);
        await why.fill("Typed before voting.");
        await page.waitForTimeout(1600);
        assert.equal((await requests(page)).length, 0, "nothing is saved onto a decision that does not exist yet");
        await review(page).locator("[data-review-choice=accept]").click();
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 1);
        assert.deepEqual((await requests(page))[0], { id: "r3", action: "accept", note: "Typed before voting.", reasonCode: null }, "the vote carries the reason");
        await closeDetail(page, width);
        assert.ok((await card(page, "r3").locator("[data-predicted]").innerText()).toLowerCase().includes("confirmed"));
        // A typed reason is a reason: a Reject with words and no reason button saves at once.
        await open(page, "r6");
        await review(page).getByLabel(WHY).fill("Not our beat.");
        await review(page).locator("[data-review-choice=reject]").click();
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 2);
        assert.deepEqual((await requests(page))[1], { id: "r6", action: "reject", note: "Not our beat.", reasonCode: null }, "a typed reason saves the Reject");
        await closeDetail(page, width);
        // With no reason at all, a Reject waits for one and saves nothing.
        await open(page, "r7");
        await review(page).locator("[data-review-choice=reject]").click();
        assert.ok(await review(page).locator("[data-review-record]").isVisible(), "a Reject with no reason asks for one, in words");
        assert.equal((await requests(page)).length, 2, "a Reject with no reason waits");
        await review(page).getByLabel(WHY).fill("Off topic for us.");
        await review(page).locator("[data-review-record]").click();
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 3);
        assert.deepEqual((await requests(page))[2], { id: "r7", action: "reject", note: "Off topic for us.", reasonCode: null });
        await closeDetail(page, width);
        await open(page, "r6");
        // A failed save keeps what was typed.
        await page.evaluate(() => { (window as unknown as { fixtureFailNext: boolean }).fixtureFailNext = true; });
        await review(page).getByLabel(WHY).fill("Second thoughts that must not vanish.");
        await review(page).getByLabel(WHY).blur();
        await review(page).getByRole("alert").waitFor();
        assert.equal(await review(page).getByLabel(WHY).inputValue(), "Second thoughts that must not vanish.", "a typed reason is never lost");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** A vote or a reason in the detail pane shows on the card, and the card's Reject asks for its reason in both places. */
  async card_and_detail_agree() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        await card(page, "r4").locator("[data-review-choice=reject]").click();
        assert.equal(await card(page, "r4").locator("[data-review-record]").count(), 1, "the card asks for a reason");
        await open(page, "r4");
        assert.equal(await review(page).locator("[data-review-choice=reject]").getAttribute("aria-pressed"), "true", "the detail pane shows the waiting Reject");
        assert.ok(await review(page).locator("[data-review-record]").isVisible());
        await review(page).getByLabel(WHY).fill("Seen this one already.");
        await review(page).locator("[data-review-record]").click();
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 1);
        await closeDetail(page, width);
        await card(page, "r4").locator("[data-prediction-mark][data-verdict=match]").waitFor();
        assert.equal(await card(page, "r4").getAttribute("data-feed-rated"), "reject");
        assert.equal(await card(page, "r4").locator("[data-review-record]").count(), 0, "nothing is waiting any more");
        const green = await rgbOf(card(page, "r4").locator("[data-prediction-mark][data-verdict=match]"), "color");
        assert.ok(green.g > green.r, "a match is green on the card");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Previous / Next scrolls the grid to the same item and selects it: a tinted surface and a thick ring outside the card, no border. */
  async previous_next_selects() {
    const { browser, page, errors } = await setup(1440);
    try {
      await card(page, "r1").waitFor();
      assert.equal(await page.locator("[data-newsroom-list-detail-shell]").isVisible(), false, "no empty Detail pane before a reference is selected");
      await open(page, "r1");
      assert.equal(await page.locator("[data-newsroom-list-detail-shell]").isVisible(), true, "the pane appears with the selection");
      assert.equal(await page.locator("[data-feed-selected]").getAttribute("data-feed-card"), "r1", "opening from the grid selects the card");
      // A thick ring drawn outside the card on every side (a box-shadow): nothing inside it is covered and it takes no layout space.
      assert.equal(await card(page, "r1").locator("[data-feed-selected-bar]").count(), 0, "no left strip");
      await page.waitForTimeout(400);   // the ring eases in
      const ring = await card(page, "r1").evaluate((el) => getComputedStyle(el).boxShadow);
      assert.match(ring, /0px 0px 0px 4px/, `a 4px ring outside the card: ${ring}`);
      const room = await page.evaluate(() => {
        const box = document.querySelector('[data-feed-card="r1"]')!.getBoundingClientRect();
        const scroller = document.querySelector("[data-reference-feed-scroll]")!.getBoundingClientRect();
        return { left: box.left - scroller.left, top: box.top - scroller.top };
      });
      assert.ok(room.left >= 4 && room.top >= 4, `the scroller leaves room for the ring, so it is not cut off: ${JSON.stringify(room)}`);
      const style = await card(page, "r1").evaluate((el) => { const c = getComputedStyle(el); return { border: c.borderTopWidth, outline: c.outlineStyle }; });
      assert.deepEqual(style, { border: "0px", outline: "none" }, "no outline lines");
      const queue = page.locator("[data-review-queue-bar]:visible");
      for (let step = 0; step < 9; step += 1) await queue.getByRole("button", { name: "Next" }).click();
      const selected = (await page.locator("[data-feed-selected]").getAttribute("data-feed-card"))!;
      assert.equal(await page.locator("[data-feed-selected]").count(), 1, "exactly one card is selected");
      assert.notEqual(selected, "r1");
      await page.waitForTimeout(900); // the smooth scroll
      const inView = await card(page, selected).evaluate((el) => {
        const scroller = el.closest("[data-reference-feed-scroll]")!.getBoundingClientRect(); const rect = el.getBoundingClientRect();
        return rect.bottom > scroller.top + 8 && rect.top < scroller.bottom - 8;
      });
      assert.ok(inView, "the selected card was scrolled into view");
      assert.equal(await page.locator("[data-review-card]:visible").getAttribute("data-review-card"), selected, "the pane shows the same item");
      for (let step = 0; step < 9; step += 1) await queue.getByRole("button", { name: "Previous" }).click();
      assert.equal(await page.locator("[data-feed-selected]").getAttribute("data-feed-card"), "r1", "Previous selects it again");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Our captured record: full text, a teaser, or nothing, said in words with an icon, above the source preview, with a badge on the card. */
  async capture_status() {
    for (const width of [375, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        assert.equal(await card(page, "r1").locator("[data-capture-badge]").getAttribute("data-capture-badge"), "full");
        assert.equal(await card(page, "r2").locator("[data-capture-badge]").getAttribute("data-capture-badge"), "thin");
        assert.equal(await card(page, "r3").locator("[data-capture-badge]").getAttribute("data-capture-badge"), "none");
        assert.ok((await card(page, "r3").locator("[data-capture-badge]").innerText()).includes("No text"));
        assert.equal(await card(page, "r1").locator("[data-capture-badge] svg").count(), 1, "each state has its own icon");

        await open(page, "r1");
        const panel = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await panel.waitFor();
        assert.equal(await panel.getAttribute("data-capture-panel"), "full");
        assert.equal(await panel.locator("[data-capture-label]").innerText(), "Full text captured");
        await panel.locator("[data-capture-text]").waitFor();
        assert.ok((await panel.locator("[data-capture-text]").innerText()).includes("Captured article."), "the stored text is shown");
        // Stored as Markdown, shown formatted: the heading is a heading and no "##" shows through.
        assert.equal(await panel.locator("[data-capture-text] :is(h2,h3,h4,h5)", { hasText: "Captured article." }).count(), 1, "a Markdown heading renders as a heading");
        assert.ok(!(await panel.locator("[data-capture-text]").innerText()).includes("##"), "no Markdown syntax shows through");
        assert.ok((await panel.locator("[data-capture-words]").innerText()).includes("603 words"), "with its word count");
        assert.ok((await review(page).locator("[data-review-summary]").innerText()).includes("A stored summary of the full article."), "the summary is shown with the title");
        assert.equal(await panel.locator("[data-capture-summary]").count(), 0, "and not repeated in the record");
        assert.ok((await panel.locator("[data-capture-structured]").innerText()).includes("Parsed paper title"), "and the structured extraction");
        // A source that allows framing shows its live preview right under its link, above the summary and the rating.
        await review(page).locator("[data-news-desk-reference-source-preview=html]").waitFor();
        const order = await page.evaluate(() => [...document.querySelectorAll("[data-review-card] header a[target=_blank], [data-news-desk-reference-source-preview], [data-review-summary], [data-capture-panel]")]
          .filter((el) => (el as HTMLElement).offsetParent).map((el) => el.hasAttribute("data-news-desk-reference-source-preview") ? "preview" : el.hasAttribute("data-review-summary") ? "summary" : el.hasAttribute("data-capture-panel") ? "capture" : "link"));
        assert.deepEqual(order, ["link", "preview", "summary", "capture"], "the preview sits under the link, our record after the rating");
        assert.equal(await page.getByText("Source preview", { exact: true }).count(), 0, "no heading of its own");
        // Top to bottom: title, summary, the rating, then our record.
        const top = await page.evaluate(() => ["[data-review-card] h2", "[data-review-summary]", "[data-review-card] [data-review-choice=accept]", "[data-capture-panel]"]
          .map((selector) => Math.round(([...document.querySelectorAll(selector)].find((el) => (el as HTMLElement).offsetParent) as HTMLElement).getBoundingClientRect().top)));
        assert.deepEqual([...top].sort((a, b) => a - b), top, `title, summary, rating, record in that order: ${top.join(", ")}`);
        await closeDetail(page, width);

        await open(page, "r2");
        const thin = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        await thin.locator("[data-capture-text]").waitFor();
        assert.equal(await thin.getAttribute("data-capture-panel"), "thin");
        assert.match(await thin.locator("[data-capture-label]").innerText(), /^Only 63 words — may be a teaser or paywalled$/);
        await page.waitForTimeout(300);
        assert.equal(await review(page).locator("[data-news-desk-reference-source-preview]").count(), 0, "a source that refuses framing shows no preview and no empty box");
        await closeDetail(page, width);

        await open(page, "r3");
        const none = review(page).locator("xpath=ancestor::*[.//*[@data-capture-panel]][1]").locator("[data-capture-panel]");
        assert.equal(await none.getAttribute("data-capture-panel"), "none");
        assert.equal(await none.locator("[data-capture-label]").innerText(), "No text captured");
        assert.equal(await none.locator("[data-capture-text]").count(), 0);
        assert.equal(await none.locator("svg").count() > 0, true, "an icon beside the words");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
};

Object.assign(scenarios, {
  /** On a phone nothing in the detail scrolls inside itself: the captured text and the text boxes grow, and a swipe moves the page. */
  async phone_scroll() {
    const { browser, page, errors } = await setup(375);
    try {
      await open(page, "r1");
      const panel = page.locator("[data-capture-panel]:visible");
      await panel.locator("[data-capture-text]").waitFor();
      const toggle = panel.locator("[data-capture-toggle]");
      if (await toggle.count()) await toggle.click();
      await review(page).getByLabel(WHY).fill(Array.from({ length: 12 }, (_, line) => `Line ${line + 1} of a long reason.`).join("\n"));
      const boxes = await page.evaluate(() => [...document.querySelectorAll("[data-capture-text], textarea")].filter((el) => (el as HTMLElement).offsetParent).map((el) => {
        const style = getComputedStyle(el);
        return { overflow: style.overflowY, scrolls: el.scrollHeight > el.clientHeight + 1 };
      }));
      assert.ok(boxes.length >= 2, "the captured text and the Why box are on screen");
      for (const box of boxes) {
        assert.ok(!["auto", "scroll"].includes(box.overflow), `no inner scroll box (${box.overflow})`);
        assert.equal(box.scrolls, false, "every box is as tall as its text");
      }
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
});

/** A click that does not scroll the page first (Playwright's own click scrolls the target into view, which would hide a real jump). */
const domClick = (locator: ReturnType<Page["locator"]>) => locator.evaluate((el) => (el as HTMLElement).click());

/** The geometry of every card in content coordinates (independent of the scroll position), in DOM order. */
const geometry = (page: Page) => page.evaluate(() => {
  const scroller = document.querySelector("[data-reference-feed-scroll]") as HTMLElement;
  const box = scroller.getBoundingClientRect();
  return {
    scrollTop: scroller.scrollTop,
    cards: [...document.querySelectorAll("[data-feed-card]")].map((el) => {
      const rect = el.getBoundingClientRect();
      return { id: el.getAttribute("data-feed-card")!, x: Math.round(rect.x - box.x), y: Math.round(rect.y - box.y + scroller.scrollTop), w: Math.round(rect.width), h: Math.round(rect.height) };
    }),
  };
});

function assertSame(before: Awaited<ReturnType<typeof geometry>>, after: Awaited<ReturnType<typeof geometry>>, what: string) {
  assert.deepEqual(after.cards.map((c) => c.id), before.cards.map((c) => c.id), `${what}: the cards are in the same order`);
  for (const [index, card] of before.cards.entries()) {
    const now = after.cards[index];
    for (const key of ["x", "y", "w", "h"] as const) assert.ok(Math.abs(now[key] - card[key]) <= 1, `${what}: ${card.id} ${key} ${card[key]} -> ${now[key]}`);
  }
}

Object.assign(scenarios, {
  /** Selecting, rating and a background refresh never move a card: same order, same boxes, same scroll position. */
  async grid_stays_put() {
    // 1100 and 1440: the detail pane appears beside the grid with the first selection (the grid narrows once) and then holds its place;
    // 375: the detail takes the feed's place, with a Back control, so the grid is measured after going Back.
    for (const width of [375, 1100, 1440]) {
      const { browser, page, errors } = await setup(width);
      try {
        const columns = async () => page.locator("[data-feed-grid]").first().evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length);
        await domClick(card(page, "r1").locator("[data-feed-open]"));
        await review(page).waitFor();
        await page.waitForTimeout(250);
        await closeDetail(page, width);
        const columnsBefore = await columns();
        const before = await geometry(page);
        let last = before;
        // Select five items in turn.
        for (const id of ["r1", "r2", "r3", "r4", "r5"]) {
          await domClick(card(page, id).locator("[data-feed-open]"));
          await review(page).waitFor();
          await page.waitForTimeout(250);
          await closeDetail(page, width);
          const now = await geometry(page);
          assertSame(before, now, `selecting ${id}`);
          assert.equal(now.scrollTop, before.scrollTop, `selecting ${id} does not scroll the grid`);
          assert.equal(await columns(), columnsBefore, "the column count stays fixed while the pane is open");
          last = now;
        }
        // Rate two: one from the card, one from the pane.
        await domClick(card(page, "r2").locator("[data-review-choice=accept]"));
        await card(page, "r2").locator("[data-verdict=match]").waitFor();
        await domClick(card(page, "r4").locator("[data-review-choice=reject]"));
        // Asking for a written reason adds one status row to that card (and its grid row): the order and columns never change.
        const asking = await geometry(page);
        assert.deepEqual(asking.cards.map((c) => c.id), before.cards.map((c) => c.id), "asking for a reason: the cards are in the same order");
        for (const [index, c] of before.cards.entries()) assert.ok(Math.abs(asking.cards[index].x - c.x) <= 1 && Math.abs(asking.cards[index].w - c.w) <= 1, `asking for a reason: ${c.id} keeps its column`);
        await card(page, "r4").getByLabel(WHY).fill("Seen this one already.");
        await domClick(card(page, "r4").locator("[data-review-record]"));
        await card(page, "r4").locator("[data-prediction-mark][data-verdict=match]").waitFor();
        await page.waitForTimeout(300);
        assertSame(before, await geometry(page), "rating two items");
        await domClick(card(page, "r3").locator("[data-feed-open]"));
        await review(page).waitFor();
        await domClick(review(page).locator("[data-review-choice=accept]"));
        await page.waitForFunction(() => (window as unknown as { fixtureRequests: unknown[] }).fixtureRequests.length === 3);
        await page.waitForTimeout(300);
        await closeDetail(page, width);
        assertSame(before, await geometry(page), "rating from the pane");
        void last;
        // A background refresh: predictions change (a re-rank would reshuffle everything) and a new item arrives.
        await page.evaluate(() => { (window as unknown as { fixtureReshuffle: () => void; fixtureAddItem: () => void }).fixtureReshuffle(); (window as unknown as { fixtureAddItem: () => void }).fixtureAddItem(); });
        await page.waitForTimeout(400);
        assertSame(before, await geometry(page), "a background refresh");
        const pill = page.locator("[data-feed-new-items]");
        assert.equal((await pill.innerText()).trim(), "1 new item: show", "new items wait behind a quiet pill");
        await pill.click();
        await page.waitForTimeout(300);
        assert.equal(await page.locator("[data-feed-new-items]").count(), 0);
        assert.equal(await page.locator('[data-feed-card="r15"]').count(), 1, "showing the new items brings them in");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
});

/** Where the detail view really scrolls: the pane's own scroll area from 1024, the organizer's scroller (or the window) on a phone. */
const detailScroll = (page: Page, to: "top" | "bottom" | number) => page.evaluate((target) => {
  for (let node: HTMLElement | null = document.querySelector<HTMLElement>("[data-reference-detail-scroll]"); node; node = node.parentElement) {
    if (node.scrollHeight > node.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(node).overflowY)) node.scrollTop = target === "top" ? 0 : target === "bottom" ? 1e6 : target;
  }
  const page = document.scrollingElement; if (page && page.scrollHeight > page.clientHeight + 1) page.scrollTop = target === "top" ? 0 : target === "bottom" ? 1e6 : target;
}, to);
const scrolledOffsets = (page: Page) => page.evaluate(() => {
  const offsets: number[] = [];
  for (let node: HTMLElement | null = document.querySelector<HTMLElement>("[data-reference-detail-scroll]"); node; node = node.parentElement) offsets.push(node.scrollTop);
  offsets.push(document.scrollingElement?.scrollTop ?? 0);
  return Math.max(...offsets);
});
/** PAPYRUS_DETAIL_NAV_SHOTS_DIR=<dir> saves a screenshot at the 390 and 1440 pixel widths. */
const shoot = async (page: Page, width: number, name: string) => {
  const dir = process.env.PAPYRUS_DETAIL_NAV_SHOTS_DIR; if (!dir || (width !== 390 && width !== 1440)) return;
  fs.mkdirSync(dir, { recursive: true }); await page.screenshot({ path: `${dir}/${name}-${width}.png` });
};
const rectOf = (page: Page, selector: string) => page.evaluate((query) => {
  const el = document.querySelector<HTMLElement>(query + ":not([hidden])"); if (!el) return null;
  const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: r.height };
}, selector);
/** Opens the long reference r1 (600 words of captured text) and waits for the text, so there is plenty to scroll. */
const openLong = async (page: Page) => { await open(page, "r1"); await page.locator("[data-capture-text]:visible").waitFor(); await page.waitForTimeout(300); };
const lastContentBottom = (page: Page) => page.evaluate(() => {
  const root = document.querySelector("[data-reference-detail-scroll]")!; let bottom = 0;
  for (const el of root.querySelectorAll("*")) { const r = el.getBoundingClientRect(); if (r.height > 0 && r.bottom > bottom && getComputedStyle(el).position !== "fixed") bottom = r.bottom; }
  return bottom;
});

Object.assign(scenarios, {
  /** The Previous / Next bar stays in view above the tab bar however far the detail is scrolled, and covers nothing at the end. */
  async detail_bar_fixed() {
    for (const [width, height] of [[375, 800], [390, 844], [1440, 900]] as const) {
      const { browser, page, errors } = await setup(width, "?shell");
      try {
        await page.setViewportSize({ width, height });
        await openLong(page);
        const barAt = async (label: string) => {
          const bar = (await rectOf(page, "[data-review-queue-bar]"))!; const tabs = await rectOf(page, ".organizer-bottom-nav");
          assert.ok(bar.height > 30, `${width}: the bar is shown ${label}`);
          assert.ok(bar.top >= 0 && bar.bottom <= height + 1, `${width}: the bar is inside the viewport ${label}: ${JSON.stringify(bar)}`);
          if (width < 1024) assert.ok(tabs && Math.abs(bar.bottom - tabs.top) <= 1, `${width}: the bar sits just above the tab bar ${label}: bar ${bar.bottom}, tabs ${tabs?.top}`);
          else assert.ok(Math.abs(bar.bottom - height) <= 1, `${width}: the bar is at the bottom of the detail pane ${label}: ${bar.bottom}`);
          return bar;
        };
        const top = await barAt("at the top");
        await detailScroll(page, 120); await page.waitForTimeout(150);
        const middle = await barAt("part way down");
        await detailScroll(page, "bottom"); await page.waitForTimeout(300);
        const bottom = await barAt("at the bottom");
        await shoot(page, width, "detail-scrolled-to-bottom");
        assert.ok(Math.abs(top.top - middle.top) <= 1 && Math.abs(top.top - bottom.top) <= 1, `${width}: the bar does not move while the content scrolls`);
        assert.ok(await scrolledOffsets(page) > 100, `${width}: the content really scrolled`);
        const content = await lastContentBottom(page);
        assert.ok(content <= bottom.top + 1, `${width}: the last of the content (${content}) is not covered by the bar (top ${bottom.top})`);
        assert.equal(await page.locator("[data-review-queue-bar]").getByRole("button", { name: "Next" }).isVisible(), true);
        assert.equal(await page.locator("[data-review-queue-bar]").getByRole("button", { name: "Previous" }).isVisible(), true);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Whatever selects a reference, its detail opens at the top with the headline in view. */
  async detail_opens_at_top() {
    for (const [width, height] of [[375, 800], [390, 844], [1440, 900]] as const) {
      const { browser, page, errors } = await setup(width, "?shell");
      try {
        await page.setViewportSize({ width, height });
        const headlineShown = async (id: string, how: string) => {
          await page.waitForFunction((lineage) => document.querySelector(`[data-review-card="${lineage}"]`)?.getBoundingClientRect().height, id);
          await page.waitForTimeout(250);
          assert.equal(await scrolledOffsets(page), 0, `${width}: ${how} opens ${id} scrolled to the top`);
          const bar = (await rectOf(page, "[data-review-queue-bar]"))!;
          const headline = (await page.locator(`[data-review-card="${id}"] h2`).first().boundingBox())!;
          assert.ok(headline.y >= 40 && headline.y + headline.height <= bar.top, `${width}: ${how}: the headline of ${id} is in view (${headline.y}..${headline.y + headline.height}, bar ${bar.top})`);
        };
        await openLong(page);
        await headlineShown("r1", "a card click");
        // Next, from deep in a long reference.
        await detailScroll(page, "bottom"); await page.waitForTimeout(200);
        assert.ok(await scrolledOffsets(page) > 100, `${width}: scrolled down before Next`);
        const queue = page.locator("[data-review-queue-bar]:visible");
        await queue.getByRole("button", { name: "Next" }).click();
        await headlineShown("r2", "Next");
        await shoot(page, width, "detail-after-next");
        // Re-rendering the same reference leaves the scroll alone.
        await detailScroll(page, "bottom"); await page.waitForTimeout(200);
        const kept = await scrolledOffsets(page);
        await page.evaluate(() => (window as unknown as { fixtureReshuffle: () => void }).fixtureReshuffle());
        await page.waitForTimeout(300);
        assert.equal(await scrolledOffsets(page), kept, `${width}: a refresh of the same reference does not move the scroll`);
        // Previous, from deep down again.
        await queue.getByRole("button", { name: "Previous" }).click();
        await headlineShown("r1", "Previous");
        await detailScroll(page, "bottom"); await page.waitForTimeout(200);
        await queue.getByRole("button", { name: "Next" }).click();
        await headlineShown("r2", "Next, again");
        // A card click: on a phone Back shows the feed, which has its own scroll position; on a desktop the pane stays beside the feed.
        await detailScroll(page, "bottom"); await page.waitForTimeout(200);
        await closeDetail(page, width);
        await domClick(card(page, "r4").locator("[data-feed-open]"));
        await review(page).waitFor();
        await headlineShown("r4", "a card click");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
});

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Reference sync scenario passed: ${name}`);
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
