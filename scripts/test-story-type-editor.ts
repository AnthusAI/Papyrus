/**
 * The Story editor's Type field, fixture-only (no network, no production reads): the site's Story types as buttons, the plain "no public URL" note, and a live
 * Story whose type changes only through a new version. The editor runs on the local-preview demo backend; the site's projection.json slice arrives through
 * the same variable `withPapyrus` inlines (NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES), set here from the page's `types` query.
 * Run one scenario with `tsx scripts/test-story-type-editor.ts live_story`.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://story-type.test";
const DRAFT_ID = "preview-item-version-copywriting-0";
const PUBLISHED_ID = "preview-item-version-published-0";
/** article and post have a base; guide is offered by the site (storyTypes.types) but has no urls.types entry and no listing. */
const SITE = { storyTypes: { default: "article", types: ["article", "post", "guide"] }, urls: { types: { article: { base: "articles" }, post: { base: "posts" } } }, listings: { types: ["article", "post"] } };
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

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent",
    loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development", NEXT_PUBLIC_PAPYRUS_LOCAL_PREVIEW: "1", NEXT_PUBLIC_PAPYRUS_PROJECTION_TYPES: new URLSearchParams(location.search).get("types") || undefined } };' },
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: "navigation", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ contents: "export const usePathname = () => '/newsroom/articles'; export const useRouter = () => ({ push() {}, replace() {} }); export const useSearchParams = () => new URLSearchParams();", loader: "js" }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-type-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { NewsroomArticleEditor } from "./components/newsroom-article-editor";
const id = new URLSearchParams(location.search).get("id");
createRoot(document.getElementById("root")).render(<div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode="light" data-sidebar-collapsed="true"><div className="organizer-workspace"><main className="organizer-main"><NewsroomArticleEditor key={id} articleId={id} demo /></main></div></div>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(id: string, width = 1280, site: unknown = SITE) {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${styles}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/?id=${id}&types=${encodeURIComponent(JSON.stringify(site))}`);
  await page.locator("[data-newsroom-article-type-field]").waitFor();
  return { browser, page, errors };
}

const typeButton = (page: Page, type: string) => page.locator(`[data-newsroom-article-type="${type}"]`);
const pressed = (page: Page) => page.locator("[data-newsroom-article-type][aria-pressed=true]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-newsroom-article-type")));

const scenarios: Record<string, () => Promise<void>> = {
  /** The Type field is buttons for the site's own types (plus the page), never a dropdown; the chosen one is marked by a check, not by colour alone. */
  async buttons_not_a_dropdown() {
    const { browser, page, errors } = await setup(DRAFT_ID);
    try {
      const labels = await page.locator("[data-newsroom-article-type]").allInnerTexts();
      assert.deepEqual(labels.map((label) => label.trim()), ["Article", "Post", "Guide", "Page"], "the site's types in its order, then the page");
      assert.equal(await page.locator("[data-newsroom-article-type-field] select, [data-newsroom-article-type-field] [role=combobox]").count(), 0, "no dropdown");
      assert.deepEqual(await pressed(page), ["article"], "the Story is of the site's default type");
      assert.equal(await typeButton(page, "article").locator("svg").count(), 1, "the chosen type carries a check mark");
      assert.equal(await typeButton(page, "post").locator("svg").count(), 0);
      for (const icon of await page.locator("[data-newsroom-article-type-field] svg").all()) assert.ok(await icon.evaluate((svg) => [...svg.classList].some((name) => name.startsWith("lucide"))), "Lucide icons only");
      await typeButton(page, "post").click();
      assert.deepEqual(await pressed(page), ["post"], "one type at a time");
      assert.ok(await page.getByText("Unsaved changes").isVisible(), "choosing a type is an edit");
      assert.match(await page.locator("[data-newsroom-article-address]").innerText(), /Published under \/posts\//, "the address the type gives");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A type with no urls.types entry and no section route says so plainly in the editor. */
  async no_public_url() {
    const { browser, page, errors } = await setup(DRAFT_ID);
    try {
      assert.equal(await page.locator("[data-newsroom-article-no-public-url]").count(), 0, "an article has an address");
      await typeButton(page, "guide").click();
      const note = page.locator("[data-newsroom-article-no-public-url]");
      assert.match(await note.innerText(), /No public URL\. This site has no page for the type "guide"/);
      assert.equal(await note.evaluate((element) => element.getAttribute("role")), "status");
      assert.ok(await note.locator("svg").count() > 0, "the note has an icon as well as words");
      await typeButton(page, "post").click();
      assert.equal(await page.locator("[data-newsroom-article-no-public-url]").count(), 0, "a type with an address has no such note");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A live Story keeps its address until a new version is published: saving in place is off, a new version carries the type, Publish moves it with a notice. */
  async live_story() {
    const { browser, page, errors } = await setup(PUBLISHED_ID);
    try {
      assert.deepEqual(await pressed(page), ["article"]);
      await typeButton(page, "post").click();
      assert.match(await page.locator("[data-newsroom-article-type-needs-version]").innerText(), /live\. Use Save as new version/);
      assert.equal(await page.locator("[data-newsroom-article-save]").isDisabled(), true, "Save draft would republish at once, so it is off");
      assert.equal(await page.locator("[data-newsroom-article-publish]").isDisabled(), true, "and so is Publish");
      assert.match(await page.locator("[data-newsroom-article-type-move]").innerText(), /Live as the type Article under \/articles\/\. Publishing it as the type Post moves it under \/posts\/; the old address redirects/);
      await page.locator("[data-newsroom-article-save-version]").click();
      await page.getByText(/Saved as version/).waitFor();
      assert.deepEqual(await pressed(page), ["post"], "the new version is a post");
      assert.match(await page.locator("[data-newsroom-article-type-move]").innerText(), /Live as the type Article/, "the live page is still the article");
      assert.equal(await page.locator("[data-newsroom-article-type-needs-version]").count(), 0, "the new version is a draft");
      await page.locator("[data-newsroom-article-publish]").click();
      await page.getByText(/its address moved, and the old address redirects/).waitFor();
      assert.equal(await page.locator("[data-newsroom-article-type-move]").count(), 0, "once published there is nothing left to warn about");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Publishing a live Story as a type the site publishes nowhere would remove its page: Publish is off and the note says why. */
  async live_story_to_a_type_without_a_page() {
    const { browser, page, errors } = await setup(PUBLISHED_ID);
    try {
      await typeButton(page, "guide").click();
      await page.locator("[data-newsroom-article-save-version]").click();
      await page.getByText(/Saved as version/).waitFor();
      assert.equal(await page.locator("[data-newsroom-article-publish]").isDisabled(), true);
      assert.match(await page.locator("[data-newsroom-article-type-move]").innerText(), /would remove the live page, so Publish is off/);
      assert.equal(await page.locator("[data-newsroom-article-no-public-url]").count(), 1);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A site that declares nothing offers the article type and the page; Create Story and the editor need no engine change for a new type. */
  async a_site_that_declares_nothing() {
    const { browser, page, errors } = await setup(DRAFT_ID, 1280, {});
    try {
      const labels = (await page.locator("[data-newsroom-article-type]").allInnerTexts()).map((label) => label.trim());
      assert.deepEqual(labels, ["Article", "Page"]);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** On a phone the buttons are large targets and nothing scrolls sideways. */
  async phone() {
    const { browser, page, errors } = await setup(DRAFT_ID, 375);
    try {
      for (const button of await page.locator("[data-newsroom-article-type]").all()) assert.ok((await button.boundingBox())!.height >= 40, "at least forty pixels tall");
      await typeButton(page, "guide").click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Story type editor scenario passed: ${name}`);
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
