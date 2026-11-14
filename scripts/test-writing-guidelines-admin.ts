/**
 * Fixture-only browser acceptance for Administration > Policies > Writing guidelines: the Site and section tabs, saving with a reason, history and diff, locked fields,
 * the read-only view for editors and the Story picker, at 1440 and 375 wide, on an in-memory stand-in for the guidelines door. No network, no AWS, nothing written
 * anywhere. Run one scenario with `tsx scripts/test-writing-guidelines-admin.ts site_edit`; set PAPYRUS_WRITING_GUIDELINES_SHOTS=<dir> to write screenshots.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Locator, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://writing-guidelines.test";
const shots = process.env.PAPYRUS_WRITING_GUIDELINES_SHOTS;
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
      entryPoints: ["node_modules/@kanbus/ui/dist/styles/kanban.css", "node_modules/@kanbus/ui/dist/styles/themes/index.css", "components/newsroom-theme.css", "components/newsroom-organizer.css"], outdir: "out",
    });
    return [tailwindCss, ...bundled.outputFiles.map((output) => output.text)].join("\n");
  })();
  return css;
}

const STUBS = `export const guidelinesDoor = async () => { throw new Error("The fixture supplies its own door."); }; export const listPublishedStories = guidelinesDoor; export const listPolicies = guidelinesDoor;`;

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent", loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    plugins: [{ name: "fixture-door", setup(builder) {
      builder.onResolve({ filter: /guidelines-door-client$|editorial-checks-client$/ }, () => ({ path: "stubs", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ contents: STUBS, loader: "js", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "writing-guidelines-fixture-entry.tsx", contents: `
import { createRoot } from "react-dom/client";
import { WritingGuidelinesAdmin } from "./components/writing-guidelines-admin-panel";
import { createFixtureBackend, SECTIONS } from "./scripts/fixtures/writing-guidelines-fixture";
const params = new URLSearchParams(location.search);
const backend = createFixtureBackend(params.get("scenario") || "ready");
window.fixtureBackend = backend;
createRoot(document.getElementById("root")).render(
  <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode={document.documentElement.dataset.colorMode || "light"} style={{ display: "block", height: "100vh", overflowY: "auto", padding: "0 16px" }}>
    <div className="news-desk-columns news-desk-columns--administration" data-news-desk-section="administration" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", width: "100%" }}><div className="news-desk-main-column">
      <section className="category-steering-section category-steering-section--lead"><h2 style={{ fontSize: "1.25rem", fontWeight: 600, padding: "12px 0" }}>Administration</h2>
        <div className="news-desk-settings-panel"><div data-news-desk-admin-panel="policies">
          <WritingGuidelinesAdmin door={backend.door} isAdmin={params.get("role") !== "editor"} listChecks={backend.checks} listStories={backend.stories} sections={SECTIONS} />
        </div></div>
      </section>
    </div></div>
  </div>
);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(scenario: string, width = 1440, height = 1000, mode: "light" | "dark" = "light", role: "admin" | "editor" = "admin") {
  const script = await browserBundle();
  const styles = await stylesheet();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ colorScheme: mode });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html data-color-mode="${mode}" class="${mode === "dark" ? "dark" : "light-theme"}"><head><meta name="viewport" content="width=device-width"><style>${styles}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/?scenario=${scenario}&role=${role}`);
  await page.locator("[data-news-desk-admin-panel='writing-guidelines']").waitFor();
  return { browser, page, errors };
}

const calls = (page: Page) => page.evaluate(() => (window as any).fixtureBackend.calls as { op: string; input: any }[]);
const flat = (text: string) => text.replace(/\s+/g, " ");
const status = (page: Page) => page.locator("[data-writing-guidelines-status]");
const tabButton = (page: Page, key: string) => page.locator(`[data-writing-guidelines-tab='${key}']`);
const pageButton = (page: Page, name: string) => page.locator(`[data-writing-guidelines-page='${name}']`);
const field = (page: Page, name: string) => page.locator(`[data-field='${name}']`);
const noOverflow = async (page: Page) => assert.equal(await page.evaluate(() => { const root = document.querySelector(".newsroom-organizer")!; return root.scrollWidth <= root.clientWidth && document.documentElement.scrollWidth <= window.innerWidth; }), true, "no horizontal scroll");
const saves = async (page: Page) => (await calls(page)).filter((call) => call.op === "guidelines_save");

async function shoot(page: Page, name: string) {
  if (!shots) return;
  fs.mkdirSync(shots, { recursive: true });
  const size = page.viewportSize()!;
  const height = await page.evaluate(() => Math.ceil(document.querySelector(".newsroom-organizer")!.scrollHeight));
  await page.setViewportSize({ width: size.width, height: Math.min(Math.max(height, size.height), 8000) });
  await page.screenshot({ path: `${shots}/${name}.png` });
  await page.setViewportSize(size);
}

const scenarios: Record<string, () => Promise<void>> = {
  async site_edit() {
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("ready", width);
      try {
        const text = await page.locator("[data-news-desk-admin-panel='writing-guidelines']").innerText();
        assert.match(text, /Site version 1, last changed by Ryan/); assert.match(text, /Binding rules/); assert.match(text, /Never describe a product as revolutionary/);
        assert.equal(await field(page, "tone").locator("textarea").inputValue(), "Plain and specific.\nCalm, never breathless.");
        await field(page, "tone").locator("textarea").fill("Plain and specific.\nCalm, never breathless.\nWarm toward readers.");
        await page.locator("[data-show-changes]").click();
        await page.locator("[data-change-preview]").getByText(/Tone: changed from/).waitFor();
        await page.locator("[data-save-reason]").fill("Add warmth after the reader survey");
        await page.locator("[data-save]").click();
        await status(page).getByText(/Saved as version 2/).waitFor();
        const sent = (await saves(page))[0].input;
        assert.equal(sent.kind, "writing"); assert.equal(sent.expectedCurrentVersionId, "site-v1"); assert.equal(sent.reason, "Add warmth after the reader survey");
        assert.deepEqual(sent.document.tone, ["Plain and specific.", "Calm, never breathless.", "Warm toward readers."]);
        assert.deepEqual(sent.document.constraints, [{ id: "no-hype", text: "Never describe a product as revolutionary." }], "binding rules are carried over untouched");
        await pageButton(page, "history").click();
        await page.locator("[data-version='2']").waitFor();
        const history = flat(await page.locator("[data-writing-guidelines-page-body='history']").innerText());
        assert.match(history, /Version 2 \(current\)/); assert.match(history, /Why: Add warmth after the reader survey/); assert.match(history, /Version 1/); assert.match(history, /Why: First guidelines/);
        await page.locator("[data-version='2'] button").click(); await page.locator("[data-version='1'] button").click();
        await page.locator("[data-compare]").click();
        await page.locator("[data-version-diff]").getByText(/Tone: changed from/).waitFor();
        await noOverflow(page);
        if (width === 1440) await shoot(page, "history-1440"); else await shoot(page, "history-375");
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  async section_override() {
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("ready", width);
      try {
        assert.equal(await page.locator("[data-writing-guidelines-tab]").count(), 3, "a Site tab and one tab per section");
        await tabButton(page, "ai").click();
        await page.locator("[data-no-document]").getByText(/follows the site's guidelines/).waitFor();
        await field(page, "tone").locator("textarea").fill("More technical in this section.");
        await field(page, "lexicon.avoid").locator("textarea").fill("synergy");
        await page.locator("[data-save-reason]").fill("AI desk needs a technical tone");
        await page.locator("[data-save]").click();
        await status(page).getByText(/Saved as version 1/).waitFor();
        const sent = (await saves(page))[0].input;
        assert.equal(sent.section, "ai"); assert.equal(sent.expectedCurrentVersionId, "none");
        assert.deepEqual(sent.document.tone, ["More technical in this section."]);
        for (const publicationOnly of ["locked", "constraints"]) assert.equal(publicationOnly in sent.document, false, `${publicationOnly} is not part of a section's document`);
        await pageButton(page, "effective").click();
        const effective = (name: string) => page.locator(`[data-effective-field='${name}'] [data-field-source]`);
        await effective("tone").waitFor();
        assert.match(await effective("tone").innerText(), /Source: Site and this section/);
        assert.match(await effective("lexicon").innerText(), /Source: Site and this section/);
        assert.match(await effective("voice").innerText(), /Source: Site$/);
        assert.match(await effective("sentenceStyle").innerText(), /Source: Site$/);
        assert.match(await effective("audience").innerText(), /Source: Locked by site/);
        assert.match(await page.locator("[data-effective-field='tone']").innerText(), /Calm, never breathless[\s\S]*More technical in this section/);
        await noOverflow(page);
        await shoot(page, `section-effective-${width}`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  async locked_field() {
    const { browser, page, errors } = await setup("ready");
    try {
      await tabButton(page, "culture").click();
      await field(page, "audience").getByText("Locked by site").waitFor();
      assert.equal(await field(page, "audience").locator("textarea").isDisabled(), true, "a locked field cannot be changed on a section tab");
      assert.equal(await field(page, "voice").locator("input").isDisabled(), false, "an unlocked choice can be set");
      assert.equal(await field(page, "voice").locator("input").getAttribute("placeholder"), "Site: Plain newsroom");
      await tabButton(page, "site").click();
      assert.equal(await field(page, "audience").locator("textarea").isDisabled(), false, "the site tab can change it");
      assert.equal(await page.locator("[data-lock-field='audience']").getAttribute("aria-pressed"), "true");
      assert.match(await page.locator("[data-lock-field='audience']").innerText(), /Audience: locked/, "locked says so in words");
      assert.match(await page.locator("[data-lock-field='voice']").innerText(), /Voice: open/);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async editor_read_only() {
    const { browser, page, errors } = await setup("ready", 1440, 1000, "light", "editor");
    try {
      const text = flat(await page.locator("[data-news-desk-admin-panel='writing-guidelines']").innerText());
      assert.match(text, /Read only: You can read the writing guidelines. Only an admin can change them/);
      assert.equal(await page.locator("[data-save]").count(), 0, "no save button");
      assert.equal(await page.locator("[data-story-picker]").count(), 0, "no picker");
      const boxes = page.locator("[data-writing-guidelines-page-body='edit'] textarea, [data-writing-guidelines-page-body='edit'] input");
      for (let index = 0; index < await boxes.count(); index += 1) assert.equal(await boxes.nth(index).isDisabled(), true, "every box is read only");
      assert.match(await field(page, "tone").locator("textarea").inputValue(), /Plain and specific/);
      await pageButton(page, "history").click(); await page.locator("[data-version='1']").waitFor();
      await shoot(page, "editor-read-only-1440");
      assert.equal((await saves(page)).length, 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async reason_required() {
    const { browser, page, errors } = await setup("ready");
    try {
      await field(page, "tone").locator("textarea").fill("Changed.");
      assert.equal(await page.locator("[data-save]").isDisabled(), true, "saving is not possible without a reason");
      await page.locator("[data-reason-needed]").getByText(/once you give a reason/).waitFor();
      await page.locator("[data-save-reason]").fill("   ");
      assert.equal(await page.locator("[data-save]").isDisabled(), true, "blank spaces are not a reason");
      await page.locator("[data-save-reason]").fill("Because");
      assert.equal(await page.locator("[data-save]").isDisabled(), false);
      assert.equal((await saves(page)).length, 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async exemplar_pick() {
    const { browser, page, errors } = await setup("ready");
    try {
      await page.locator("[data-story-picker] input").fill("headline");
      await page.locator("[data-story-option]").getByText("What a good headline does").waitFor();
      assert.equal(await page.locator("[data-story-option]").count(), 1, "the picker narrows to matching published Stories");
      await page.locator("[data-story-option='story-3'] button").click();
      await page.locator("[data-exemplar='story-3']").getByText("What a good headline does").waitFor();
      await page.getByLabel("Why What a good headline does is a good example").fill("Says the news in nine words.");
      await page.locator("[data-save-reason]").fill("Add a voice example");
      await page.locator("[data-save]").click();
      await status(page).getByText(/Saved as version 2/).waitFor();
      assert.deepEqual((await saves(page))[0].input.document.exemplars, [{ storyLineageId: "story-3", note: "Says the news in nine words." }]);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async empty_and_checks() {
    const empty = await setup("empty");
    try {
      assert.match(await empty.page.locator("[data-writing-guidelines-warning]").innerText(), /no writing guidelines yet/);
      await empty.page.locator("[data-save-reason]").fill("First guidelines");
      await field(empty.page, "tone").locator("textarea").fill("Plain.");
      await empty.page.locator("[data-save]").click();
      await status(empty.page).getByText(/Saved as version 1/).waitFor();
      assert.equal((await saves(empty.page))[0].input.expectedCurrentVersionId, "none");
      assert.deepEqual(empty.errors, []);
    } finally { await empty.browser.close(); }
    const { browser, page, errors } = await setup("ready");
    try {
      await page.locator("[data-derived-check='c1']").waitFor();
      assert.equal(await page.locator("[data-derived-check]").count(), 1, "only checks drawn from these guidelines are listed");
      assert.match(await page.locator("[data-derived-checks]").innerText(), /Avoid the word leverage/);
      assert.equal(await page.locator("[data-checks-link]").getAttribute("href"), "/newsroom/administration/editorial-checks");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async screenshots() {
    for (const mode of ["light", "dark"] as const) for (const width of [1440, 375]) {
      const { browser, page } = await setup("ready", width, 1000, mode);
      await shoot(page, `site-${mode}-${width}`);
      await tabButton(page, "culture").click(); await shoot(page, `section-locked-${mode}-${width}`);
      await browser.close();
    }
  },
};

const wanted = process.argv[2];
const names = wanted ? [wanted] : Object.keys(scenarios).filter((name) => name !== "screenshots" || shots);
async function main() {
  for (const name of names) {
    if (!scenarios[name]) throw new Error(`No scenario ${name}`);
    await scenarios[name]();
    console.log(`ok - ${name}`);
  }
}
main().catch((error) => { console.error(error); process.exit(1); });
