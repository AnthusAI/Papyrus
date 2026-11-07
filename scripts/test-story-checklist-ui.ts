/**
 * Fixture-only browser acceptance for the Story checklist: the real Stories board, a card's progress line and the open Story panel's sub-tasks, on the local-preview
 * data, in light and dark. No network, no production reads. Run one scenario with `tsx scripts/test-story-checklist-ui.ts card_progress`;
 * set PAPYRUS_STORY_CHECKLIST_SHOTS=<dir> to write the screenshots.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://story-checklist.test";
/** Seeds of lib/local-preview-seed.ts: copywriting-0 has skipped the outline and reviewed for readers; published-0 has every step closed; idea-0 has nothing done. */
const COPYWRITING = { lineage: "preview-item-lineage-copywriting-0" };
const PUBLISHED = { lineage: "preview-item-lineage-published-0" };
const IDEA = { lineage: "preview-item-lineage-idea-0" };
const shots = process.env.PAPYRUS_STORY_CHECKLIST_SHOTS;
let bundle: Promise<string> | undefined;
let css: Promise<string> | undefined;

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

const NAVIGATION = `
import { useMemo, useSyncExternalStore } from 'react';
const listeners = new Set();
const notify = () => listeners.forEach((listener) => listener());
const subscribe = (listener) => { listeners.add(listener); window.addEventListener('popstate', listener); return () => { listeners.delete(listener); window.removeEventListener('popstate', listener); }; };
export const usePathname = () => useSyncExternalStore(subscribe, () => location.pathname);
export const useSearchParams = () => { const search = useSyncExternalStore(subscribe, () => location.search); return useMemo(() => new URLSearchParams(search), [search]); };
export const useRouter = () => useMemo(() => ({ push: (url) => { history.pushState({}, '', url); notify(); }, replace: (url) => { history.replaceState({}, '', url); notify(); } }), []);
`;
const BOARD_CLIENT = `
import { createLocalPreviewContentItemVersions, createLocalPreviewStoryChecklist } from ${JSON.stringify(root + "lib/local-preview-seed")};
export const CONTENT_ITEM_COLUMN_PAGE_LIMIT = 25;
export const loadNewsroomContentItemStagePage = async (stage) => ({ versions: createLocalPreviewContentItemVersions().filter((version) => version.stage === stage), nextToken: null });
export const loadNewsroomContentItemsChangedSince = async () => [];
export const loadStoryChecklistSteps = async (lineageId) => createLocalPreviewStoryChecklist(lineageId);
export const loadNewsroomAssignmentPage = async () => ({ items: [], nextToken: null });
export const saveNewsroomAssignmentDesk = async () => undefined;
`;
const STUBS: Record<string, string> = {
  "news-desk-client-provider": "export const useOptionalNewsDeskClient = () => ({ shell: { phase: 'ready', dashboard: { newsroomSections: [] } } });",
  "newsroom-access-gate": "export const NewsDeskAccessGate = () => null;",
  "newsroom-assignment-detail": "export const NewsroomAssignmentDetail = () => null;",
  "newsroom-article-editor": "export const NewsroomArticleEditor = () => <p data-article-editor-stub>The Story editor sits here.</p>;",
  "newsroom-ops-shell": "export const NewsroomOpsShell = ({ children, headerActions, pageTitle }) => <div className='newsroom-organizer' data-kanbus-theme='newspaper-gothic' data-color-mode={document.documentElement.dataset.colorMode || 'light'} data-sidebar-collapsed='true'><div className='organizer-workspace'><header className='organizer-topbar'><h1>{pageTitle}</h1><div className='organizer-header-actions'>{headerActions}</div></header><main className='organizer-main'>{children}</main></div></div>; export const NewsroomOpsStatusBanner = ({ children }) => <p role='alert'>{children}</p>;",
};

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent",
    loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development", NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW: "1" } };' },
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onResolve({ filter: /news-desk-taxonomy-client$/ }, (args) => /newsroom-board-view|use-paged-content-item-versions|story-checklist-panel/.test(args.importer) ? { path: "board-client", namespace: "fixture" } : undefined);
      builder.onResolve({ filter: new RegExp(`/(${Object.keys(STUBS).join("|")})$`) }, (args) => ({ path: args.path.split("/").pop()!, namespace: "fixture-stub" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ contents: path === "navigation" ? NAVIGATION : BOARD_CLIENT, loader: "js", resolveDir: root }));
      builder.onLoad({ filter: /.*/, namespace: "fixture-stub" }, ({ path }) => ({ contents: STUBS[path], loader: "jsx", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-stars-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NewsroomBoardView } from "./components/newsroom-board-view";
createRoot(document.getElementById("root")).render(<NewsroomBoardView subject="contentItem" />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(path: string, width = 1440, height = 1000, mode: "light" | "dark" = "light") {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Low motion: the board's staggered card animation otherwise stacks cards above the phone drawer while it plays, which says nothing about stars.
  await page.addInitScript(() => window.localStorage.setItem("papyrus:reader-settings", JSON.stringify({ motion: "low" })));
  await page.emulateMedia({ colorScheme: mode });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html data-color-mode="${mode}" class="${mode === "dark" ? "dark" : "light-theme"}"><head><meta name="viewport" content="width=device-width"><style>${styles}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}${path}`);
  return { browser, page, errors };
}

const board = "/newsroom/articles";
const card = (page: Page, lineage: string) => page.locator(`.issue-card[data-issue-id="contentItem:${lineage}"]`);
const progress = (page: Page, lineage: string) => card(page, lineage).locator("[data-story-checklist-progress]");
const panel = (page: Page) => page.locator("[data-story-checklist]");
async function openStory(page: Page, lineage: string) {
  await card(page, lineage).locator("h3").click();
  await panel(page).waitFor();
  await panel(page).locator("[data-step-key]").first().waitFor();
}
async function shot(page: Page, name: string) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: `${shots}/${name}.png` }); }
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);

const scenarios: Record<string, () => Promise<void>> = {
  /** A Story card shows its progress, with an icon, and a Story with nothing done shows 1 of its steps; a tap on it opens the panel. */
  async card_progress() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await progress(page, COPYWRITING.lineage).waitFor();
        assert.equal(await progress(page, COPYWRITING.lineage).innerText(), "6/11 · 1 skipped", "done and not-applicable over all, then the skipped count");
        assert.equal(await progress(page, COPYWRITING.lineage).locator("svg").count(), 1, "a Lucide icon");
        assert.match(await progress(page, COPYWRITING.lineage).getAttribute("aria-label") ?? "", /Checklist: 6\/11 · 1 skipped/, "the words for a screen reader");
        assert.equal(await progress(page, IDEA.lineage).innerText(), "0/11", "an idea has done nothing yet");
        assert.equal(await card(page, COPYWRITING.lineage).locator(".issue-card-owner [data-story-checklist-progress]").count(), 1, "in the card's owner row");
        await progress(page, COPYWRITING.lineage).scrollIntoViewIfNeeded();
        await shot(page, `card-${mode}-1440`);
        await progress(page, COPYWRITING.lineage).click();
        await panel(page).waitFor();
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** The open panel lists the steps as Kanbus sub-tasks of the Story: each has a state as an icon and a word, who and when, the reason or findings, and the next command while open. */
  async panel_sub_tasks() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await openStory(page, COPYWRITING.lineage);
        const rows = panel(page).locator("[data-step-key]");
        assert.equal(await rows.count(), 11, "every live step of the template");
        assert.equal(await rows.evaluateAll(nodes => nodes.every(node => node.getAttribute("data-issue-type") === "sub-task" && node.getAttribute("data-parent") === "contentItem:preview-item-lineage-copywriting-0")), true, "sub-tasks of the Story");
        const outline = panel(page).locator('[data-step-key="outline"]');
        assert.equal(await outline.getAttribute("data-step-state"), "skipped");
        assert.match(await outline.innerText(), /Skipped[\s\S]*Preview editor[\s\S]*Reason: The editor wrote the draft straight from the reporting notes\./);
        const readers = panel(page).locator('[data-step-key="review_people"]');
        assert.match(await readers.innerText(), /Done[\s\S]*Reviewed for readers[\s\S]*Findings: Reads clearly/);
        const search = panel(page).locator('[data-step-key="review_search"]');
        assert.equal(await search.getAttribute("data-step-state"), "open");
        assert.match(await search.innerText(), /Open[\s\S]*Reviewed for search[\s\S]*Next: papyrus stories step --story preview-item-lineage-copywriting-0 --step review_search/);
        const research = panel(page).locator('[data-step-key="research"]');
        assert.match(await research.innerText(), /evidence/, "a step the records proved is shown as evidence's");
        assert.equal(await rows.evaluateAll(nodes => nodes.every(node => node.querySelectorAll("svg").length === 1 && /\b(Open|Done|Skipped|Not applicable)\b/.test((node as HTMLElement).innerText))), true, "every state is an icon and a word, never colour alone");
        assert.equal(await panel(page).locator("svg").count(), 12, "Lucide icons: one per step and one in the heading");
        await panel(page).scrollIntoViewIfNeeded();
        await shot(page, `panel-${mode}-1440`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** A published Story's panel shows every required step closed, including a not-applicable step with its reason. */
  async published_panel() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, PUBLISHED.lineage);
      assert.equal(await progress(page, PUBLISHED.lineage).innerText(), "10/11 · 1 skipped");
      const social = panel(page).locator('[data-step-key="review_social"]');
      assert.equal(await social.getAttribute("data-step-state"), "not_applicable");
      assert.match(await social.innerText(), /Not applicable[\s\S]*Reason: This Story has no image to preview\./);
      assert.equal(await panel(page).locator('[data-step-state="open"]').count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone the panel's steps stack in one column and nothing scrolls sideways. */
  async phone() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 375, 900, mode);
      try {
        await progress(page, COPYWRITING.lineage).waitFor();
        await progress(page, COPYWRITING.lineage).scrollIntoViewIfNeeded();
        await shot(page, `card-${mode}-375`);
        assert.equal(await noSideScroll(page), true, "board: nothing scrolls sideways");
        await openStory(page, COPYWRITING.lineage);
        await panel(page).scrollIntoViewIfNeeded();
        await shot(page, `panel-${mode}-375`);
        assert.equal(await noSideScroll(page), true, "panel: nothing scrolls sideways");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },
};

void (async () => {
  const wanted = process.argv[2] ?? "all";
  for (const name of wanted === "all" ? Object.keys(scenarios) : [wanted]) {
    assert(scenarios[name], `unknown scenario ${name}`);
    await scenarios[name]();
    console.log(`Story checklist scenario passed: ${name}`);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
