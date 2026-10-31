/**
 * Newsroom review fixes, fixture-only: the Proposed Story wording, the board's newest-first columns, and a story's detail view opening
 * on a solid surface that does not jump. No network and no production reads. Run one scenario with `tsx scripts/test-newsroom-ux-review.ts board_order`.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { ORGANIZER_NAV_GROUPS } from "../lib/newsroom-organizer-nav";
import { kindLabel, stateLabel } from "../lib/proposals-admin";
import { summaryText } from "../lib/review-requests";
import { waitingTextFor } from "../lib/needs-me-items";
import { NEEDS_ME_FILTER_LABELS } from "../lib/needs-me-ranking";
import { IDEA_ORIGIN_PRIORITIES, contentItemBoardConfig, deskBoardConfig, projectContentItemBoard } from "../lib/newsroom-board";
import { DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS } from "../lib/content-item-lifecycle";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://ux-review.test";
let bundle: Promise<string> | undefined;
let css: Promise<string> | undefined;

/** The shipped stylesheets: the real Tailwind build, Kanbus's board and the newspaper-gothic theme, the newsroom theme map and the organizer. */
function stylesheet(): Promise<string> {
  css ??= (async () => {
    const file = `${root}app/tailwind.css`;
    const { default: postcss } = await import("postcss");
    const { default: tailwind } = await import("@tailwindcss/postcss");
    const tailwindCss = (await postcss([tailwind() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
    const bundled = await build({
      absWorkingDir: root, bundle: true, write: false, logLevel: "silent", loader: { ".woff2": "empty", ".woff": "empty" },
      entryPoints: ["node_modules/@kanbus/ui/dist/styles/kanban.css", "node_modules/@kanbus/ui/dist/styles/themes/index.css", "components/newsroom-theme.css", "components/newsroom-organizer.css"],
      outdir: "out",
    });
    return [tailwindCss, ...bundled.outputFiles.map((output) => output.text)].join("\n");
  })();
  return css;
}

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent",
    loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"', "process.env.NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW": '"1"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development", NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW: "1" } };' },
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ contents: "export const usePathname = () => '/stories'; export const useRouter = () => ({ push() {}, replace() {} }); export const useSearchParams = () => new URLSearchParams();", loader: "js" }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "ux-review-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { useMemo, useState } from "react";
import { IssueCollection, IssueDetailPanel, IssueIdFormatProvider } from "@kanbus/ui";
import { NewsroomArticleEditor } from "./components/newsroom-article-editor";
import { contentItemBoardConfig, contentItemBoardType, formatNativeIssueId, projectContentItemBoard } from "./lib/newsroom-board";
import { createLocalPreviewContentItemVersions } from "./lib/local-preview-seed";

const params = new URLSearchParams(location.search);
const mode = params.get("mode") ?? "seed";
// "order": stories whose id order is the OPPOSITE of their time order, so a column sorted by id (what Kanbus did) lists them oldest first.
const versions = mode === "order"
  ? [["a-oldest", "2026-10-01T00:00:00Z"], ["b-middle", "2026-10-02T00:00:00Z"], ["c-newest", "2026-10-03T00:00:00Z"], ["d-undated", null]].map(([slug, updatedAt], index) => ({
      id: slug + "-v1", lineageId: slug, versionNumber: 1, stage: "copywriting", type: "article", status: "draft", title: String(slug), headline: String(slug), slug: String(slug), updatedAt }))
  : createLocalPreviewContentItemVersions();
function Board() {
  const issues = useMemo(() => projectContentItemBoard({ contentItemVersions: versions }), []);
  const config = useMemo(() => {
    const base = contentItemBoardConfig(issues);
    return params.has("legacy") ? { ...base, sort_order: undefined } : base;
  }, [issues]);
  const [selected, setSelected] = useState(null);
  const issue = issues.find((item) => item.id === selected);
  window.openStory = (id) => setSelected(id);
  return <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode="light" data-sidebar-collapsed="true">
    <div className="organizer-workspace"><main className="organizer-main"><IssueIdFormatProvider formatIssueId={formatNativeIssueId}><div className="organizer-native-board">
      <div className="organizer-board-body" data-detail-open={Boolean(issue)}>
        <IssueCollection issues={issues} config={config} query={{ type: contentItemBoardType() }} view="board" initialScroll="start"
          selectedIssueId={selected} detailOpen={Boolean(issue)} onSelectIssue={(item) => setSelected(item.id)} ariaLabel="Stories" />
        {issue && <IssueDetailPanel issue={issue} onClose={() => setSelected(null)} fields={[]}>
          <NewsroomArticleEditor key={issue.id} articleId={decodeURIComponent(issue.href.split("/").pop() ?? "")} demo embedded />
        </IssueDetailPanel>}
      </div>
    </div></IssueIdFormatProvider></main></div>
  </div>;
}
createRoot(document.getElementById("root")).render(<Board />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(query: string, width: number) {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${styles}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/stories${query}`);
  await page.locator(".issue-card").first().waitFor();
  return { browser, page, errors };
}

/** Every column's cards, top to bottom, by title. */
const columns = (page: Page) => page.locator("[data-column-key]").evaluateAll((nodes) => Object.fromEntries(nodes.map((node) => [node.getAttribute("data-column-key"), [...node.querySelectorAll(".issue-card h3")].map((heading) => heading.textContent)])));

type Frame = { t: number; x: number; y: number; w: number; h: number; alpha: number; opacity: number; editor: number | null; skeleton: boolean };

/** Open the first story and record the detail view on every animation frame for a few seconds. */
async function sampleOpening(page: Page): Promise<Frame[]> {
  // A string, not a function: the test runner's transform adds helpers that do not exist in the page.
  return page.evaluate(`(async () => {
    const frames = [];
    const start = performance.now();
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const alphaOf = (colour) => { context.clearRect(0, 0, 1, 1); context.fillStyle = "#000"; context.fillStyle = colour; context.fillRect(0, 0, 1, 1); return context.getImageData(0, 0, 1, 1).data[3] / 255; };
    let running = true;
    const tick = () => {
      const detail = document.querySelector(".kb-issue-detail");
      if (detail) {
        const box = detail.getBoundingClientRect();
        const editor = detail.querySelector(".newsroom-embedded-article")?.getBoundingClientRect().height ?? null;
        let opacity = 1;
        for (let element = detail; element && element !== document.body; element = element.parentElement) opacity *= parseFloat(getComputedStyle(element).opacity);
        frames.push({ t: Math.round(performance.now() - start), x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.width), h: Math.round(box.height),
          alpha: alphaOf(getComputedStyle(detail).backgroundColor), opacity, editor: editor === null ? null : Math.round(editor), skeleton: Boolean(detail.querySelector("[data-newsroom-article-skeleton]")) });
      }
      if (running) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    document.querySelector(".issue-card").click();
    await new Promise((resolve) => setTimeout(resolve, 3000));
    running = false;
    return frames;
  })()`) as Promise<Frame[]>;
}

const scenarios: Record<string, () => Promise<void>> = {
  /** A story_draft Proposal is a "Proposed Story" everywhere an editor reads it. */
  async proposed_stories() {
    const navigation = ORGANIZER_NAV_GROUPS.flatMap((group) => group.items).find((item) => item.path === "/newsroom/administration/proposals");
    assert.equal(navigation?.label, "Proposed Stories", "the sidebar entry");
    assert.ok(!/draft/i.test(navigation?.description ?? ""), "its description does not say draft");
    assert.equal(kindLabel("story_draft"), "Proposed Story", "the kind label");
    assert.ok(!/^draft$/i.test(stateLabel("draft", true)), "the proposal's first state is not the bare word Draft");
    assert.equal(NEEDS_ME_FILTER_LABELS.drafts, "Proposed Stories", "the Needs me filter");
    assert.equal(waitingTextFor({ drafts: 3, references: 1, stories: 0, email: 0, captures: 0, other: 0 } as never), "3 Proposed Stories and 1 reference waiting for you");
    assert.match(summaryText({ waiting: 0, drafts: 1, otherReviews: 0, decidedBySystem: 0, unread: 0 }), /1 Proposed Story to review/);
    assert.ok(!/draft/i.test(summaryText({ waiting: 0, drafts: 4, otherReviews: 0, decidedBySystem: 0, unread: 0 })));
  },

  /** Each column lists its stories newest first. Kanbus sorts a column by created_at ascending unless told otherwise, and stories carry no created_at. */
  async board_order() {
    const issues = projectContentItemBoard({ contentItemVersions: [{ id: "x-v1", lineageId: "x", versionNumber: 1, stage: "copywriting", type: "article", status: "draft", slug: "x", updatedAt: "2026-10-01" }] });
    const config = contentItemBoardConfig(issues);
    for (const status of config.statuses) assert.deepEqual(config.sort_order?.[status.key], [{ field: "updated_at", direction: "desc" }], `${status.key} is sorted newest first`);
    const desk = deskBoardConfig(issues);
    for (const status of desk.statuses) assert.ok(desk.sort_order?.[status.key], `${status.key} keeps its sort on a desk board`);
    assert.equal(DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS.length > 0, true);
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("?mode=order", width);
      try {
        const order = (await columns(page))[`${issues[0].type}/copywriting`] ?? [];
        assert.deepEqual(order, ["c-newest", "b-middle", "a-oldest", "d-undated"], `${width}: newest first, a story with no date last (${order.join(", ")})`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
    // The cause: without the sort rule the same column lists oldest first (by id), which is what the editor saw.
    const { browser, page } = await setup("?mode=order&legacy=1", 1440);
    try {
      const order = (await columns(page))[`${issues[0].type}/copywriting`] ?? [];
      assert.deepEqual(order, ["a-oldest", "b-middle", "c-newest", "d-undated"], `without the rule Kanbus orders by id (${order.join(", ")})`);
    } finally { await browser.close(); }
  },

  /** The Stories board starts with Idea ahead of Reporting; assignment-stage work stays off it. */
  async board_stage_columns() {
    const version = (stage: string, versionCreatedBy = "Someone") => ({ versionCreatedBy, id: `${stage}-v1`, lineageId: stage, versionNumber: 1, stage, type: "article", status: "draft", slug: stage });
    const issues = projectContentItemBoard({ contentItemVersions: ["idea", "reporting", "assignment"].map((stage) => version(stage)) });
    assert.deepEqual(issues.map((issue) => issue.nativeStatus).sort(), ["idea", "reporting"], "idea stories are on the board, assignment-stage work is not");
    const origins = projectContentItemBoard({ contentItemVersions: [{ ...version("idea", "AI"), lineageId: "g", id: "g-v1" }, { ...version("idea", "Pat"), lineageId: "p", id: "p-v1" }] }).map((issue) => issue.priority);
    assert.deepEqual(origins, [IDEA_ORIGIN_PRIORITIES.generated, IDEA_ORIGIN_PRIORITIES.person], "an Idea card says whether it was generated or started by a person");
    assert.deepEqual(contentItemBoardConfig(issues).priorities[IDEA_ORIGIN_PRIORITIES.generated], { name: "Generated" });
    const names = contentItemBoardConfig(issues).statuses.map((status) => status.name);
    assert.deepEqual(names, ["Idea", "Reporting", "Copywriting", "Illustration", "Typesetting", "Spiked", "Held", "Published"], "column order");
  },

  /** Opening a story: a solid detail view from its first frame, in one place and one size, with a loading shape that is the loaded shape. */
  async detail_stable() {
    for (const width of [1440, 834, 375]) {
      const { browser, page, errors } = await setup("", width);
      try {
        await page.waitForTimeout(500);
        const frames = await sampleOpening(page);
        assert.ok(frames.length > 20, `${width}: the detail view was sampled (${frames.length} frames)`);
        const first = frames[0];
        assert.equal(first.alpha, 1, `${width}: the detail view's background is opaque on its first frame (alpha ${first.alpha})`);
        assert.equal(first.opacity, 1, `${width}: and it is not fading in (opacity ${first.opacity})`);
        assert.ok(frames.every((frame) => frame.alpha === 1 && frame.opacity === 1), `${width}: it is opaque on every frame`);
        for (const key of ["x", "y", "w", "h"] as const) assert.ok(frames.every((frame) => frame[key] === first[key]), `${width}: the panel's ${key} never changes`);
        const heights = frames.map((frame) => frame.editor).filter((height): height is number => height !== null);
        const jumps = heights.filter((height, index) => index > 0 && Math.abs(height - heights[index - 1]) > 2);
        assert.ok(jumps.length === 0, `${width}: the editor's height does not jump while it loads (${[...new Set(heights)].join(" -> ")})`);
        console.log(`  ${width}px: ${frames.length} frames, first-frame alpha ${first.alpha}, panel ${first.w}x${first.h} at ${first.x},${first.y}, editor height ${[...new Set(heights)].join(" -> ")}${frames.some((frame) => frame.skeleton) ? " (skeleton seen)" : ""}`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Newsroom UX review scenario passed: ${name}`);
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
