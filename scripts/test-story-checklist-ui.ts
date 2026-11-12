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
import { addLocalPreviewStoryStepNote, createLocalPreviewContentItemVersions, createLocalPreviewStoryChecklist, setLocalPreviewStoryStep } from ${JSON.stringify(root + "lib/local-preview-seed")};
export const CONTENT_ITEM_COLUMN_PAGE_LIMIT = 25;
export const loadNewsroomContentItemStagePage = async (stage) => ({ versions: createLocalPreviewContentItemVersions().filter((version) => version.stage === stage), nextToken: null });
export const loadNewsroomContentItemsChangedSince = async () => [];
export const loadStoryChecklistSteps = async (lineageId) => createLocalPreviewStoryChecklist(lineageId);
export const addStoryChecklistNote = async (lineageId, stepKey, text) => { window.fixtureSaves.push({ lineageId, stepKey, note: text }); addLocalPreviewStoryStepNote(lineageId, stepKey, text); };
export const saveStoryChecklistStep = async (lineageId, stepKey, state, input) => { window.fixtureSaves.push({ lineageId, stepKey, state, ...input }); setLocalPreviewStoryStep(lineageId, stepKey, state, input); };
export const loadNewsroomAssignmentPage = async () => ({ items: [], nextToken: null });
export const saveNewsroomAssignmentDesk = async () => undefined;
`;
const STUBS: Record<string, string> = {
  "news-desk-client-provider": "export const useOptionalNewsDeskClient = () => ({ shell: { phase: 'ready', dashboard: { newsroomSections: [] } } });",
  "newsroom-access-gate": "export const NewsDeskAccessGate = () => null;",
  "newsroom-assignment-detail": "export const NewsroomAssignmentDetail = () => null;",
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
      builder.onResolve({ filter: /news-desk-taxonomy-client$/ }, (args) => /newsroom-board-view|use-paged-content-item-versions/.test(args.importer) ? { path: "board-client", namespace: "fixture" } : undefined);
      builder.onResolve({ filter: /story-checklist-client$/ }, () => ({ path: "board-client", namespace: "fixture" }));
      builder.onResolve({ filter: new RegExp(`/(${Object.keys(STUBS).join("|")})$`) }, (args) => ({ path: args.path.split("/").pop()!, namespace: "fixture-stub" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ contents: path === "navigation" ? NAVIGATION : BOARD_CLIENT, loader: "js", resolveDir: root }));
      builder.onLoad({ filter: /.*/, namespace: "fixture-stub" }, ({ path }) => ({ contents: STUBS[path], loader: "jsx", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-stars-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
window.fixtureSaves = [];
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
const step = (page: Page, key: string) => panel(page).locator(`.issue-card[data-issue-id$="-${key}"]`);
const actions = (page: Page, key: string) => panel(page).locator(`[data-story-step-actions="${key}"]`);
const saves = (page: Page) => page.evaluate(() => (window as unknown as { fixtureSaves: unknown[] }).fixtureSaves);
async function openStory(page: Page, lineage: string) {
  await card(page, lineage).locator("h3").click();
  await panel(page).waitFor();
  await panel(page).locator(".issue-card").first().waitFor();
}
async function shot(page: Page, name: string) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: `${shots}/${name}.png` }); }
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);

const scenarios: Record<string, () => Promise<void>> = {
  /** A Story card shows its progress, with an icon, and a tap on it opens the panel. */
  async card_progress() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await progress(page, COPYWRITING.lineage).waitFor();
        assert.equal(await progress(page, COPYWRITING.lineage).innerText(), "6/14 · 1 skipped", "done and not-applicable over all, then the skipped count");
        assert.equal(await progress(page, COPYWRITING.lineage).locator("svg").count(), 1, "a Lucide icon");
        assert.match(await progress(page, COPYWRITING.lineage).getAttribute("aria-label") ?? "", /Checklist: 6\/14 · 1 skipped/, "the words for a screen reader");
        assert.equal(await progress(page, IDEA.lineage).innerText(), "0/14", "an idea has done nothing yet");
        assert.equal(await card(page, COPYWRITING.lineage).locator(".issue-card-owner [data-story-checklist-progress]").count(), 1, "in the card's owner row");
        await shot(page, `card-${mode}-1440-v5`);
        await progress(page, COPYWRITING.lineage).click();
        await panel(page).waitFor();
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** The Story's own content comes first in the panel (title, then the editor's fields and text); the checklist follows it, toward the bottom. */
  async content_first() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await card(page, COPYWRITING.lineage).locator("h3").click();
        await panel(page).waitFor();
        const detail = page.locator(".kb-issue-detail");
        await detail.locator("[data-newsroom-article-stars]").waitFor();
        const order = await page.evaluate(`(function(){var d=document.querySelector('.kb-issue-detail');var title=d.querySelector('h2').getBoundingClientRect().top;var editor=d.querySelector('[data-newsroom-article-stars]').getBoundingClientRect().top;var list=d.querySelector('[data-story-checklist]').getBoundingClientRect().top;return {title:title,editor:editor,list:list};})()`) as { title: number; editor: number; list: number };
        assert.ok(order.title < order.editor && order.editor < order.list, `title, then the Story's content, then the checklist: ${JSON.stringify(order)}`);
        await detail.evaluate(node => { node.scrollTop = 0; });
        await shot(page, `panel-content-${mode}-1440-v5`);
        await panel(page).scrollIntoViewIfNeeded();
        await detail.evaluate(node => { node.scrollTop = node.scrollHeight; });
        await shot(page, `panel-checklist-${mode}-1440-v5`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** The panel lists the steps as Kanbus's own sub-task cards: type sub-task, the state as a word and an icon, the actor in plain words, the reason or findings, and no raw command. */
  async panel_sub_tasks() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await openStory(page, COPYWRITING.lineage);
        const cards = panel(page).locator(".issue-card");
        assert.equal(await cards.count(), 14, "every live step of the template");
        assert.equal(await cards.evaluateAll(nodes => nodes.every(node => node.getAttribute("data-type") === "sub-task")), true, "Kanbus sub-task cards");
        assert.equal(await step(page, "outline").getAttribute("data-priority"), "Skipped");
        assert.match(await step(page, "outline").innerText(), /Reason: The editor wrote the draft straight from the reporting notes\./);
        assert.match(await step(page, "review_people").innerText(), /Findings: Reads clearly/);
        assert.equal(await step(page, "review_search").getAttribute("data-priority"), "Open");
        assert.match(await step(page, "research").innerText(), /Automatically, from the research packet/, "an automatic completion says where the proof came from");
        assert.doesNotMatch(await panel(page).innerText(), /papyrus stories step|Next:|\bevidence\b/, "no raw command and no jargon in the panel");
        assert.equal(await cards.evaluateAll(nodes => nodes.every(node => /\b(Open|Done|Skipped|Not applicable)\b/i.test((node as HTMLElement).innerText))), true, "every state is a word as well as an icon");
        const icons = await cards.evaluateAll(nodes => nodes.map(node => getComputedStyle(node.querySelector(".issue-accent-priority")!, "::before").maskImage));
        assert.ok(icons.every(image => image.startsWith("url(")), "every state has a Lucide icon");
        assert.equal(new Set(icons).size, 3, "three states on this Story, three icons");
        await shot(page, `panel-${mode}-1440-v5`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** Every step row has its buttons, not only a chosen one: done (a review step asks for findings), skipped and not applicable (each asks for a reason), and reopen on a closed step. */
  async buttons() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await openStory(page, COPYWRITING.lineage);
        const kinds = (key: string) => actions(page, key).locator("[data-step-action]").evaluateAll(nodes => nodes.map(node => node.getAttribute("data-step-action")));
        assert.equal(await panel(page).locator("[data-story-step-actions]").count(), 14, "buttons under every step, none of them chosen first");
        for (const key of ["review_reader_agents", "review_search", "review_social", "publish"]) assert.deepEqual(await kinds(key), ["done", "skipped", "not_applicable", "note"], `${key}: an open step offers done, skip, not applicable and a note`);
        for (const key of ["choose", "outline", "review_people"]) assert.deepEqual(await kinds(key), ["open", "note"], `${key}: a closed step offers reopen and a note`);
        assert.equal(await panel(page).locator("[data-story-step-actions] button svg").count() >= 20, true, "Lucide icons on the buttons");
        await panel(page).locator("[data-story-step-actions]").nth(7).scrollIntoViewIfNeeded();
        await shot(page, `panel-row-buttons-${mode}-1440-v5`);
        await actions(page, "review_search").locator('[data-step-action="done"]').click();
        await actions(page, "review_search").locator("textarea").waitFor();
        await actions(page, "review_search").locator('[data-step-action="save"]').click();
        assert.match(await actions(page, "review_search").locator("[data-step-problem]").innerText(), /note of what the review found/i, "findings are required for a review step");
        assert.deepEqual(await saves(page), [], "nothing was saved");
        await shot(page, `buttons-${mode}-1440-v5`);
        await actions(page, "review_search").locator("textarea").fill("Title and description read well in results.");
        await actions(page, "review_search").locator('[data-step-action="save"]').click();
        await step(page, "review_search").locator('.issue-accent-priority:has-text("Done")').waitFor();
        assert.deepEqual(await saves(page), [{ lineageId: COPYWRITING.lineage, stepKey: "review_search", state: "done", note: "Title and description read well in results." }]);
        assert.match(await step(page, "review_search").innerText(), /Findings: Title and description read well/);
        assert.match(await step(page, "review_search").innerText(), /Preview editor/, "a person's change shows their name");
        assert.deepEqual(await kinds("review_search"), ["open", "note"], "the row now offers reopen");
        // Skipping needs a reason, on a different row, while another row is untouched.
        await actions(page, "review_social").locator('[data-step-action="skipped"]').click();
        await actions(page, "review_social").locator('[data-step-action="save"]').click();
        assert.match(await actions(page, "review_social").locator("[data-step-problem]").innerText(), /say why/i);
        await actions(page, "review_social").locator("textarea").fill("No image on this Story.");
        await actions(page, "review_social").locator('[data-step-action="save"]').click();
        await step(page, "review_social").locator('.issue-accent-priority:has-text("Skipped")').waitFor();
        assert.match(await panel(page).locator(".story-checklist-progress").innerText(), /^7\/14 · 2 skipped$/, "the panel's progress follows");
        // Not applicable also needs a reason; a done step is reopened by a person.
        await actions(page, "review_reader_agents").locator('[data-step-action="not_applicable"]').click();
        await actions(page, "review_reader_agents").locator("textarea").fill("Agents do not read this page.");
        await actions(page, "review_reader_agents").locator('[data-step-action="save"]').click();
        await step(page, "review_reader_agents").locator('.issue-accent-priority:has-text("Not applicable")').waitFor();
        await actions(page, "review_search").locator('[data-step-action="open"]').click();
        await step(page, "review_search").locator('.issue-accent-priority:has-text("Open")').waitFor();
        assert.deepEqual((await saves(page)).map(save => (save as { state: string }).state), ["done", "skipped", "not_applicable", "open"]);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** A note can be added to any step, in any state; notes pile up newest last, a crowded step folds its older notes, and nothing offers to edit or delete one. */
  async notes() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 1440, 1000, mode);
      try {
        await openStory(page, COPYWRITING.lineage);
        const noteTexts = (key: string) => step(page, key).locator("xpath=..").locator("[data-step-note] .story-checklist-note-text").allInnerTexts();
        const crowded = step(page, "review_people").locator("xpath=..");
        assert.equal(await crowded.locator("[data-step-note]").count(), 3, "more than three notes: the newest three show");
        assert.match((await noteTexts("review_people")).at(-1) ?? "", /Checked the footer/, "the newest is last");
        const toggle = crowded.locator("[data-step-notes-toggle]");
        assert.match(await toggle.innerText(), /Show 1 earlier note/);
        await toggle.scrollIntoViewIfNeeded();
        await shot(page, `notes-folded-${mode}-1440-v5`);
        await toggle.click();
        assert.equal(await crowded.locator("[data-step-note]").count(), 4, "all four once opened");
        assert.match(await crowded.locator("[data-step-note]").first().innerText(), /Headline and dek agree[\s\S]*AI \(agent\)/, "who, with agents named as agents");
        assert.match(await crowded.locator("[data-step-note]").nth(1).innerText(), /quotation in the fourth paragraph needs its source named/, "a multi-line note keeps its lines");
        await crowded.scrollIntoViewIfNeeded();
        await shot(page, `notes-open-${mode}-1440-v5`);
        assert.equal(await panel(page).locator("[data-step-note] button, [data-step-note] textarea").count(), 0, "no note can be edited or deleted");
        // Any state: an open step, a done step and a skipped step each offer Add note.
        for (const key of ["review_social", "review_people", "outline"]) assert.equal(await actions(page, key).locator('[data-step-action="note"]').count(), 1, `${key}: Add note`);
        await actions(page, "review_social").locator('[data-step-action="note"]').click();
        await actions(page, "review_social").locator('[data-step-action="save"]').click();
        assert.match(await actions(page, "review_social").locator("[data-step-problem]").innerText(), /write the note/i, "an empty note is refused");
        await actions(page, "review_social").locator("textarea").fill("Ask the photo desk for a card image.\nNo rush.");
        await actions(page, "review_social").locator('[data-step-action="save"]').click();
        await step(page, "review_social").locator("xpath=..").locator("[data-step-note]").first().waitFor();
        assert.deepEqual(await saves(page), [{ lineageId: COPYWRITING.lineage, stepKey: "review_social", note: "Ask the photo desk for a card image.\nNo rush." }]);
        assert.equal(await step(page, "review_social").getAttribute("data-priority"), "Open", "a note leaves the state as it was");
        assert.deepEqual((await noteTexts("review_social")), ["Ask the photo desk for a card image.\nNo rush."]);
        assert.match(await step(page, "review_social").locator("xpath=..").locator("[data-step-note]").innerText(), /Preview editor/, "a person's note shows their name");
        await actions(page, "outline").locator('[data-step-action="note"]').click();
        await actions(page, "outline").locator("textarea").fill("Second thought on the skip.");
        await actions(page, "outline").locator('[data-step-action="save"]').click();
        await step(page, "outline").locator("xpath=..").locator("[data-step-note]").nth(1).waitFor();
        assert.equal(await step(page, "outline").getAttribute("data-priority"), "Skipped");
        assert.deepEqual(await noteTexts("outline"), ["Skipped on purpose: this Story came from a single Reference.", "Second thought on the skip."], "notes accumulate, newest last");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** A published Story's panel shows every required step closed, including a not-applicable step with its reason. */
  async published_panel() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, PUBLISHED.lineage);
      assert.equal(await progress(page, PUBLISHED.lineage).innerText(), "13/14 · 1 skipped");
      assert.equal(await step(page, "review_social").getAttribute("data-priority"), "Not applicable");
      assert.match(await step(page, "review_social").innerText(), /Reason: This Story has no image to preview\./);
      assert.equal(await panel(page).locator('.issue-card[data-priority="Open"]').count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** With the panel open the board's columns are not clipped on the left: every column starts at the board's edge (it scrolls, or shrinks), and nothing scrolls sideways on the page. */
  async columns_not_clipped() {
    for (const [width, height] of [[1440, 1000], [1024, 800]] as const) {
      const { browser, page, errors } = await setup(board, width, height);
      try {
        await openStory(page, COPYWRITING.lineage);
        const geometry = await page.evaluate(`(function(){var grid=document.querySelector('.organizer-board-body .kb-grid');var box=grid.getBoundingClientRect();var card=document.querySelector('.issue-card[data-issue-id="contentItem:${COPYWRITING.lineage}"]').getBoundingClientRect();var first=document.querySelector('.organizer-board-body .kb-column').getBoundingClientRect();return {scrollLeft:grid.scrollLeft,boardLeft:box.left,boardRight:box.right,firstLeft:first.left,cardLeft:card.left,cardRight:card.right};})()`) as { scrollLeft: number; boardLeft: number; boardRight: number; firstLeft: number; cardLeft: number; cardRight: number };
        if (width >= 1440) {   // the columns up to the open Story's fit beside the panel: nothing scrolls, so the first column is whole
          assert.equal(geometry.scrollLeft, 0, `${width}px: the board is not scrolled away from its first column: ${JSON.stringify(geometry)}`);
          assert.ok(geometry.firstLeft >= geometry.boardLeft - 1, `${width}px: the first column starts inside the board: ${JSON.stringify(geometry)}`);
        }   // on a narrower screen the board scrolls just far enough to show the open Story's card whole
        assert.ok(geometry.cardLeft >= geometry.boardLeft - 1 && geometry.cardRight <= geometry.boardRight + 1, `${width}px: the open Story's card is fully inside the board: ${JSON.stringify(geometry)}`);
        await shot(page, `columns-${width}-v5`);
        assert.equal(await noSideScroll(page), true, `${width}px: nothing scrolls sideways on the page`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  /** On a phone the panel's steps and buttons stack in one column and nothing scrolls sideways. */
  async phone() {
    for (const mode of ["light", "dark"] as const) {
      const { browser, page, errors } = await setup(board, 375, 900, mode);
      try {
        await progress(page, COPYWRITING.lineage).waitFor();
        await progress(page, COPYWRITING.lineage).scrollIntoViewIfNeeded();
        await shot(page, `card-${mode}-375-v5`);
        assert.equal(await noSideScroll(page), true, "board: nothing scrolls sideways");
        await openStory(page, COPYWRITING.lineage);
        await page.locator(".kb-issue-detail [data-newsroom-article-stars]").waitFor();
        const detail = page.locator(".kb-issue-detail");
        const order = await page.evaluate(`(function(){var d=document.querySelector('.kb-issue-detail');var top=function(selector){return d.querySelector(selector).getBoundingClientRect().top+d.scrollTop;};return {title:top('h2'),editor:top('[data-newsroom-article-stars]'),list:top('[data-story-checklist]')};})()`) as { title: number; editor: number; list: number };
        assert.ok(order.title < order.editor && order.editor < order.list, `phone: title, then the Story's content, then the checklist: ${JSON.stringify(order)}`);
        await detail.evaluate(node => { node.scrollTop = 0; });
        await shot(page, `panel-content-${mode}-375-v5`);
        await panel(page).scrollIntoViewIfNeeded();
        await actions(page, "review_search").scrollIntoViewIfNeeded();
        await shot(page, `panel-${mode}-375-v5`);
        const clipped = await page.evaluate(`(function(){var out=[];var els=document.querySelectorAll('[data-story-checklist], [data-story-checklist] *');for(var i=0;i<els.length;i++){var r=els[i].getBoundingClientRect();if(r.width>0&&(r.right>window.innerWidth+1||r.left<-1)){out.push(els[i].tagName+'.'+els[i].className);}}return out.slice(0,5);})()`) as string[];
        assert.deepEqual(clipped, [], "phone: nothing in the checklist runs past the screen's edge (the editor's own toggle and header controls are a separate follow-up)");
        const crowded = step(page, "review_people").locator("xpath=..");
        await crowded.locator("[data-step-notes-toggle]").click();
        await crowded.scrollIntoViewIfNeeded();
        await shot(page, `notes-open-${mode}-375-v5`);
        assert.equal(await noSideScroll(page), true, "notes: nothing scrolls sideways");
        await actions(page, "review_search").locator('[data-step-action="note"]').click();
        await actions(page, "review_search").locator("textarea").waitFor();
        await actions(page, "review_search").scrollIntoViewIfNeeded();
        await shot(page, `panel-form-${mode}-375-v5`);
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
