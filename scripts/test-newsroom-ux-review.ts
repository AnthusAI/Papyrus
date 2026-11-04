/**
 * Newsroom review fixes, fixture-only: the ideas wording, the board's newest-first columns, and a story's detail view opening
 * on a solid surface that does not jump. No network and no production reads. Run one scenario with `tsx scripts/test-newsroom-ux-review.ts board_order`.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { ORGANIZER_NAV_GROUPS } from "../lib/newsroom-organizer-nav";
import { kindLabel, stateLabel, withoutStoryDrafts } from "../lib/proposals-admin";
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
import { IssueCollection, IssueDetailPanel, IssueIdFormatProvider, useBoardColumnState } from "@kanbus/ui";
import { NewsroomBoardSkeleton } from "./components/newsroom-board-skeleton";
import { NewsroomArticleEditor } from "./components/newsroom-article-editor";
import { contentItemBoardConfig, contentItemBoardType, formatNativeIssueId, projectContentItemBoard } from "./lib/newsroom-board";
import { createLocalPreviewContentItemVersions } from "./lib/local-preview-seed";

const params = new URLSearchParams(location.search);
const mode = params.get("mode") ?? "seed";
// "order": stories whose id order is the OPPOSITE of their time order, so a column sorted by id (what Kanbus did) lists them oldest first.
const versions = mode === "order"
  ? [["a-oldest", "2026-10-01T00:00:00Z"], ["b-middle", "2026-10-02T00:00:00Z"], ["c-newest", "2026-10-03T00:00:00Z"], ["d-undated", null]].map(([slug, updatedAt], index) => ({
      id: slug + "-v1", lineageId: slug, versionNumber: 1, stage: "copywriting", type: "article", status: "draft", title: String(slug), headline: String(slug), slug: String(slug), updatedAt }))
  : mode === "long"
    ? Array.from({ length: 160 }, (_, index) => ({ id: "long-" + index + "-v1", lineageId: "long-" + index, versionNumber: 1, stage: "copywriting", type: "article", status: "draft",
      title: "Long " + index, headline: "Long " + index, slug: "long-" + index, updatedAt: new Date(Date.UTC(2026, 9, 1) + (160 - index) * 60000).toISOString() }))
    : createLocalPreviewContentItemVersions();
window.nearEndCalls = [];
const LONG_PAGE_SIZE = 40;
function Board() {
  const [loadedCount, setLoadedCount] = useState(mode === "long" ? LONG_PAGE_SIZE : versions.length);
  const loadedVersions = useMemo(() => versions.slice(0, loadedCount), [loadedCount]);
  const issues = useMemo(() => projectContentItemBoard({ contentItemVersions: loadedVersions }), [loadedVersions]);
  const config = useMemo(() => {
    const base = contentItemBoardConfig(issues);
    return params.has("legacy") ? { ...base, sort_order: undefined } : base;
  }, [issues]);
  const [selected, setSelected] = useState(null);
  const columnState = useBoardColumnState({ config: contentItemBoardConfig([]), storageKey: "ux-review.columns" });
  const issue = issues.find((item) => item.id === selected);
  window.openStory = (id) => setSelected(id);
  return <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode="light" data-sidebar-collapsed="true">
    <div className="organizer-workspace"><main className="organizer-main"><IssueIdFormatProvider formatIssueId={formatNativeIssueId}><div className="organizer-native-board">
      <div className="organizer-board-body" data-detail-open={Boolean(issue)}>
        {mode === "skeleton" ? <NewsroomBoardSkeleton /> : <IssueCollection collapsedColumns={columnState.collapsedColumns} onToggleCollapse={columnState.toggleColumn}
          onColumnNearEnd={(columnKey) => { window.nearEndCalls.push({ columnKey, loadedCount }); if (mode === "long") setLoadedCount((count) => Math.min(versions.length, count + LONG_PAGE_SIZE)); }} issues={issues} config={config} query={{ type: contentItemBoardType() }} view="board" initialScroll="start"
          selectedIssueId={selected} detailOpen={Boolean(issue)} onSelectIssue={(item) => setSelected(item.id)} ariaLabel="Stories" />}
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

async function setup(query: string, width: number, height = 900, readySelector = ".issue-card") {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height } });
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
  await page.locator(readySelector).first().waitFor();
  return { browser, page, errors };
}

/** Every column's (or stacked section's) cards, top to bottom, by title. A column is one element; a stacked section is one element per card, so cards are gathered by column key. */
const columns = (page: Page) => page.locator("[data-column-key]").evaluateAll((nodes) => {
  const titlesByColumnKey: Record<string, (string | null)[]> = {};
  for (const node of nodes) {
    const key = node.getAttribute("data-column-key") ?? "";
    titlesByColumnKey[key] ??= [];
    for (const heading of node.querySelectorAll(".issue-card h3")) titlesByColumnKey[key].push(heading.textContent);
  }
  return titlesByColumnKey;
});

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

const verticalScrollers = (page: Page) => page.evaluate(`[...document.querySelectorAll("*")].filter((element) => {
  const style = getComputedStyle(element);
  return /(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1;
}).map((element) => element.className || element.tagName)`) as Promise<string[]>;

const scenarios: Record<string, () => Promise<void>> = {
  /** Below 600 px the stages are sections in one scroller; from 600 px they stay columns. */
  async board_stacked_on_phones() {
    for (const [width, height, layout] of [[375, 812, "stacked"], [390, 844, "stacked"], [667, 375, "columns"], [834, 1112, "columns"], [1440, 900, "columns"]] as const) {
      const { browser, page, errors } = await setup("", width, height);
      try {
        const state = await page.evaluate(`({ layout: document.querySelector("[data-layout]")?.getAttribute("data-layout"), columns: document.querySelectorAll(".kb-column").length,
          wide: document.documentElement.scrollWidth > innerWidth + 1 })`) as { layout: string; columns: number; wide: boolean };
        assert.equal(state.layout, layout, `${width}x${height}: layout`);
        assert.equal(state.wide, false, `${width}x${height}: no horizontal scroll`);
        if (layout === "stacked") {
          assert.equal(state.columns, 0, `${width}: no side by side columns`);
          const scrollers = await verticalScrollers(page);
          assert.deepEqual(scrollers, ["kb-stacked-scroll"], `${width}: exactly one vertical scroller (${scrollers.join(", ")})`);
        } else assert.ok(state.columns > 1, `${width}x${height}: columns stay`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** A long stage pages in through onColumnNearEnd on a phone and keeps the page small. */
  async board_pages_on_phones() {
    const boardView = fs.readFileSync(`${root}components/newsroom-board-view.tsx`, "utf8");
    assert.ok(boardView.includes("onColumnNearEnd"), "the newsroom board pages through onColumnNearEnd");
    assert.ok(!boardView.includes("kb-column-scroll") && !boardView.includes("onScrollCapture"), "the newsroom board no longer watches the column scroller");
    const organizerCss = fs.readFileSync(`${root}components/newsroom-organizer.css`, "utf8");
    assert.ok(!/\.kb-column\{min-width/.test(organizerCss), "no phone column width workaround remains");
    const { browser, page, errors } = await setup("?mode=long", 375, 812);
    try {
      await page.waitForTimeout(300);
      const cards = () => page.locator(".issue-card").count();
      assert.ok(await cards() < 60, "a bounded number of cards is rendered");
      const calls = () => page.evaluate("window.nearEndCalls.length") as Promise<number>;
      const before = await calls();
      for (let step = 0; step < 6; step++) {
        await page.evaluate(`(() => { const scroller = document.querySelector(".kb-stacked-scroll"); scroller.scrollTop = scroller.scrollHeight; })()`);
        await page.waitForTimeout(300);
      }
      assert.ok(await calls() > before, "the near-the-end callback requested more");
      assert.ok(await cards() < 80, `still bounded after paging (${await cards()})`);
      const heights = await page.evaluate(`document.querySelector(".kb-stacked-scroll").scrollHeight`) as number;
      assert.ok(heights > 40 * 80, "the stage grew past its first page");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
    const short = await setup("", 375, 812);
    try {
      await short.page.waitForTimeout(300);
      const keys = await short.page.evaluate("window.nearEndCalls.map((call) => call.columnKey)") as string[];
      assert.equal(new Set(keys).size, keys.length, `each short stage requests at most once (${keys.join(", ")})`);
    } finally { await short.browser.close(); }
  },

  /** Opening and closing a story keeps the place; a collapsed section stays collapsed after a reload. */
  async board_phone_detail_and_collapse() {
    const { browser, page, errors } = await setup("?mode=long", 375, 812);
    try {
      await page.evaluate(`document.querySelector(".kb-stacked-scroll").scrollTop = 1500`);
      await page.waitForTimeout(300);
      const scrollBefore = await page.evaluate(`document.querySelector(".kb-stacked-scroll").scrollTop`) as number;
      const visibleIndex = await page.evaluate(`[...document.querySelectorAll(".issue-card")].findIndex((card) => { const box = card.getBoundingClientRect(); return box.top > 200 && box.bottom < innerHeight - 20; })`) as number;
      assert.ok(visibleIndex >= 0, "a card is fully visible");
      const title = await page.locator(".issue-card h3").nth(visibleIndex).textContent();
      await page.locator(".issue-card").nth(visibleIndex).click();
      await page.locator(".kb-issue-detail").waitFor();
      const detail = await page.locator(".kb-issue-detail").boundingBox();
      assert.ok(detail && detail.width >= 340, `the detail view covers the board (${JSON.stringify(detail)})`);
      await page.evaluate(`window.openStory(null)`);
      await page.locator(".kb-issue-detail").waitFor({ state: "detached" });
      await page.waitForTimeout(300);
      const scrollAfter = await page.evaluate(`document.querySelector(".kb-stacked-scroll").scrollTop`) as number;
      assert.ok(Math.abs(scrollAfter - scrollBefore) <= 2, `same scroll position (${scrollBefore} -> ${scrollAfter})`);
      const focused = await page.evaluate(`document.activeElement?.closest(".issue-card")?.querySelector("h3")?.textContent ?? null`);
      assert.equal(focused, title, "the same story is focused again");
      await page.evaluate(`document.querySelector(".kb-stacked-scroll").scrollTop = 0`);
      await page.waitForTimeout(200);
      const header = page.locator(".kb-column-header").first();
      await header.click();
      assert.equal(await header.getAttribute("aria-expanded"), "false", "the section collapsed");
      await page.reload();
      await page.locator(".kb-column-header").first().waitFor();
      assert.equal(await page.locator(".kb-column-header").first().getAttribute("aria-expanded"), "false", "collapsed after reload");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The skeleton and the board change shape at the same width: the package's 600 px line. */
  async board_skeleton_agrees() {
    for (const [width, stacked] of [[375, true], [599, true], [600, false], [640, false]] as const) {
      const skeleton = await setup("?mode=skeleton", width, 812, "[data-board-skeleton]");
      try {
        const tracks = await skeleton.page.evaluate(`getComputedStyle(document.querySelector("[data-board-skeleton]")).gridTemplateColumns.split(" ").length`) as number;
        assert.equal(tracks, stacked ? 1 : 3, `${width}: skeleton column tracks`);
      } finally { await skeleton.browser.close(); }
      const board = await setup("", width, 812);
      try {
        const layout = await board.page.evaluate(`document.querySelector("[data-layout]").getAttribute("data-layout")`);
        assert.equal(layout, stacked ? "stacked" : "columns", `${width}: board layout`);
      } finally { await board.browser.close(); }
    }
  },

  /** A generated story idea is an "idea" in the Idea column everywhere an editor reads it; there is no Proposed Stories page. */
  async ideas_wording() {
    const navigation = ORGANIZER_NAV_GROUPS.flatMap((group) => group.items).find((item) => item.path === "/newsroom/administration/proposals");
    assert.equal(navigation, undefined, "ideas live in the Stories board Idea column, so the sidebar has no separate Proposed Stories entry");
    assert.equal(kindLabel("story_draft"), "story_draft", "a story draft has no editor-facing kind label: it is not a Proposal any more");
    assert.deepEqual(withoutStoryDrafts([{ kind: "story_draft" }, { kind: "rename" }]), [{ kind: "rename" }], "the Proposals panel leaves old story drafts to papyrus ideas migrate-proposals");
    assert.ok(!/^draft$/i.test(stateLabel("draft", true)), "the proposal's first state is not the bare word Draft");
    assert.equal(NEEDS_ME_FILTER_LABELS.ideas, "Ideas", "the Needs me filter");
    assert.equal(waitingTextFor({ ideas: 2, references: 1, stories: 0, email: 0, captures: 0, links: 0, other: 0 } as never), "2 idea batches and 1 reference waiting for you");
    assert.match(summaryText({ waiting: 0, ideas: 1, otherReviews: 0, decidedBySystem: 0, unread: 0 }), /1 idea to review/);
    assert.ok(!/draft|proposed stor/i.test(summaryText({ waiting: 0, ideas: 4, otherReviews: 0, decidedBySystem: 0, unread: 0 })));
    for (const file of ["components/newsroom-board-view.tsx", "components/needs-me-bodies.tsx", "components/needs-me-feed.tsx", "components/proposals-view.tsx", "lib/needs-me-items.ts", "lib/review-requests.ts"]) {
      assert.ok(!/proposed stor/i.test(fs.readFileSync(`${root}${file}`, "utf8")), `${file} never says Proposed Story`);
    }
    const board = fs.readFileSync(`${root}components/newsroom-board-view.tsx`, "utf8");
    assert.ok(!/loadProposals|data-newsroom-proposed-stories|older Proposed/.test(board), "the board header has no link to an older Proposed Stories page");
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
