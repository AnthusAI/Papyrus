/** Fixture-only browser acceptance for the Related section and "Linked by editors" at 375 and 1440 pixels. No network beyond the fixture origin. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://related.test";
const shots = process.env.RELATED_SHOTS_DIR;
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
    plugins: [{ name: "fixture-stubs", setup(b) {
      // The References page imports the Amplify client, which reads generated outputs; the fixture never configures it.
      b.onResolve({ filter: /^papyrus-amplify-outputs$/ }, () => ({ path: "papyrus-amplify-outputs", namespace: "fixture-stub" }));
      b.onLoad({ filter: /.*/, namespace: "fixture-stub" }, () => ({ contents: "export default {};", loader: "js" }));
    } }],
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "related-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { ReviewCard } from "./components/reference-review-card";
import { RelatedSection, LinkedByEditors, ConceptDescription } from "./components/related-section";
import { ReferenceLinksStoreProvider, createMemoryReferenceLinksStore } from "./components/reference-links-context";
import { ReferenceCardHeader } from "./components/reference-feed";
import { referenceDatesText } from "./lib/reference-links";
import { NewsroomReferencesView } from "./components/newsroom-references-view";
import { localPreviewReferenceLinkItems, localPreviewReferenceLinks } from "./lib/local-preview-reference-links";

const params = new URLSearchParams(location.search);
const REFERENCE = { lineageId: "preview-reference-lineage-0", id: "preview-reference-0", title: "Fixture reference about harbour dredging" };
const items = localPreviewReferenceLinkItems();
const links = params.has("concept") ? localPreviewReferenceLinks().filter((link) => link.objectKind === "semanticNode" && link.state === "current" && link.id !== "preview-link-1")
  : params.has("noindex") ? localPreviewReferenceLinks().filter((link) => link.id === "preview-link-1")
  : params.has("bare") ? []
  : localPreviewReferenceLinks();
window.calls = [];
const store = createMemoryReferenceLinksStore({
  items, links,
  withoutIndex: params.has("noindex"),
  skipped: params.has("skipped") ? "no reference_summary vector is indexed for this Reference" : params.has("unknownskip") ? "calibration_not_ready: kind=reference" : undefined,
  suggestions: [{ id: "preview-link-9", subjectKind: "reference", subjectLineageId: REFERENCE.lineageId, objectKind: "reference", objectLineageId: "preview-reference-lineage-4", state: "suggested", provenance: "suggested", similarity: 0.66, label: "possible" }],
  onCall: (call) => window.calls.push(call),
});
const withLabels = { ...store };
const labelled = params.has("labels") ? { ...store, listForReference: async (id) => (await store.listForReference(id)).map((entry) => entry.state === "suggested" ? { ...entry, label: entry.item.kind === "concept" ? "likely" : "possible" } : entry) } : store;

function Detail() {
  return <div className="max-w-xl space-y-4" data-fixture-detail>
    <ReviewCard decided={null} itemId={REFERENCE.lineageId} onDecide={async () => undefined} prediction={{ state: "none" }} title={REFERENCE.title} dek="A one line dek for the Reference.">
      <RelatedSection lineageId={REFERENCE.lineageId} referenceId={REFERENCE.id} />
    </ReviewCard>
  </div>;
}
const REFERENCE_PAGE_ROW = { id: "preview-reference-0", lineageId: REFERENCE.lineageId, corpusId: "fixture", externalItemId: "fixture-0", title: REFERENCE.title, sourceUri: "https://records.example.org/council/harbour-dredging-0", sourcePublishedAt: "2026-10-26T09:00:00Z", createdAt: "2026-10-27T08:15:00Z", curationStatus: "accepted", versionState: "current", versionNumber: 1 };
function ReferencesPage() {
  return <div className="max-w-6xl" data-fixture-references-page>
    <NewsroomReferencesView demo={false} disabled={params.has("viewer")} initialReferenceLineageId={REFERENCE.lineageId} loading={false} onReview={async () => undefined} references={[REFERENCE_PAGE_ROW as never]} />
  </div>;
}
function Described() {
  return <article className="wiki-page max-w-xl" data-fixture-described><h1>Fake website networks</h1><ConceptDescription lineageId="semantic-node-editor_concept--fake-website-networks" nodeKind="editor_concept" /><LinkedByEditors conceptLineageId="preview-concept-voice-cloning" /></article>;
}
function Concept() {
  return <article className="wiki-page max-w-xl" data-fixture-concept><h1>Voice cloning</h1><LinkedByEditors conceptLineageId="preview-concept-voice-cloning" /></article>;
}
const DATE_REFERENCES = [
  { id: "d1", lineageId: "d1", title: "Dated to the day", sourceUri: "https://records.example.org/a", sourcePublishedAt: "2026-10-27T09:00:00Z", createdAt: "2026-10-28T08:15:00Z" },
  { id: "d2", lineageId: "d2", title: "Dated to the month", sourceUri: "https://records.example.org/b", sourcePublishedAt: "2026-10-01T00:00:00Z", createdAt: "2026-10-29T08:15:00Z", metadata: { publicationDateResolution: { precision: "month" } } },
  { id: "d3", lineageId: "d3", title: "Dated to the year", sourceUri: "https://records.example.org/c", sourcePublishedAt: "2026-01-01T00:00:00Z", createdAt: "2026-10-29T09:15:00Z", metadata: JSON.stringify({ publicationDateResolution: { precision: "year" } }) },
  { id: "d4", lineageId: "d4", title: "No publication date", sourceUri: "https://records.example.org/d", sourcePublishedAt: null, createdAt: "2026-10-30T08:15:00Z" },
];
function Dates() {
  return <div className="max-w-xl space-y-4" data-fixture-dates>
    {DATE_REFERENCES.map((reference) => <div key={reference.id} className="flex flex-col rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-card)]" data-fixture-feed-card={reference.id}>
      <ReferenceCardHeader now={Date.parse("2026-10-31T00:00:00Z")} preview={undefined} reference={reference as never} />
    </div>)}
    <ReviewCard decided={null} itemId="d2" onDecide={async () => undefined} prediction={{ state: "none" }} title="Dated to the month" dek="Detail header."
      meta={<span className="text-xs text-muted-foreground" data-reference-dates>{referenceDatesText(DATE_REFERENCES[1])}</span>} />
  </div>;
}
createRoot(document.getElementById("root")).render(<ReferenceLinksStoreProvider store={labelled}>{params.has("references") ? <ReferencesPage /> : params.has("dates") ? <Dates /> : params.has("described") ? <Described /> : params.has("concept") ? <Concept /> : <Detail />}</ReferenceLinksStoreProvider>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const darkCss = "html.dark body{background:#16150f;color:#ece8dc;--feed-card:#201e17;--feed-control:#2d2a20;--feed-footer:#26231b;--foreground-muted:#a39e8e;--primary:#c6f432;--primary-foreground:#1c1c1c;--muted-foreground:#a39e8e;--foreground:#ece8dc}html.dark .wiki-empty{color:#a39e8e}";
const fixtureCss = "body{margin:0;font:16px sans-serif;background:#f4f1ea;color:#1c1c1c;--muted-foreground:#6b6b6b;--foreground:#1c1c1c;--feed-card:#fbf9f4;--feed-control:#e8e3d8;--feed-footer:#f0ece2;--feed-radius-xl:12px;--feed-radius-lg:10px;--feed-radius-md:8px;--feed-radius-pill:8px;--feed-quiet:.6;--foreground-muted:#6b6b6b;--feed-verdict-match-fill:#059669;--feed-verdict-miss-fill:#dc2626;--primary:#46560f;--primary-foreground:#fff}button,textarea{font:inherit}h1,h2{margin:.4em 0}.wiki-empty{color:#6b6b6b}";

async function setup(options: string, width: number, height = 1000, dark = false) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html class="${dark ? "dark" : ""}"><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>${fixtureCss}${darkCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/${options}`);
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

const calls = (page: Page) => page.evaluate(() => (window as unknown as { calls: unknown[] }).calls);
const section = (page: Page) => page.locator("[data-related-section]");
const box = (page: Page) => page.locator("[data-related-add] textarea");

async function screenshot(page: Page, name: string, width: number) {
  if (shots) await page.screenshot({ path: `${shots}/related-${name}-${width}.png`, fullPage: true });
}

const scenarios: Record<string, () => Promise<void>> = {
  async marks() {
    await run("?labels=1", [375, 1440], async (page, width) => {
      await section(page).waitFor();
      await page.locator("[data-related-suggested]").waitFor();
      const header = section(page).locator("h3");
      assert.ok((await header.innerText()).includes("Related"));
      assert.equal(await header.locator("svg").count(), 1, "a Lucide link icon in the header");
      const chip = page.locator('[data-related-concept="preview-concept-voice-cloning"]');
      assert.equal(await chip.locator("svg").count(), 1, "a hash icon");
      assert.equal(await chip.locator("[data-related-hashtag]").innerText(), "#voice-cloning");
      const suggested = page.locator('[data-related-suggested="preview-link-3"]');
      const marks = suggested.locator("[data-related-suggestion-marks]");
      assert.ok((await marks.innerText()).includes("Suggested"), "the word Suggested");
      assert.equal(await marks.locator("svg").count(), 1, "a sparkles icon");
      assert.equal(await marks.locator("[data-related-close-match]").innerText(), "close match 0.81");
      assert.equal(await marks.locator("[data-related-likelihood]").innerText(), "likely");
      const card = page.locator('[data-related-reference-card="preview-reference-lineage-1"]');
      assert.ok((await card.locator("[data-related-title]").innerText()).includes("Council minutes"));
      assert.equal(await card.locator("[data-related-host]").innerText(), "records.example.org");
      assert.equal(await card.locator("[data-related-edge]").innerText(), "relates to");
      const suggestedCard = page.locator('[data-related-reference-card="preview-reference-lineage-2"]');
      assert.equal(await suggestedCard.locator("[data-related-likelihood]").innerText(), "possible");
      assert.equal(await suggestedCard.locator("[data-related-close-match]").innerText(), "close match 0.74");
      await screenshot(page, "section", width);
    });
    console.log("Related scenario passed: marks");
  },

  async dates() {
    await run("", [375, 1440], async (page) => {
      await page.locator("[data-related-reference-card]").first().waitFor();
      const cards = page.locator("[data-related-reference-card]");
      const count = await cards.count();
      assert.ok(count >= 2);
      for (let index = 0; index < count; index += 1) {
        assert.match(await cards.nth(index).locator("[data-related-dates]").innerText(), /^published (\d{4}-\d{2}-\d{2}|unknown) · added \d{4}-\d{2}-\d{2}$/);
      }
      assert.equal(await page.locator('[data-related-reference-card="preview-reference-lineage-1"] [data-related-dates]').innerText(), "published 2026-10-27 · added 2026-10-28");
      assert.equal(await page.locator('[data-related-reference-card="preview-reference-lineage-2"] [data-related-dates]').innerText(), "published unknown · added 2026-10-29");
    });
    console.log("Related scenario passed: dates");
  },

  async accept() {
    await run("", [375, 1440], async (page, width) => {
      const suggested = page.locator('[data-related-suggested="preview-link-3"]');
      await suggested.waitFor();
      await suggested.locator('[data-review-choice="accept"]').click();
      await page.locator('[data-related-concept="preview-concept-speech-synthesis"]').waitFor();
      assert.equal(await page.locator('[data-related-suggested="preview-link-3"]').count(), 0, "no longer a suggestion");
      assert.deepEqual((await calls(page)), [{ type: "decide", relationId: "preview-link-3", decision: "accept" }]);
      assert.ok(!(await page.locator('[data-related-concepts]').innerText()).includes("close match 0.81"), "the suggestion marks are gone");
      await screenshot(page, "accepted", width);
    });
    console.log("Related scenario passed: accept");
  },

  async reject() {
    await run("", [375, 1440], async (page, width) => {
      const decision = page.locator('[data-related-decision="preview-link-4"]');
      await decision.waitFor();
      assert.equal(await decision.locator("[data-review-reason] textarea").count(), 1, "the reason box is offered");
      assert.equal(await decision.locator('[data-review-choice="accept"]').count(), 1);
      assert.equal(await decision.locator('[data-review-choice="reject"]').count(), 1);
      await decision.locator("[data-review-reason] textarea").fill("Different harbour.");
      await decision.locator('[data-review-choice="reject"]').click();
      await page.locator('[data-related-reference-card="preview-reference-lineage-2"]').waitFor({ state: "detached" });
      assert.deepEqual(await calls(page), [{ type: "decide", relationId: "preview-link-4", decision: "reject", note: "Different harbour." }]);
      await screenshot(page, "rejected", width);
    });
    console.log("Related scenario passed: reject");
  },

  async addConcept() {
    await run("", [375, 1440], async (page, width) => {
      await box(page).waitFor();
      assert.equal(await box(page).getAttribute("placeholder"), "Type # for a concept, or paste a link or a title");
      await box(page).fill("#anth");
      const result = page.locator('[data-related-result="preview-concept-anthropic"]');
      await result.waitFor();
      assert.ok((await result.innerText()).includes("#anthropic"));
      assert.equal(await result.locator("svg").count(), 1, "a hash icon");
      const fieldWidth = (await box(page).boundingBox())!.width;
      assert.ok(Math.abs((await result.boundingBox())!.width - fieldWidth) < 2, "full width under the box");
      await screenshot(page, "add-concept", width);
      await result.click();
      await page.locator('[data-related-concept="preview-concept-anthropic"]').waitFor();
      assert.equal(await box(page).inputValue(), "", "the box clears");
      assert.deepEqual(await calls(page), [{ type: "create", subjectLineageId: "preview-reference-lineage-0", objectKind: "semanticNode", objectLineageId: "preview-concept-anthropic", predicate: "tagged_with" }]);
      await box(page).fill("#translation");
      assert.ok((await page.locator('[data-related-result="preview-concept-translation"]').innerText()).includes("#translation (concept)"), "a shared name says its kind");
      assert.equal(await page.locator('[data-related-result="preview-task-translation"]').count(), 1);
    });
    console.log("Related scenario passed: addConcept");
  },

  async addReference() {
    await run("", [375, 1440], async (page, width) => {
      await box(page).waitFor();
      await box(page).fill("https://audits.example.net/port/q2");
      const byLink = page.locator('[data-related-result="preview-reference-lineage-3"]');
      await byLink.waitFor();
      assert.ok((await byLink.innerText()).includes("audits.example.net"));
      assert.ok((await byLink.innerText()).includes("published 2026-09-30 · added 2026-10-30"));
      await box(page).fill("contractor");
      const byTitle = page.locator('[data-related-result="preview-reference-lineage-4"]');
      await byTitle.waitFor();
      await screenshot(page, "add-reference", width);
      await byTitle.click();
      await page.locator('[data-related-reference-card="preview-reference-lineage-4"]').waitFor();
      assert.deepEqual(await calls(page), [{ type: "create", subjectLineageId: "preview-reference-lineage-0", objectKind: "reference", objectLineageId: "preview-reference-lineage-4", predicate: "related_to" }]);
    });
    console.log("Related scenario passed: addReference");
  },

  async noIndex() {
    await run("?noindex=1", [375, 1440], async (page, width) => {
      await page.locator('[data-related-concept="preview-concept-voice-cloning"]').waitFor();
      await page.locator("[data-related-suggest-more]").click();
      const note = page.locator("[data-related-suggest-note]");
      await note.waitFor();
      assert.equal((await note.innerText()).trim(), "Suggestions need the knowledge index");
      assert.equal(await page.locator('[data-related-concept="preview-concept-voice-cloning"]').count(), 1, "confirmed links stay");
      await box(page).fill("#anthropic");
      await page.locator('[data-related-result="preview-concept-anthropic"]').click();
      await page.locator('[data-related-concept="preview-concept-anthropic"]').waitFor();
      await screenshot(page, "no-index", width);
    });
    console.log("Related scenario passed: noIndex");
  },

  async concept() {
    await run("?concept=1", [375, 1440], async (page, width) => {
      const list = page.locator("[data-linked-by-editors-list]");
      await list.locator("[data-related-reference-card]").first().waitFor();
      assert.ok((await page.locator("[data-wiki-section='linked-by-editors'] h2").innerText()).includes("Linked by editors"));
      assert.equal(await list.locator("[data-related-reference-card]").count(), 2);
      assert.equal(await list.locator('[data-related-reference-card="preview-reference-lineage-3"] [data-related-dates]').innerText(), "published 2026-09-30 · added 2026-10-30");
      assert.equal(await list.locator('[data-related-reference-card="preview-reference-lineage-2"] [data-related-dates]').innerText(), "published unknown · added 2026-10-29");
      assert.equal(await box(page).getAttribute("placeholder"), "Paste a link or a title");
      await box(page).fill("https://letters.example.org/dredging-letter");
      await screenshot(page, "concept", width);
      await page.locator('[data-related-result="preview-reference-lineage-4"]').click();
      await list.locator('[data-related-reference-card="preview-reference-lineage-4"]').waitFor();
      assert.deepEqual(await calls(page), [{ type: "create", subjectLineageId: "preview-reference-lineage-4", objectKind: "semanticNode", objectLineageId: "preview-concept-voice-cloning", predicate: "tagged_with" }]);
    });
    console.log("Related scenario passed: concept");
  },

  async referenceDates() {
    await run("?dates=1", [375, 1440], async (page, width) => {
      const feed = (id: string) => page.locator(`[data-fixture-feed-card="${id}"] [data-feed-dates]`).innerText();
      assert.equal(await feed("d1"), "published 2026-10-27 · added 2026-10-28");
      assert.equal(await feed("d2"), "published Oct 2026 · added 2026-10-29");
      assert.equal(await feed("d3"), "published 2026 · added 2026-10-29");
      assert.equal(await feed("d4"), "published unknown · added 2026-10-30");
      assert.equal(await page.locator("[data-reference-dates]").innerText(), "published Oct 2026 · added 2026-10-29");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
      if (shots) await page.screenshot({ path: `${shots}/dates-feed-and-detail-${width}.png`, fullPage: true });
    });
    console.log("Related scenario passed: referenceDates");
  },

  async referencesPage() {
    for (const [width, height] of [[390, 844], [1440, 900]]) {
      for (const dark of [false, true]) {
        const { browser, page, errors } = await setup("?references=1&labels=1", width, height, dark);
        try {
          const detail = page.locator("[data-news-desk-reference-detail]");
          await detail.waitFor();
          const related = detail.locator("[data-related-section]");
          await related.waitFor();
          await related.locator("[data-related-suggested]").first().waitFor();
          assert.ok((await related.locator("h3").innerText()).includes("Related"));
          assert.ok(await related.locator("[data-related-suggestion-marks]").count() >= 2, "suggestions are visible on the References page");
          assert.equal(await related.locator('[data-review-choice="accept"]').count() > 0, true, "Accept and Reject are offered");
          assert.equal(await page.locator("[data-related-section]").count(), 1, "one Related section");
          const order = await detail.evaluate((root) => {
            const section = root.querySelector("[data-related-section]");
            const conversation = root.querySelector("[data-reference-conversation]");
            return section && conversation ? Boolean(section.compareDocumentPosition(conversation) & Node.DOCUMENT_POSITION_FOLLOWING) : true;
          });
          assert.equal(order, true, "Related comes before messages");
          assert.equal(await related.locator("[data-related-reference-card] a").first().getAttribute("href") !== null, true, "Reference cards link to their detail");
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
          if (shots) {
            fs.mkdirSync(`${shots}/references`, { recursive: true });
            await detail.scrollIntoViewIfNeeded();
            await related.scrollIntoViewIfNeeded();
            await page.screenshot({ path: `${shots}/references/references-related-${width}x${height}-${dark ? "dark" : "light"}.png`, fullPage: true });
          }
          assert.deepEqual(errors, []);
        } finally { await browser.close(); }
      }
    }
    console.log("Related scenario passed: referencesPage");
  },

  async referencesViewer() {
    await run("?references=1&viewer=1", [390], async (page) => {
      const related = page.locator("[data-related-section]");
      await related.waitFor();
      assert.ok((await related.innerText()).includes("Editor access is required to change links."));
      assert.equal(await related.locator("[data-related-suggest-more]").isDisabled(), true);
      assert.equal(await related.locator("[data-related-add] textarea").isDisabled(), true);
    });
    console.log("Related scenario passed: referencesViewer");
  },

  /** A Reference opened with no links and never tried gets its suggestions once, without a click, and they show when the call returns. */
  async autoSuggest() {
    await run("?bare=1", [375, 1440], async (page, width) => {
      await page.locator('[data-related-reference-card="preview-reference-lineage-4"]').waitFor();
      const made = (await calls(page)).filter((call) => (call as { type?: string }).type === "suggest");
      assert.equal(made.length, 1, "asked once, by itself");
      assert.equal(await page.locator("[data-related-suggest-more]").isDisabled(), false, "the button is back once the answer came");
      await screenshot(page, "auto-suggest", width);
    });
    console.log("Related scenario passed: autoSuggest");
  },

  /** Inventing a concept by typing its hashtag: one button, one tap or Enter, no duplicate of an existing name, and a double tap makes one. */
  async createConcept() {
    const slug = "fake-website-networks";
    for (const width of [375, 1440]) {
      for (const dark of [false, true]) {
        const { browser, page, errors } = await setup("?bare=1", width, 1000, dark);
        try {
          await page.locator("[data-related-add] textarea").waitFor();
          await box(page).fill("#Fake Website Networks");
          const create = page.locator(`[data-related-create="${slug}"]`);
          await create.waitFor();
          assert.equal((await create.innerText()).trim(), `Create #${slug} and tag this`);
          assert.equal(await create.locator("svg").count() >= 1, true, "a Lucide icon");
          if (shots) { fs.mkdirSync(`${shots}/hashtag-concepts`, { recursive: true }); await page.screenshot({ path: `${shots}/hashtag-concepts/create-action-${width}-${dark ? "dark" : "light"}.png`, fullPage: true }); }
          await create.dblclick();   // a double tap
          await page.locator(`[data-related-concept="semantic-node-editor_concept--${slug}"]`).waitFor();
          const made = (await calls(page)).filter((call) => (call as { type?: string }).type === "createConceptAndTag");
          assert.equal(made.length, 1, "a double tap asks once");
          assert.equal(await page.locator(`[data-related-concept="semantic-node-editor_concept--${slug}"]`).count(), 1, "one chip");
          assert.equal(await box(page).inputValue(), "", "the box clears");
          assert.deepEqual(errors, []);
        } finally { await browser.close(); }
      }
    }
    // Enter creates too; an existing name offers itself and no second concept.
    await run("?bare=1", [375], async (page) => {
      await box(page).fill("#brand new idea");
      await page.locator('[data-related-create="brand-new-idea"]').waitFor();
      await box(page).press("Enter");
      await page.locator('[data-related-concept="semantic-node-editor_concept--brand-new-idea"]').waitFor();
      await box(page).fill("#voice-cloning");
      await page.locator('[data-related-result="preview-concept-voice-cloning"]').waitFor();
      assert.equal(await page.locator("[data-related-create]").count(), 0, "an existing concept is not created again");
    });
    console.log("Related scenario passed: createConcept");
  },

  /** The page of an editor's concept: add the description in place. */
  async conceptDescription() {
    for (const width of [375, 1440]) {
      for (const dark of [false, true]) {
        const { browser, page, errors } = await setup("?described=1", width, 1000, dark);
        try {
          await page.locator("[data-concept-description-edit]").click();
          await page.locator("[data-concept-description-input]").fill("Sites made to look like independent news outlets.");
          if (shots) { fs.mkdirSync(`${shots}/hashtag-concepts`, { recursive: true }); await page.screenshot({ path: `${shots}/hashtag-concepts/concept-page-${width}-${dark ? "dark" : "light"}.png`, fullPage: true }); }
          await page.locator("[data-concept-description-save]").click();
          await page.getByText("Sites made to look like independent news outlets.").waitFor();
          const saved = (await calls(page)).filter((call) => (call as { type?: string }).type === "describeConcept");
          assert.equal(saved.length, 1);
          assert.equal(await page.locator("[data-concept-description-edit]").innerText(), "Edit description");
          assert.deepEqual(errors, []);
        } finally { await browser.close(); }
      }
    }
    console.log("Related scenario passed: conceptDescription");
  },

  async skipNotes() {
    const cases: Array<[string, string]> = [
      ["?skipped=1", "Suggestions appear once this Reference has a summary."],
      ["?unknownskip=1", "No suggestions could be made for this Reference yet."],
    ];
    for (const [options, expected] of cases) {
      await run(options, [390, 1440], async (page, width) => {
        await page.locator("[data-related-concept]").first().waitFor();
        await page.locator("[data-related-suggest-more]").click();
        const note = page.locator("[data-related-suggest-note]");
        await note.waitFor();
        const text = (await note.innerText()).trim();
        assert.equal(text, expected);
        assert.ok(!/vector|indexed|reference_summary|calibration|kind=/.test(text), "no internal wording");
        if (shots && options === "?skipped=1") {
          fs.mkdirSync(`${shots}/references`, { recursive: true });
          await page.screenshot({ path: `${shots}/references/suggest-skipped-plain-${width}.png`, fullPage: true });
        }
      });
    }
    console.log("Related scenario passed: skipNotes");
  },

  async explanationsShown() {
    await run("", [375, 1440], async (page) => {
      const concept = page.locator('[data-related-concept-entry="preview-link-1"]');
      await concept.waitFor();
      assert.ok((await concept.locator("[data-related-explanation-text]").innerText()).includes("voice cloning for harbour announcements"), "the words show under the concept chip");
      assert.equal(await concept.locator("[data-related-explanation-byline]").innerText(), "Written by an editor on 2026-10-30", "who and when, in words");
      assert.equal(await concept.locator("[data-related-explanation] svg").count() >= 1, true, "a Lucide quote icon");
      const card = page.locator('[data-related-reference-card="preview-reference-lineage-1"]');
      assert.equal(await card.locator("[data-related-explanation-text]").innerText(), "The minutes are the council vote that this Reference reports on.");
      assert.equal(await card.locator("[data-related-explanation-byline]").innerText(), "Written by an editor on 2026-10-31");
      assert.equal(await page.locator("[data-related-suggested] [data-related-explanation]").count(), 0, "a suggestion has no explanation");
      assert.equal(await page.locator('[data-related-decision] [data-related-explanation-add]').count(), 0);
      assert.equal(await concept.locator("[data-related-explanation-edit]").innerText(), "Edit", "the button says what it does");
    });
    console.log("Related scenario passed: explanationsShown");
  },

  /** Edit in place: the words change, the decision call keeps the link accepted, and the page shows the new words and who wrote them. */
  async explanationsEdited() {
    await run("", [375, 1440], async (page) => {
      const card = page.locator('[data-related-reference-card="preview-reference-lineage-1"]');
      await card.locator("[data-related-explanation-edit]").click();
      const input = card.locator("[data-related-explanation-input]");
      assert.equal(await input.inputValue(), "The minutes are the council vote that this Reference reports on.");
      assert.equal(await input.evaluate((element) => element.tagName), "TEXTAREA");
      await input.fill("The minutes record the vote on the dredging contract.");
      await card.locator("[data-related-explanation-save]").click();
      await card.locator("[data-related-explanation-edit]").waitFor();
      assert.equal(await card.locator("[data-related-explanation-text]").innerText(), "The minutes record the vote on the dredging contract.");
      assert.match(await card.locator("[data-related-explanation-byline]").innerText(), /^Written by an editor on \d{4}-\d{2}-\d{2}$/);
      assert.deepEqual(await calls(page), [{ type: "decide", relationId: "preview-link-2", decision: "accept", note: "The minutes record the vote on the dredging contract." }]);
    });
    console.log("Related scenario passed: explanationsEdited");
  },

  /** Cancel changes nothing; clearing the words saves an empty note and leaves the offer to add some. */
  async explanationsCleared() {
    await run("", [375], async (page) => {
      const concept = page.locator('[data-related-concept-entry="preview-link-1"]');
      await concept.locator("[data-related-explanation-edit]").click();
      await concept.locator("[data-related-explanation-input]").fill("Changed my mind");
      await concept.locator("[data-related-explanation-cancel]").click();
      assert.ok((await concept.locator("[data-related-explanation-text]").innerText()).includes("harbour announcements"));
      assert.deepEqual(await calls(page), []);
      await concept.locator("[data-related-explanation-edit]").click();
      await concept.locator("[data-related-explanation-input]").fill("   ");
      await concept.locator("[data-related-explanation-save]").click();
      await concept.locator("[data-related-explanation-add]").waitFor();
      assert.deepEqual(await calls(page), [{ type: "decide", relationId: "preview-link-1", decision: "accept", note: "" }]);
    });
    console.log("Related scenario passed: explanationsCleared");
  },

  /** Accepting a suggestion with a reason makes the reason its explanation. */
  async explanationsFromReason() {
    await run("", [375], async (page) => {
      const suggested = page.locator('[data-related-suggested="preview-link-3"]');
      await suggested.locator("[data-review-reason] textarea").fill("Both are about the same synthetic voices.");
      await suggested.locator('[data-review-choice="accept"]').click();
      const accepted = page.locator('[data-related-concept-entry="preview-link-3"]');
      await accepted.locator("[data-related-explanation-text]").waitFor();
      assert.equal(await accepted.locator("[data-related-explanation-text]").innerText(), "Both are about the same synthetic voices.");
    });
    console.log("Related scenario passed: explanationsFromReason");
  },

  /** A link with no words offers Add explanation. */
  async explanationsOnConceptPage() {
    await run("?concept=1", [375, 1440], async (page) => {
      const list = page.locator("[data-linked-by-editors-list]");
      await list.locator("[data-related-reference-card]").first().waitFor();
      assert.ok((await list.locator('[data-related-reference-card="preview-reference-lineage-3"] [data-related-explanation-text]').innerText()).includes("audit prices the voice-cloning contract"));
      const bare = list.locator('[data-related-reference-card="preview-reference-lineage-2"]');
      assert.equal(await bare.locator("[data-related-explanation-text]").count(), 0);
      await bare.locator("[data-related-explanation-add]").click();
      await bare.locator("[data-related-explanation-input]").fill("The hearing is where the concept first came up.");
      await bare.locator("[data-related-explanation-save]").click();
      await bare.locator("[data-related-explanation-text]").waitFor();
      assert.deepEqual(await calls(page), [{ type: "decide", relationId: "preview-link-6", decision: "accept", note: "The hearing is where the concept first came up." }]);
    });
    console.log("Related scenario passed: explanationsOnConceptPage");
  },

  async explanationViewer() {
    await run("?references=1&viewer=1", [390], async (page) => {
      const related = page.locator("[data-related-section]");
      await related.waitFor();
      await related.locator("[data-related-explanation-text]").first().waitFor();
      assert.ok(await related.locator("[data-related-explanation-text]").count() >= 2, "the words are readable");
      assert.equal(await related.locator("[data-related-explanation-edit], [data-related-explanation-add], [data-related-explanation-input]").count(), 0, "read-only for a viewer");
    });
    console.log("Related scenario passed: explanationViewer");
  },

  async explanationShots() {
    if (shots) fs.mkdirSync(shots, { recursive: true });
    for (const [width, height] of [[390, 844], [1440, 900]]) {
      for (const dark of [false, true]) {
        const { browser, page, errors } = await setup("?references=1", width, height, dark);
        try {
          const related = page.locator("[data-related-section]");
          await related.waitFor();
          await related.locator("[data-related-explanation-text]").first().waitFor();
          const name = `${width}x${height}-${dark ? "dark" : "light"}`;
          await related.scrollIntoViewIfNeeded();
          if (shots) await page.screenshot({ path: `${shots}/explanation-showing-${name}.png`, fullPage: true });
          await related.locator('[data-related-concept-entry="preview-link-1"] [data-related-explanation-edit]').click();
          await related.locator("[data-related-explanation-input]").waitFor();
          if (shots) await page.screenshot({ path: `${shots}/explanation-editing-${name}.png`, fullPage: true });
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
          assert.deepEqual(errors, []);
        } finally { await browser.close(); }
      }
    }
    console.log("Related scenario passed: explanationShots");
  },

  async design() {
    await run("", [375, 1440], async (page) => {
      await page.locator("[data-related-suggested]").waitFor();
      await page.locator("[data-related-explanation-edit]").first().click();
      await page.locator("[data-related-explanation-input]").waitFor();
      const offenders = await page.locator("[data-related-section], [data-related-section] *").evaluateAll((elements) => elements.flatMap((element) => {
        const style = getComputedStyle(element);
        const edges = ["top", "right", "bottom", "left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge}-width`)) > 0 && style.getPropertyValue(`border-${edge}-style`) !== "none");
        const outline = parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== "none";
        return edges || outline ? [element.tagName.toLowerCase()] : [];
      }));
      assert.deepEqual(offenders, [], "no borders or outlines");
      assert.equal(await section(page).locator("select").count(), 0, "no drop-downs");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
    });
    console.log("Related scenario passed: design");
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
