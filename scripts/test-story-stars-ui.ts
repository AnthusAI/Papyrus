/**
 * Fixture-only browser acceptance for Story star ratings (PPY-f1c1fd): the real Stories board, its drawer and the Story editor on the local-preview data. No network,
 * no production reads. Run one scenario with `tsx scripts/test-story-stars-ui.ts card_mark`; set PAPYRUS_STORY_STARS_SHOTS=<dir> to write the screenshots.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://story-stars.test";
/** Seeds of lib/local-preview-seed.ts: copywriting-0 carries 4 stars, published-0 carries 5, idea-1 carries 2, the rest are unrated. */
const RATED = { lineage: "preview-item-lineage-copywriting-0", version: "preview-item-version-copywriting-0" };
const UNRATED = { lineage: "preview-item-lineage-copywriting-1", version: "preview-item-version-copywriting-1" };
const PUBLISHED = { lineage: "preview-item-lineage-published-0", version: "preview-item-version-published-0" };
const shots = process.env.PAPYRUS_STORY_STARS_SHOTS;
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
import { createLocalPreviewContentItemVersions } from ${JSON.stringify(root + "lib/local-preview-seed")};
export const CONTENT_ITEM_COLUMN_PAGE_LIMIT = 25;
export const loadNewsroomContentItemStagePage = async (stage) => ({ versions: createLocalPreviewContentItemVersions().filter((version) => version.stage === stage), nextToken: null });
export const loadNewsroomContentItemsChangedSince = async () => [];
export const loadNewsroomAssignmentPage = async () => ({ items: [], nextToken: null });
export const saveNewsroomAssignmentDesk = async () => undefined;
`;
const STUBS: Record<string, string> = {
  "news-desk-client-provider": "export const useOptionalNewsDeskClient = () => ({ shell: { phase: 'ready', dashboard: { newsroomSections: [] } } });",
  "newsroom-access-gate": "export const NewsDeskAccessGate = () => null;",
  "newsroom-assignment-detail": "export const NewsroomAssignmentDetail = () => null;",
  "newsroom-ops-shell": "export const NewsroomOpsShell = ({ children, headerActions, pageTitle }) => <div className='newsroom-organizer' data-kanbus-theme='newspaper-gothic' data-color-mode='light' data-sidebar-collapsed='true'><div className='organizer-workspace'><header className='organizer-topbar'><h1>{pageTitle}</h1><div className='organizer-header-actions'>{headerActions}</div></header><main className='organizer-main'>{children}</main></div></div>; export const NewsroomOpsStatusBanner = ({ children }) => <p role='alert'>{children}</p>;",
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
      builder.onResolve({ filter: new RegExp(`/(${Object.keys(STUBS).join("|")})$`) }, (args) => ({ path: args.path.split("/").pop()!, namespace: "fixture-stub" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ contents: path === "navigation" ? NAVIGATION : BOARD_CLIENT, loader: "js", resolveDir: root }));
      builder.onLoad({ filter: /.*/, namespace: "fixture-stub" }, ({ path }) => ({ contents: STUBS[path], loader: "jsx", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-stars-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NewsroomBoardView } from "./components/newsroom-board-view";
import { NewsroomArticleEditor } from "./components/newsroom-article-editor";
import { resolveArticlesBackend } from "./lib/newsroom-articles";
// What the backend was asked to do: a rating is a plain update, so it must never be a draft save, a publish or a stage move.
window.fixtureCalls = [];
window.fixtureFailStars = false;
const backend = resolveArticlesBackend(true);
const actions = backend.actions;
for (const name of ["saveItemDraft", "publishItem", "unpublishItem", "moveStoryStage"]) {
  const original = actions[name];
  actions[name] = async (...args) => { window.fixtureCalls.push({ action: name }); return original(...args); };
}
const setItemStars = actions.setItemStars;
actions.setItemStars = async (itemId, stars) => {
  window.fixtureCalls.push({ action: "setItemStars", itemId, stars });
  if (window.fixtureFailStars) throw new Error("Your rating could not be saved. Tap a star to try again.");
  return setItemStars(itemId, stars);
};
const params = new URLSearchParams(location.search);
const editorId = params.get("editor");
createRoot(document.getElementById("root")).render(editorId
  ? <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode="light" data-sidebar-collapsed="true"><div className="organizer-workspace"><main className="organizer-main"><NewsroomArticleEditor key={editorId} articleId={editorId} demo /></main></div></div>
  : <NewsroomBoardView subject="contentItem" />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(path: string, width = 1440, height = 1000) {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Low motion: the board's staggered card animation otherwise stacks cards above the phone drawer while it plays, which says nothing about stars.
  await page.addInitScript(() => window.localStorage.setItem("papyrus:reader-settings", JSON.stringify({ motion: "low" })));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${styles}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}${path}`);
  return { browser, page, errors };
}

const board = "/newsroom/articles";
const card = (page: Page, lineage: string) => page.locator(`.issue-card[data-issue-id="contentItem:${lineage}"]`);
const mark = (page: Page, lineage: string) => card(page, lineage).locator("[data-stars-mark]");
const drawer = (page: Page) => page.locator("[data-newsroom-article-stars]");
const stars = (locator: ReturnType<Page["locator"]>) => locator.locator("[data-star-rating]").getAttribute("data-stars");
const calls = (page: Page) => page.evaluate(() => (window as unknown as { fixtureCalls: unknown[] }).fixtureCalls);
const waitStars = (locator: ReturnType<Page["locator"]>, expected: string) => locator.locator(`[data-star-rating][data-stars="${expected}"]`).first().waitFor();
async function openStory(page: Page, lineage: string) {
  await card(page, lineage).locator("h3").click();
  await drawer(page).waitFor();
}
async function shot(page: Page, name: string) {
  if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: `${shots}/story-stars-${name}.png` }); }
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);

const scenarios: Record<string, () => Promise<void>> = {
  /** A rated card shows one solid star and the number in its top row, an unrated card shows nothing, the card has no controls, and a tap on the mark opens the Story. */
  async card_mark() {
    const { browser, page, errors } = await setup(board);
    try {
      await mark(page, RATED.lineage).waitFor();
      assert.equal(await mark(page, RATED.lineage).getAttribute("aria-label"), "4 of 5 stars", "a rated Story shows its saved rating");
      assert.match(await mark(page, RATED.lineage).innerText(), /^4$/, "the number is written");
      assert.equal(await mark(page, RATED.lineage).locator("svg").getAttribute("fill"), "currentColor", "a solid star, by shape");
      assert.equal(await card(page, RATED.lineage).locator(".issue-accent-row [data-stars-mark]").count(), 1, "in the card's top row");
      assert.equal(await mark(page, UNRATED.lineage).count(), 0, "an unrated Story shows no rating");
      assert.equal(await page.locator(".issue-card [data-star]").count(), 0, "no star buttons on any card");
      const rowHeight = await card(page, RATED.lineage).locator(".issue-accent-row").evaluate((node) => node.getBoundingClientRect().height);
      assert.equal(await card(page, UNRATED.lineage).locator(".issue-accent-row").evaluate((node) => node.getBoundingClientRect().height), rowHeight, "the mark does not make the top row taller");
      await shot(page, "card-1440");
      await mark(page, RATED.lineage).click();
      await drawer(page).waitFor();
      assert.deepEqual(await calls(page), [], "tapping the mark saves nothing");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** In the drawer one tap sets and a tap on the same star clears, by shape with the count in words; the card follows. Rating never saves a draft, publishes or moves a stage. */
  async drawer_tap() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, UNRATED.lineage);
      assert.equal(await stars(drawer(page)), "0", "an unrated Story shows five empty stars");
      assert.equal(await drawer(page).locator("[data-star]").count(), 5);
      await drawer(page).locator('[data-star="3"]').click();
      await waitStars(drawer(page), "3");
      assert.deepEqual(await calls(page), [{ action: "setItemStars", itemId: UNRATED.version, stars: 3 }]);
      const shapes = await drawer(page).locator("[data-star] svg").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("fill")));
      assert.deepEqual(shapes, ["currentColor", "currentColor", "currentColor", "none", "none"], "filled versus outline by shape, not colour");
      assert.match(await drawer(page).locator("[data-star-rating-words]").innerText(), /3 of 5 stars/i, "the count is written as well");
      await card(page, UNRATED.lineage).locator('[data-stars-mark="3"]').waitFor({ state: "attached" });
      await shot(page, "drawer-1440");
      await drawer(page).locator('[data-star="3"]').click();
      await waitStars(drawer(page), "0");
      await mark(page, UNRATED.lineage).waitFor({ state: "detached" });
      assert.deepEqual((await calls(page)).at(-1), { action: "setItemStars", itemId: UNRATED.version, stars: null }, "the second tap clears");
      assert.deepEqual((await calls(page)).map((call) => (call as { action: string }).action), ["setItemStars", "setItemStars"], "only ratings were saved: no draft, publish or stage move");
      assert.equal(await drawer(page).locator("select, [role=combobox]").count(), 0, "no dropdowns");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** The standalone editor page rates the Story too, at any stage, including a published one, and a rating is not a draft save or a publish. */
  async editor_and_published() {
    const { browser, page, errors } = await setup(`/?editor=${PUBLISHED.version}`);
    try {
      await drawer(page).waitFor();
      assert.equal(await stars(drawer(page)), "5", "a published Story's rating is shown");
      await drawer(page).locator('[data-star="1"]').click();
      await waitStars(drawer(page), "1");
      assert.deepEqual(await calls(page), [{ action: "setItemStars", itemId: PUBLISHED.version, stars: 1 }], "rating a published Story is one plain update");
      assert.equal(await page.locator("[data-newsroom-article-status]").innerText(), "Published", "it is still published");
      assert.equal(await page.locator("[data-newsroom-article-save]").isDisabled(), true, "and the editor has nothing unsaved");
      await shot(page, "editor-1440");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A save that fails says so and shows the saved rating again, in the drawer and on the card. */
  async failed_save() {
    const { browser, page, errors } = await setup(board);
    try {
      await openStory(page, RATED.lineage);
      await page.evaluate(() => { (window as unknown as { fixtureFailStars: boolean }).fixtureFailStars = true; });
      await drawer(page).locator('[data-star="1"]').click();
      await drawer(page).locator('[role="alert"]').waitFor();
      assert.match(await drawer(page).locator('[role="alert"]').innerText(), /could not be saved/i);
      assert.equal(await stars(drawer(page)), "4", "the saved rating is shown again");
      assert.equal(await mark(page, RATED.lineage).getAttribute("data-stars-mark"), "4", "and on the card");
      await page.evaluate(() => { (window as unknown as { fixtureFailStars: boolean }).fixtureFailStars = false; });
      await drawer(page).locator('[data-star="1"]').click();
      await waitStars(drawer(page), "1");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone the stars are large targets in one row in the drawer and the editor, the card's rating stays in its top row, and nothing scrolls sideways. */
  async phone() {
    const onBoard = await setup(board, 375, 900);
    try {
      await mark(onBoard.page, RATED.lineage).waitFor();
      await mark(onBoard.page, RATED.lineage).scrollIntoViewIfNeeded();
      await shot(onBoard.page, "board-375");
      assert.equal(await card(onBoard.page, RATED.lineage).locator(".issue-accent-row [data-stars-mark]").count(), 1, "board: the mark is in the card's top row");
      assert.equal(await noSideScroll(onBoard.page), true, "board: nothing scrolls sideways");
      assert.deepEqual(onBoard.errors, []);
    } finally { await onBoard.browser.close(); }
    for (const target of ["drawer", "editor"] as const) {
      const { browser, page, errors } = await setup(target === "editor" ? `/?editor=${RATED.version}` : board, 375, 900);
      try {
        if (target === "drawer") await openStory(page, RATED.lineage);
        const control = drawer(page);
        await control.first().waitFor();
        await control.first().scrollIntoViewIfNeeded();
        await shot(page, `${target}-375`);
        const boxes = await control.first().locator("[data-star]").evaluateAll((nodes) => nodes.map((node) => { const box = node.getBoundingClientRect(); return { width: box.width, height: box.height, top: Math.round(box.top) }; }));
        assert.equal(boxes.length, 5);
        assert.ok(boxes.every((box) => box.height >= 40 && box.width >= 40), `${target}: every star is at least 40px square: ${JSON.stringify(boxes)}`);
        assert.equal(new Set(boxes.map((box) => box.top)).size, 1, `${target}: the five stars are in one row`);
        assert.equal(await control.first().locator("[data-star] svg").count(), 5, `${target}: Lucide icons`);
        assert.equal(await noSideScroll(page), true, `${target}: nothing scrolls sideways`);
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
    console.log(`Story stars scenario passed: ${name}`);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
