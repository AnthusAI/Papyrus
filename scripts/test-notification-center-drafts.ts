/** Fixture-only browser acceptance for the Notification Center's AI-draft reviews and the Needs attention suggestions. No production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://notification-center.test";
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
      builder.onResolve({ filter: /(review-client|proposals-client)$/ }, () => ({ path: "network", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/link$/ }, () => ({ path: "link", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({
        contents: path === "navigation"
          ? "export const usePathname = () => window.location.pathname; export const useRouter = () => ({ push(href) { window.pushed = href; } });"
          : path === "link"
            ? "import {createElement} from 'react'; export default function Link({href, children, prefetch, ...rest}) { return createElement('a', {href, ...rest}, children); }"
            : path === "network"
              ? "export const loadReviews = async () => ({ state: 'ready', requests: [], readIds: [], userKey: 'u1' }); export const loadDrafts = async () => ({ drafts: {}, missing: [], failed: [] }); export const loadStoryTitles = async () => ({ titles: {}, deleted: [] }); export const markReviewRead = async () => {};"
              : "export {};",
        loader: "js", resolveDir: root,
      }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "notification-center-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NotificationCenter } from "./components/notification-center";
import { NewsroomOpsOverview } from "./components/newsroom-ops-overview";
import { FIXTURE_DRAFTS, FIXTURE_REVIEW_REQUESTS } from "./lib/review-fixture";
import { answerUpdate } from "./lib/review-requests";
import { draftDecisionUpdate, draftView } from "./lib/review-drafts";

const params = new URLSearchParams(location.search);
const clone = (value) => JSON.parse(JSON.stringify(value));
const batch = clone(FIXTURE_REVIEW_REQUESTS.find((request) => request.id === "rr-soft-2"));
if (params.has("no-deadline")) batch.deadline = null;
const hard = clone(FIXTURE_REVIEW_REQUESTS.find((request) => request.id === "rr-hard-1"));
let requests = params.has("only-batch") ? [batch] : [hard, batch];
const rows = clone(FIXTURE_DRAFTS);
for (const row of rows) {
  if (params.has("decided-elsewhere")) row.state = row.id === "proposal-2" ? "declined" : "approved";
  if (params.has("held") && row.id === "proposal-1") row.held = true;
}
if (params.has("missing")) batch.links = [{ type: "proposal", id: "legacy-idea-1", label: "story idea 1" }, { type: "proposal", id: "legacy-idea-2", label: "story idea 2" }];
if (params.has("partly-missing")) batch.links = [...batch.links.slice(0, 1), { type: "proposal", id: "legacy-idea-9", label: "story idea 9" }];
window.calls = [];
let failLoads = params.has("fail-load") ? 1 : 0;
const api = {
  loadReviews: async () => ({ state: "ready", requests: clone(requests), readIds: [], userKey: "u1" }),
  loadStoryTitles: async () => ({ titles: {}, deleted: [] }),
  loadDrafts: async (ids) => {
    if (failLoads > 0) { failLoads -= 1; return { drafts: {}, missing: [], failed: ids }; }
    const known = ids.filter((id) => rows.some((row) => row.id === id));
    return { drafts: Object.fromEntries(known.map((id) => [id, draftView(rows.find((row) => row.id === id))])), missing: ids.filter((id) => !known.includes(id)), failed: [] };
  },
  transitionProposalPath: async (id, path) => {
    window.calls.push({ type: "transition", id, path });
    if (params.has("refuse")) return { status: "refused", message: "The proposal changed under you. Open it in Proposals." };
    rows.find((row) => row.id === id).state = path[path.length - 1];
    return { status: "ok" };
  },
  saveDraftDecision: async (request, draftId, decision) => {
    window.calls.push({ type: "decision", draftId, decision });
    const update = draftDecisionUpdate(request, draftId, decision);
    const saved = { ...request, links: JSON.parse(update.links), history: JSON.parse(update.history) };
    requests = requests.map((entry) => entry.id === saved.id ? saved : entry);
    return saved;
  },
  answerReviewRequest: async (request, input, by) => {
    const update = answerUpdate(request, input, by, new Date("2026-10-24T09:00:00Z"));
    window.calls.push({ type: "answer", requestId: request.id, by, answer: JSON.parse(update.answer) });
    const saved = { ...request, state: "answered", answer: JSON.parse(update.answer), links: update.links ? JSON.parse(update.links) : request.links, updatedAt: update.updatedAt };
    requests = requests.map((entry) => entry.id === saved.id ? saved : entry);
    return saved;
  },
  markReviewRead: async () => {},
};

const decision = { decisionRelationId: "d1", decisionId: "p1", label: "include", confidence: 0.82, version: null, reviewRecommended: false, reviewReason: "program", reviewDetail: null, classes: ["include", "exclude"], positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null };
const references = [
  { id: "reference-a-v1", lineageId: "reference-a", versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: "a", title: "ReadyArt: text-generation model", sourceUri: "https://example.org/a", curationStatus: "pending", importedAt: "2026-10-26T10:00:00Z" },
  { id: "reference-b-v1", lineageId: "reference-b", versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: "b", title: "Another pending source", sourceUri: "https://example.org/b", curationStatus: "pending", importedAt: "2026-10-25T10:00:00Z" },
];
function Fixture() {
  if (params.has("overview")) {
    return <NewsroomOpsOverview assignments={[]} decisions={new Map([["reference-a", decision]])} newsroomSections={[]} references={references} onReview={async (reference, action, options) => { window.calls.push({ type: "rate", id: reference.lineageId, action, options }); }} />;
  }
  return <NotificationCenter actorLabel="Ed Itor" api={api} decisions={new Map()} demo={false} humanCuratedReferenceLineageIds={new Set()} references={[]} />;
}
createRoot(document.getElementById("root")).render(<Fixture />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = "body{margin:0;font:16px sans-serif}button,textarea{font:inherit}";

export async function setup(options = "", width = 1440) {
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
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom${options}`);
  return { browser, page, errors };
}

type Call = { type: string; by?: string; id?: string; path?: string[]; requestId?: string; answer?: Record<string, unknown>; draftId?: string; decision?: Record<string, unknown> };
const calls = (page: Page) => page.evaluate(() => (window as unknown as { calls: Call[] }).calls);
const draft = (page: Page, id: string) => page.locator(`[data-review-draft="${id}"]`);
const choice = (page: Page, id: string, which: "accept" | "reject") => draft(page, id).locator(`[data-review-choice="${which}"]`);
const WORDS_GONE = ["Approve", "Steer with this note", "Steering note", "Agree", "Overrule", "Proceeds automatically", "unless you steer", "draft batches", "Mark all read"];
/** Rejecting asks what the AI should learn; either answer saves it. */
const reject = async (page: Page, id: string, kind: "not_this_kind" | "just_this" = "just_this") => {
  await choice(page, id, "reject").click();
  await draft(page, id).locator(`[data-review-reason="${kind}"]`).click();
};
const answered = (page: Page) => page.waitForFunction(() => (window as unknown as { calls: { type: string }[] }).calls.some((call) => call.type === "answer"));

async function run(options: string, widths: number[], body: (page: Page, width: number) => Promise<void>) {
  for (const width of widths) {
    const { browser, page, errors } = await setup(options, width);
    try {
      await body(page, width);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  }
}

const scenarios: Record<string, () => Promise<void>> = {
  /** Each draft is its own card, shown so it can be judged in place; the batch is only a caption. */
  async content() {
    await run("?only-batch=1", [375, 1440], async (page, width) => {
      await draft(page, "proposal-1").waitFor();
      const first = draft(page, "proposal-1");
      const text = await first.innerText();
      for (const expected of ["Sparse attention goes open", "Open-weight models are adopting sparse attention", "Section: Research", "Evidence:", "32 items in the last 2 weeks", "example.org", "from Idea pipeline · Oct 23", "Open full draft"]) {
        assert.ok(text.includes(expected), `draft 1 shows: ${expected}`);
      }
      assert.equal(await first.locator('a[href="https://example.org/sparse-attention"]').count(), 1, "a source chip links to its address");
      assert.equal(await first.locator("[data-draft-open]").getAttribute("href"), "/newsroom/administration/proposals?proposal=proposal-1");
      const monitor = await draft(page, "proposal-2").innerText();
      assert.ok(monitor.includes("Found by the arxiv-cs monitor."), "a monitor story names its monitor");
      assert.equal(await page.locator("[data-review-draft]").count(), 3, "a request covering three drafts is three cards");
      assert.equal(await page.locator("[data-review-drafts]").count(), 0, "no batch container");
      const body = await page.locator("body").innerText();
      assert.ok(body.includes("What needs me?") && body.includes("3 drafts waiting for you"), "the header counts drafts, not batches");
      for (const word of WORDS_GONE) assert.ok(!body.includes(word), `retired wording gone: ${word}`);
      assert.equal(await page.locator("[data-review-draft] [data-review-choice]").count(), 6, "Accept and Reject on every draft");
      assert.equal(await page.locator("[data-review-draft] [data-review-row=cyclotron]").count(), 0, "no prediction row for a draft");
      for (const which of ["accept", "reject"] as const) {
        assert.equal(await choice(page, "proposal-1", which).getAttribute("aria-disabled"), null, "never silently disabled");
        assert.ok((await choice(page, "proposal-1", which).boundingBox())!.height >= 48, "large tap target");
      }
      const geometry = await page.evaluate(() => {
        const card = document.querySelector('[data-review-draft="proposal-1"]')!.getBoundingClientRect();
        const why = document.querySelector('[data-review-draft="proposal-1"] textarea')!.getBoundingClientRect();
        return { card: card.width, why: why.width, scrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
      });
      assert.ok(geometry.why >= geometry.card - 28, `the Why box spans the card at ${width}px (${geometry.why} of ${geometry.card})`);
      assert.ok(geometry.scrollX <= 0, `no horizontal scroll at ${width}px`);
      // Grid: 1 column on a phone, 3 on a wide screen.
      const columns = await page.evaluate(() => new Set([...document.querySelectorAll("[data-review-draft]")].map((card) => Math.round(card.getBoundingClientRect().left))).size);
      assert.equal(columns, width < 640 ? 1 : 3, `columns at ${width}px`);
      // No borders, no lines: nothing on a card has a border width.
      assert.equal(await page.evaluate(() => [...document.querySelectorAll("[data-review-draft], [data-review-draft] *")].filter((node) => parseFloat(getComputedStyle(node).borderTopWidth) > 0 && getComputedStyle(node).borderTopStyle !== "none").length), 0, "no borders on cards");
      for (const svg of await page.locator("#root svg").all()) assert.ok(await svg.evaluate((node) => [...node.classList].some((name) => name.startsWith("lucide"))), "every icon is a Lucide icon");
      assert.equal(await page.locator("#root select").count(), 0, "no dropdowns");
    });
  },

  /** Accept approves the Proposal, Reject declines it, and the request closes itself with every decision recorded. */
  async decide() {
    await run("?only-batch=1", [375, 1440], async (page) => {
      await draft(page, "proposal-1").waitFor();
      await choice(page, "proposal-1", "accept").click();
      await draft(page, "proposal-1").locator('[data-draft-decided="accept"]').waitFor();
      assert.deepEqual((await calls(page)).filter((call) => call.type === "transition"), [{ type: "transition", id: "proposal-1", path: ["in_steering", "editor_review", "approved"] }], "a draft is walked to approved");
      assert.equal((await calls(page)).filter((call) => call.type === "answer").length, 0, "the request stays open while drafts wait");
      assert.ok((await page.locator("body").innerText()).includes("2 drafts waiting for you"));
      assert.equal(await page.locator("[data-review-draft]").count(), 3, "the decided card stays in place, showing its answer");

      await draft(page, "proposal-2").getByLabel("Why? (optional)").fill("Too thin for a story.");
      await choice(page, "proposal-2", "reject").click();
      assert.ok((await draft(page, "proposal-2").innerText()).includes("What should the AI learn from it?"), "Reject asks one question");
      await draft(page, "proposal-2").locator('[data-review-reason="not_this_kind"]').click();
      await draft(page, "proposal-2").locator('[data-draft-decided="reject"]').waitFor();
      await choice(page, "proposal-3", "accept").click();
      await answered(page);

      const all = await calls(page);
      assert.deepEqual(all.filter((call) => call.type === "transition").map((call) => [call.id, call.path]), [
        ["proposal-1", ["in_steering", "editor_review", "approved"]], ["proposal-2", ["declined"]], ["proposal-3", ["approved"]],
      ]);
      const answer = all.find((call) => call.type === "answer")!;
      assert.equal(answer.by, "Ed Itor");
      assert.equal(answer.answer!.decision, "feedback", "a mix of Accept and Reject is an answer with a note");
      assert.equal(answer.answer!.steer, "not_this_kind", "the answer to the one question is the steering signal");
      assert.match(String(answer.answer!.feedback), /Rejected "A new quantisation paper challenges 4-bit defaults" as not this kind of story: Too thin for a story\./);
      assert.equal((answer.answer!.drafts as unknown[]).length, 3, "every decision is recorded");
      const text = await page.locator("body").innerText();
      assert.ok(text.includes("All caught up"), "nothing is left waiting");
      assert.ok(text.includes("Rejected as not this kind: Too thin for a story."));
      assert.equal(await page.locator('[data-recent-decision]').count(), 3, "what was decided is listed under Recently decided");
      for (const word of WORDS_GONE) assert.ok(!text.includes(word), `retired wording gone: ${word}`);
    });
  },

  /** Accepting all is one approval; rejecting all is one rejection, neither is a steer. */
  async uniform() {
    await run("?only-batch=1", [1440], async (page) => {
      for (const id of ["proposal-1", "proposal-2"]) await choice(page, id, "accept").click().then(() => draft(page, id).locator('[data-draft-decided="accept"]').waitFor());
      await choice(page, "proposal-3", "accept").click();
      await answered(page);
      const answer = (await calls(page)).find((call) => call.type === "answer")!.answer!;
      assert.equal(answer.decision, "approve");
      assert.equal(answer.steer, null);
      assert.equal(answer.feedback, null);
    });
    await run("?only-batch=1", [1440], async (page) => {
      for (const id of ["proposal-1", "proposal-2"]) await reject(page, id).then(() => draft(page, id).locator('[data-draft-decided="reject"]').waitFor());
      await reject(page, "proposal-3");
      await answered(page);
      const answer = (await calls(page)).find((call) => call.type === "answer")!.answer!;
      assert.equal(answer.decision, "reject");
      assert.equal(answer.steer, null, "a plain rejection is not a not-this-kind steer");
    });
  },

  /** A refusal is said in words, the draft stays undecided and the buttons stay usable. */
  async refusal() {
    await run("?only-batch=1&refuse=1", [375, 1440], async (page) => {
      await choice(page, "proposal-1", "accept").click();
      await draft(page, "proposal-1").getByRole("alert").waitFor();
      assert.match(await draft(page, "proposal-1").getByRole("alert").innerText(), /The proposal changed under you/);
      assert.equal(await choice(page, "proposal-1", "accept").getAttribute("aria-disabled"), null);
      assert.equal((await calls(page)).filter((call) => call.type !== "transition").length, 0, "nothing is recorded for a refused move");
    });
    await run("?only-batch=1&held=1", [1440], async (page) => {
      const text = await draft(page, "proposal-1").innerText();
      assert.ok(text.includes("This draft is on hold in Proposals. Release the hold there before you decide it."), "a hold is named, not hidden");
      assert.equal(await choice(page, "proposal-1", "accept").getAttribute("aria-disabled"), "true");
      await choice(page, "proposal-1", "accept").dispatchEvent("click");
      assert.equal((await calls(page)).length, 0, "no move while on hold");
    });
  },

  /** Drafts decided in Proposals close the request; drafts that are not Proposals fall back to Accept or Reject on the request. */
  async closing() {
    await run("?only-batch=1&decided-elsewhere=1", [1440], async (page) => {
      await answered(page);
      const answer = (await calls(page)).find((call) => call.type === "answer")!;
      assert.equal(answer.by, "an editor in Proposals");
      assert.equal(answer.answer!.decision, "feedback");
    });
    await run("?only-batch=1&missing=1", [375, 1440], async (page) => {
      await page.locator("[data-review-request] [data-review-controls]").waitFor();
      const text = await page.locator("body").innerText();
      assert.ok(text.includes("2 of these drafts are not in Proposals on this site"), "unopenable drafts are said, not hidden");
      await page.locator('[data-review-controls] [data-review-choice="accept"]').click();
      await answered(page);
      assert.equal((await calls(page)).find((call) => call.type === "answer")!.answer!.decision, "approve");
    });
    await run("?only-batch=1&partly-missing=1", [1440], async (page) => {
      await choice(page, "proposal-1", "accept").click();
      await answered(page);
      assert.equal((await calls(page)).find((call) => call.type === "answer")!.answer!.decision, "approve", "drafts that cannot be opened do not block the rest");
    });
    await run("?only-batch=1&fail-load=1", [1440], async (page) => {
      await page.getByText("The drafts could not be loaded right now.").waitFor();
      await page.getByRole("button", { name: "Try again" }).click();
      await draft(page, "proposal-1").locator("h3").waitFor();
    });
  },

  /** References are the feed's own cards, filters narrow the page, and a rating goes through the References review. */
  async references() {
    await run("?overview=1", [375, 1440], async (page, width) => {
      const card = page.locator('[data-feed-card="reference-a"]');
      await card.waitFor();
      assert.equal(await card.locator('[data-cyclotron-choice="accept"][data-predicted]').count(), 1, "the suggestion highlights Accept");
      assert.ok((await card.innerText()).includes("82%"), "with its confidence");
      assert.ok(await page.locator('[data-feed-card="reference-b"]').innerText().then((text) => text.length > 0));
      assert.ok((await page.locator("body").innerText()).includes("2 references waiting for you"), "the header counts References");
      assert.equal(await page.locator('[data-feed-card="reference-b"] [data-cyclotron-state="none"]').count(), 1, "no invented suggestion");
      await card.locator("[data-feed-open]").click();
      assert.equal(await page.evaluate(() => (window as unknown as { pushed?: string }).pushed), "/newsroom/references/reference-a", "a card opens the References queue");
      await card.locator('[data-review-choice="accept"]').click();
      await page.waitForFunction(() => (window as unknown as { calls: { type: string }[] }).calls.some((call) => call.type === "rate"));
      assert.deepEqual((await calls(page)).filter((call) => call.type === "rate").map((call) => [call.id, (call as { action?: string }).action]), [["reference-a", "accept"]]);
      // Filters.
      await page.locator('[data-notification-filter="drafts"]').click();
      assert.equal(await page.locator("[data-notification-references]").count(), 0, "the Drafts filter hides References");
      assert.ok((await page.locator("[data-filter-empty]").innerText()).includes("Nothing in Drafts"), "an empty filter says so");
      await page.locator('[data-notification-filter="references"]').click();
      assert.equal(await page.locator("[data-notification-references]").count(), 1);
      assert.equal(await page.locator('[data-notification-filter="references"]').getAttribute("aria-pressed"), "true");
      const scrollX = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(scrollX <= 0, `no horizontal scroll at ${width}px`);
    });
  },
};

export async function runNotificationCenterScenario(name: string) {
  assert.ok(scenarios[name], `Unknown Notification Center scenario: ${name}`);
  await scenarios[name]();
  console.log(`Notification Center scenario passed: ${name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === fileURLToPath(new URL(process.argv[1], "file://"))) {
  const requested = process.argv[2];
  void (async () => {
    for (const name of requested ? [requested] : Object.keys(scenarios)) await runNotificationCenterScenario(name);
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
