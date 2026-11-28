/**
 * Fixture-only browser acceptance for the Story editor's pinned Save and Cancel bar: the real Stories board, its drawer and the Story editor on the
 * local-preview data. No network, no production reads. Run one scenario with `tsx scripts/test-story-unsaved-changes-ui.ts drawer_save`; set
 * PAPYRUS_STORY_UNSAVED_SHOTS=<dir> to write the screenshots.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Locator, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://story-unsaved-changes.test";
/** Seeds of lib/local-preview-seed.ts: idea-0 is a draft, published-0 is live, and copywriting-1's title has an unquoted colon, which is not valid YAML. */
const DRAFT = { lineage: "preview-item-lineage-idea-0", version: "preview-item-version-idea-0" };
const UNREADABLE_FRONT_MATTER = { lineage: "preview-item-lineage-copywriting-1", version: "preview-item-version-copywriting-1" };
const PUBLISHED = { lineage: "preview-item-lineage-published-0", version: "preview-item-version-published-0" };
const NEW_SUBTITLE = "A subtitle the editor just typed";
const screenshotDirectory = process.env.PAPYRUS_STORY_UNSAVED_SHOTS;
let fixtureScriptBundle: Promise<string> | undefined;
let fixtureStylesheet: Promise<string> | undefined;

function stylesheet(): Promise<string> {
  fixtureStylesheet ??= (async () => {
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
  return fixtureStylesheet;
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
export const loadEditorNewsroomSections = async () => [];
export const saveNewsroomAssignmentDesk = async () => undefined;
`;
const STUBS: Record<string, string> = {
  "news-desk-client-provider": "export const useOptionalNewsDeskClient = () => ({ shell: { phase: 'ready', auth: { status: 'signedIn' }, dashboard: { newsroomSections: [] } } });",
  "newsroom-access-gate": "export const NewsDeskAccessGate = () => null;",
  "newsroom-assignment-detail": "export const NewsroomAssignmentDetail = () => null;",
  "newsroom-ops-shell": "export const NewsroomOpsShell = ({ children, headerActions, pageTitle }) => <div className='newsroom-organizer' data-kanbus-theme='newspaper-gothic' data-color-mode='light' data-sidebar-collapsed='true'><div className='organizer-workspace'><header className='organizer-topbar'><h1>{pageTitle}</h1><div className='organizer-header-actions'>{headerActions}</div></header><main className='organizer-main'>{children}</main></div></div>; export const NewsroomOpsStatusBanner = ({ children }) => <p role='alert'>{children}</p>;",
};

function browserBundle(): Promise<string> {
  fixtureScriptBundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent",
    loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development", NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW: "1" } };' },
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onResolve({ filter: /news-desk-taxonomy-client$/ }, (args) => /newsroom-board-view|use-paged-content-item-versions|use-newsroom-desk-sections/.test(args.importer) ? { path: "board-client", namespace: "fixture" } : undefined);
      builder.onResolve({ filter: new RegExp(`/(${Object.keys(STUBS).join("|")})$`) }, (args) => ({ path: args.path.split("/").pop()!, namespace: "fixture-stub" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ contents: path === "navigation" ? NAVIGATION : BOARD_CLIENT, loader: "js", resolveDir: root }));
      builder.onLoad({ filter: /.*/, namespace: "fixture-stub" }, ({ path }) => ({ contents: STUBS[path], loader: "jsx", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-unsaved-changes-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NewsroomBoardView } from "./components/newsroom-board-view";
import { NewsroomArticleEditor } from "./components/newsroom-article-editor";
import { resolveArticlesBackend } from "./lib/newsroom-articles";
window.fixtureCalls = [];
const actions = resolveArticlesBackend(true).actions;
for (const name of ["saveItemDraft", "publishItem", "unpublishItem", "moveStoryStage"]) {
  const original = actions[name];
  actions[name] = async (...args) => { window.fixtureCalls.push({ action: name, arguments: args[0] }); return original(...args); };
}
const editorId = new URLSearchParams(location.search).get("editor");
createRoot(document.getElementById("root")).render(editorId
  ? <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode="light" data-sidebar-collapsed="true"><div className="organizer-workspace"><main className="organizer-main"><NewsroomArticleEditor key={editorId} articleId={editorId} demo /></main></div></div>
  : <NewsroomBoardView subject="contentItem" />);
` },
  }).then((result) => result.outputFiles[0].text);
  return fixtureScriptBundle;
}

async function openFixturePage(path: string, width = 1440, height = 1000) {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
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
const editorBlock = (page: Page) => page.locator("[data-newsroom-article-editor]");
const subtitleField = (page: Page) => page.locator('[data-newsroom-article-field="subtitle"]');
const unsavedBar = (page: Page) => page.locator("[data-newsroom-article-unsaved-bar]");
type RecordedBackendCall = { action: string; arguments?: { newVersion?: boolean } };
const recordedBackendCalls = (page: Page) => page.evaluate(() => (window as unknown as { fixtureCalls: RecordedBackendCall[] }).fixtureCalls);
const pageScrollsSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);

async function openStoryInDrawer(page: Page, lineage: string) {
  await card(page, lineage).locator("h3").click();
  await editorBlock(page).waitFor();
  await page.locator("[data-newsroom-article-toolbar]").waitFor();
}

async function changeSubtitle(page: Page) {
  await page.locator('[data-newsroom-article-view="edit"]').click();
  await subtitleField(page).scrollIntoViewIfNeeded();
  await subtitleField(page).fill(NEW_SUBTITLE);
  await unsavedBar(page).waitFor();
}

async function saveScreenshot(page: Page, name: string) {
  if (!screenshotDirectory) return;
  fs.mkdirSync(screenshotDirectory, { recursive: true });
  await page.screenshot({ path: `${screenshotDirectory}/story-unsaved-${name}.png` });
}

async function assertFullyInViewport(page: Page, locator: Locator, description: string) {
  const viewport = page.viewportSize()!;
  const box = await locator.boundingBox();
  assert.ok(box, `${description}: it has a box`);
  assert.ok(box.y >= 0 && box.y + box.height <= viewport.height + 1, `${description}: it is in view (${JSON.stringify(box)} in a ${viewport.height}px tall window)`);
}

const scenarios: Record<string, () => Promise<void>> = {
  /** The bar is in view while the subtitle field is, even though the toolbar has scrolled away, and Save keeps the change in place. */
  async drawer_save() {
    const { browser, page, errors } = await openFixturePage(board);
    try {
      await openStoryInDrawer(page, DRAFT.lineage);
      assert.equal(await unsavedBar(page).count(), 0, "no bar before anything changed");
      assert.equal(await page.locator("[data-newsroom-article-toolbar] [data-newsroom-article-save]").innerText(), "Save");
      assert.equal(await page.locator("[data-newsroom-article-save-version]").count(), 0, "no second way to save");
      await changeSubtitle(page);
      await saveScreenshot(page, "drawer-1440");
      assert.match(await unsavedBar(page).innerText(), /Unsaved changes/);
      await assertFullyInViewport(page, unsavedBar(page).locator("[data-newsroom-article-cancel]"), "Cancel");
      await assertFullyInViewport(page, unsavedBar(page).locator("[data-newsroom-article-unsaved-save]"), "Save");
      assert.equal(await unsavedBar(page).locator("[data-newsroom-article-unsaved-save]").innerText(), "Save");
      await page.locator("[data-newsroom-article-validity='valid']").waitFor();
      await unsavedBar(page).locator("[data-newsroom-article-unsaved-save]").click();
      await unsavedBar(page).waitFor({ state: "detached" });
      const calls = await recordedBackendCalls(page);
      assert.deepEqual(calls.map((call) => call.action), ["saveItemDraft"]);
      assert.notEqual(calls[0].arguments?.newVersion, true, "a draft is saved in place");
      assert.equal(await subtitleField(page).inputValue(), NEW_SUBTITLE);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Cancel puts back the saved subtitle without saving anything. */
  async drawer_cancel() {
    const { browser, page, errors } = await openFixturePage(board);
    try {
      await openStoryInDrawer(page, DRAFT.lineage);
      await page.locator('[data-newsroom-article-view="edit"]').click();
      const savedSubtitle = await subtitleField(page).inputValue();
      await changeSubtitle(page);
      await unsavedBar(page).locator("[data-newsroom-article-cancel]").click();
      await unsavedBar(page).waitFor({ state: "detached" });
      assert.equal(await subtitleField(page).inputValue(), savedSubtitle);
      assert.deepEqual(await recordedBackendCalls(page), []);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A live Story is saved as a new draft version; the live page is not touched. */
  async published_story() {
    const { browser, page, errors } = await openFixturePage(`/?editor=${PUBLISHED.version}`);
    try {
      await page.locator("[data-newsroom-article-toolbar]").waitFor();
      await changeSubtitle(page);
      await saveScreenshot(page, "published-1440");
      assert.match(await page.locator("[data-newsroom-article-unsaved-detail]").innerText(), /Saving makes a new draft version; readers see it once you publish it/);
      await page.locator("[data-newsroom-article-validity='valid']").waitFor();
      await unsavedBar(page).locator("[data-newsroom-article-unsaved-save]").click();
      await page.locator("[data-newsroom-article-notice]").getByText(/Saved as version \d+\. Readers see it once you publish it\./).waitFor();
      const calls = await recordedBackendCalls(page);
      assert.deepEqual(calls.map((call) => call.action), ["saveItemDraft"], "one save and no publish");
      assert.equal(calls[0].arguments?.newVersion, true, "a live Story is saved as a new version, never in place");
      await page.locator("[data-newsroom-article-toolbar] [data-newsroom-article-status]").filter({ hasText: /^Draft$/ }).waitFor();
      assert.equal(await unsavedBar(page).count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Front matter the fields cannot parse switches them off with a note, instead of letting typing vanish. */
  async unreadable_front_matter() {
    const { browser, page, errors } = await openFixturePage(board);
    try {
      await openStoryInDrawer(page, UNREADABLE_FRONT_MATTER.lineage);
      await page.locator('[data-newsroom-article-view="edit"]').click();
      for (const field of ["title", "subtitle", "blurb"]) assert.equal(await page.locator(`[data-newsroom-article-field="${field}"]`).isDisabled(), true, `${field} is off`);
      assert.match(await page.locator("[data-newsroom-article-fields-unreadable]").innerText(), /Fix it under Front matter \(YAML\)/);
      assert.equal(await unsavedBar(page).count(), 0, "nothing claims to be unsaved");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Closing the drawer with unsaved changes asks first; no keeps everything, yes closes. */
  async close_drawer() {
    const { browser, page, errors } = await openFixturePage(board);
    try {
      await openStoryInDrawer(page, DRAFT.lineage);
      await changeSubtitle(page);
      const confirmationMessages: string[] = [];
      let acceptDiscard = false;
      page.on("dialog", (dialog) => { confirmationMessages.push(dialog.message()); void (acceptDiscard ? dialog.accept() : dialog.dismiss()); });
      const closeButton = page.locator("button[aria-label='Close issue details']");
      await closeButton.click();
      await page.waitForTimeout(300);
      assert.equal(confirmationMessages.length, 1, "the editor is asked once");
      assert.match(confirmationMessages[0], /unsaved changes/i);
      assert.equal(await subtitleField(page).inputValue(), NEW_SUBTITLE, "no keeps the drawer open with the change");
      acceptDiscard = true;
      await closeButton.click();
      await editorBlock(page).waitFor({ state: "detached" });
      assert.equal(new URL(page.url()).searchParams.get("open"), null);
      assert.deepEqual(await recordedBackendCalls(page), []);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone the bar fits, stays in view and nothing scrolls sideways. */
  async phone() {
    const { browser, page, errors } = await openFixturePage(board, 375, 812);
    try {
      await openStoryInDrawer(page, DRAFT.lineage);
      await changeSubtitle(page);
      await saveScreenshot(page, "drawer-375");
      await assertFullyInViewport(page, unsavedBar(page).locator("[data-newsroom-article-cancel]"), "Cancel");
      await assertFullyInViewport(page, unsavedBar(page).locator("[data-newsroom-article-unsaved-save]"), "Save");
      assert.equal(await pageScrollsSideways(page), false, "nothing scrolls sideways");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

void (async () => {
  const wanted = process.argv[2] ?? "all";
  for (const name of wanted === "all" ? Object.keys(scenarios) : [wanted]) {
    assert(scenarios[name], `unknown scenario ${name}`);
    await scenarios[name]();
    console.log(`Story unsaved changes scenario passed: ${name}`);
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
