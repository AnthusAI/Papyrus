/**
 * Fixture-only browser acceptance for Administration > Policies > Writing guidelines: the Site and section tabs, saving with a reason, history and diff, locked fields,
 * the guideline files editor (field files and rule files added, edited, removed and rejected), the read-only view for editors and the Story picker, at 1440 and 375 wide, on an in-memory stand-in for the guidelines door. No network, no AWS, nothing written
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
const file = (page: Page, name: string) => page.locator(`[data-guideline-file='${name}']`);
const openFile = async (page: Page, name: string) => { if ((await file(page, name).locator("[data-file-editor]").count()) === 0) await file(page, name).locator("[data-toggle-file]").click(); await file(page, name).locator("[data-file-editor]").waitFor(); };
const body = async (page: Page, name: string) => { await openFile(page, name); return file(page, name).locator("[data-field='body'] textarea"); };
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
        assert.match(text, /Site version 1, last changed by Ryan/);
        assert.equal(await file(page, "tone").getAttribute("data-file-state"), "unchanged");
        const tone = await body(page, "tone");
        assert.equal(await tone.inputValue(), "- Plain and specific.\n- Calm, never breathless.\n");
        await tone.fill("- Plain and specific.\n- Calm, never breathless.\n- Warm toward readers.\n");
        assert.equal(await file(page, "tone").getAttribute("data-file-state"), "changed");
        await page.locator("[data-show-changes]").click();
        await page.locator("[data-change-preview]").getByText(/tone\/GUIDELINE.md changed/).waitFor();
        await page.locator("[data-change-preview]").getByText(/Tone: changed from/).waitFor();
        await page.locator("[data-save-reason]").fill("Add warmth after the reader survey");
        await page.locator("[data-save]").click();
        await status(page).getByText(/Saved as version 2/).waitFor();
        const sent = (await saves(page))[0].input;
        assert.equal(sent.kind, "writing"); assert.equal(sent.expectedCurrentVersionId, "site-v1"); assert.equal(sent.reason, "Add warmth after the reader survey");
        assert.equal(sent.document, undefined, "the set is sent as files, not as fields");
        assert.match(sent.files["tone/GUIDELINE.md"], /- Warm toward readers\./);
        const before = await page.evaluate(() => (window as any).fixtureBackend.door("guidelines_get", { kind: "writing", version: 1 }));
        for (const path of Object.keys(before.result.files).filter((name) => name !== "tone/GUIDELINE.md")) assert.equal(sent.files[path], before.result.files[path], `${path} is carried over byte for byte`);
        await pageButton(page, "history").click();
        await page.locator("[data-version='2']").waitFor();
        const history = flat(await page.locator("[data-writing-guidelines-page-body='history']").innerText());
        assert.match(history, /Version 2 \(current\)/); assert.match(history, /Why: Add warmth after the reader survey/); assert.match(history, /Version 1/); assert.match(history, /Why: First guidelines/);
        await page.locator("[data-version='2'] button").click(); await page.locator("[data-version='1'] button").click();
        await page.locator("[data-compare]").click();
        await page.locator("[data-version-diff]").getByText(/Tone: changed from/).waitFor();
        await noOverflow(page);
        await shoot(page, `history-${width}`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  async files_listed() {
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("ready", width);
      try {
        const names = await page.locator("[data-guideline-file]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-guideline-file")));
        for (const name of ["tone", "audience", "lexicon", "locked", "constraints", "plain-claims", "source-first", "reading-notes"]) assert.ok(names.includes(name), `${name} is listed`);
        assert.equal(await file(page, "plain-claims").locator("[data-file-role]").getAttribute("data-file-role"), "rule");
        assert.equal(await file(page, "tone").locator("[data-file-role]").getAttribute("data-file-role"), "field");
        assert.match(await file(page, "plain-claims").innerText(), /Severity: Warning/);
        assert.match(await file(page, "source-first").innerText(), /Severity: Error/);
        assert.match(await file(page, "reading-notes").innerText(), /Severity: Guidance/);
        assert.match(await file(page, "plain-claims").locator("[data-check-line]").innerText(), /Derived check: Plain claims \(on\)/);
        assert.match(await file(page, "source-first").locator("[data-check-line]").innerText(), /It needs judgement/, "a rule with only prose says it needs judgement");
        assert.match(await file(page, "reading-notes").locator("[data-check-line]").innerText(), /no check is derived/);
        assert.match(await file(page, "audience").locator("[data-file-locked-for-sections]").innerText(), /Locked: sections cannot change it/, "the site tab says in words that a field is locked");
        await openFile(page, "plain-claims");
        assert.equal(await file(page, "plain-claims").locator("[data-field='avoid'] textarea").inputValue(), "revolutionary\nworld-class");
        assert.equal(await file(page, "plain-claims").locator("[data-field='pattern'] textarea").inputValue(), "\\bvery unique\\b");
        assert.equal(await file(page, "plain-claims").locator("[data-severity='warn']").getAttribute("aria-pressed"), "true");
        assert.equal(await file(page, "plain-claims").locator("[data-field='description'] input").inputValue(), "Claims are plain and sourced.");
        await noOverflow(page);
        await shoot(page, `files-${width}`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  async rule_files() {
    const { browser, page, errors } = await setup("ready");
    try {
      await page.locator("[data-add-rule]").click();
      await page.locator("[data-new-rule-name]").fill("Plain Claims");
      await page.locator("[data-new-rule-problem]").getByText(/lowercase words joined by hyphens/).waitFor();
      assert.equal(await page.locator("[data-new-rule-add]").isDisabled(), true);
      await page.locator("[data-new-rule-name]").fill("plain-claims");
      await page.locator("[data-new-rule-problem]").getByText(/already a file named plain-claims/).waitFor();
      await page.locator("[data-new-rule-name]").fill("tone");
      await page.locator("[data-new-rule-problem]").getByText(/name of a field file/).waitFor();
      await page.locator("[data-new-rule-name]").fill("no-filler");
      await page.locator("[data-new-rule-add]").click();
      assert.equal(await file(page, "no-filler").getAttribute("data-file-state"), "added");
      assert.match(await file(page, "no-filler").locator("[data-file-change]").innerText(), /Added/);
      assert.match(await file(page, "no-filler").locator("[data-check-line]").innerText(), /no check is derived/, "a new rule starts as guidance");
      // a rule file with no description is refused, and the page says which file and which key
      await page.locator("[data-save-reason]").fill("Add a rule");
      await page.locator("[data-save]").click();
      await file(page, "no-filler").locator("[data-file-problem]").getByText(/description must be non-empty text/).waitFor();
      await file(page, "no-filler").locator("[data-field='description'] input").fill("Cut filler words.");
      await file(page, "no-filler").locator("[data-severity='error']").click();
      await file(page, "no-filler").locator("[data-field='avoid'] textarea").fill("very\nreally\n");
      await file(page, "no-filler").locator("[data-field='maxLength'] input").fill("900");
      await file(page, "no-filler").locator("[data-field='body'] textarea").fill("Cut words that add nothing.\n");
      assert.match(await file(page, "no-filler").locator("[data-check-line]").innerText(), /A check is derived when you save/);
      assert.match(await file(page, "no-filler").locator("[data-file-severity]").innerText(), /Severity: Error/);
      // a changed rule can be rejected, and goes back to what is saved
      await openFile(page, "plain-claims");
      await file(page, "plain-claims").locator("[data-severity='error']").click();
      assert.equal(await file(page, "plain-claims").getAttribute("data-file-state"), "changed");
      await file(page, "plain-claims").locator("[data-reject-file]").click();
      assert.equal(await file(page, "plain-claims").getAttribute("data-file-state"), "unchanged");
      await openFile(page, "plain-claims");
      assert.equal(await file(page, "plain-claims").locator("[data-severity='warn']").getAttribute("aria-pressed"), "true");
      // removing a rule shows it as removed, and rejecting brings it back
      await file(page, "reading-notes").locator("[data-remove-file]").click();
      await file(page, "reading-notes").locator("[data-file-removed]").getByText(/deleted when you accept and save/).waitFor();
      assert.match(await file(page, "reading-notes").locator("[data-file-change]").innerText(), /Removed/);
      await file(page, "reading-notes").locator("[data-reject-file]").click();
      assert.equal(await file(page, "reading-notes").getAttribute("data-file-state"), "unchanged");
      await file(page, "reading-notes").locator("[data-remove-file]").click();
      assert.match(await page.locator("[data-change-count]").innerText(), /2 files have changed/);
      await page.locator("[data-show-changes]").click();
      const preview = page.locator("[data-change-preview]");
      await preview.getByText("no-filler/GUIDELINE.md added").waitFor();
      await preview.getByText("reading-notes/GUIDELINE.md removed").waitFor();
      await preview.getByText("Check guideline-no-filler: create").waitFor();
      await page.locator("[data-save]").click();
      await status(page).getByText(/Saved as version 2/).waitFor();
      const sent = (await saves(page))[1].input;
      assert.equal("reading-notes/GUIDELINE.md" in sent.files, false, "the removed rule is not in the set");
      assert.match(sent.files["no-filler/GUIDELINE.md"], /^---\nid: "urn:uuid:[0-9a-f-]+"\ntype: "papyrus:Guideline"\nname: "no-filler"\ndescription: "Cut filler words\."\nkind: "writing"\nscope: "publication"\nseverity: "error"\navoid: \["very", "really"\]\nmaxLength: 900\n---\nCut words that add nothing\.\n$/);
      assert.equal(sent.files["plain-claims/GUIDELINE.md"].includes('severity: "warn"'), true);
      await file(page, "no-filler").waitFor();
      assert.equal(await file(page, "no-filler").getAttribute("data-file-state"), "unchanged", "after the save the set is the saved one");
      assert.equal(await file(page, "reading-notes").count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async section_override() {
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("ready", width);
      try {
        assert.equal(await page.locator("[data-writing-guidelines-tab]").count(), 3, "a Site tab and one tab per section");
        await tabButton(page, "ai").click();
        await page.locator("[data-no-document]").getByText(/follows the site's guidelines/).waitFor();
        assert.equal(await page.locator("[data-add-field-file='locked']").count(), 0, "a section cannot add the site-only files");
        assert.equal(await page.locator("[data-add-field-file='constraints']").count(), 0);
        await page.locator("[data-add-field-file='tone']").click();
        await (await body(page, "tone")).fill("- More technical in this section.\n");
        await page.locator("[data-add-field-file='lexicon']").click();
        await (await body(page, "lexicon")).fill('```json\n{ "avoid": ["synergy"] }\n```\n');
        await page.locator("[data-save-reason]").fill("AI desk needs a technical tone");
        await page.locator("[data-save]").click();
        await status(page).getByText(/Saved as version 1/).waitFor();
        const sent = (await saves(page))[0].input;
        assert.equal(sent.section, "ai"); assert.equal(sent.expectedCurrentVersionId, "none");
        assert.deepEqual(Object.keys(sent.files).sort(), ["lexicon/GUIDELINE.md", "tone/GUIDELINE.md"], "the section's set holds only its additions");
        assert.match(sent.files["tone/GUIDELINE.md"], /scope: "section\/ai"/);
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
      await page.locator("[data-locked-field='audience']").getByText(/Audience: Locked by site/).waitFor();
      assert.equal(await page.locator("[data-add-field-file='audience']").count(), 0, "a locked field cannot be added on a section tab");
      await page.locator("[data-add-field-file='voice']").click();
      await openFile(page, "voice");
      assert.equal(await file(page, "voice").locator("[data-field='body'] textarea").isDisabled(), false, "an unlocked choice can be set");
      assert.match(await file(page, "voice").locator("[data-site-value]").innerText(), /Site: Plain newsroom/);
      await tabButton(page, "site").click();
      await openFile(page, "audience");
      assert.equal(await file(page, "audience").locator("[data-field='body'] textarea").isDisabled(), false, "the site tab can change it");
      assert.match(await file(page, "audience").locator("[data-file-locked-for-sections]").innerText(), /Locked: sections cannot change it/, "locked says so in words");
      assert.equal(await file(page, "voice").locator("[data-file-locked-for-sections]").count(), 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async editor_read_only() {
    const { browser, page, errors } = await setup("ready", 1440, 1000, "light", "editor");
    try {
      const text = flat(await page.locator("[data-news-desk-admin-panel='writing-guidelines']").innerText());
      assert.match(text, /Read only: You can read the writing guidelines. Only an admin can change them/);
      assert.equal(await page.locator("[data-save]").count(), 0, "no save button");
      assert.equal(await page.locator("[data-add-files]").count(), 0, "no way to add a file");
      assert.equal(await page.locator("[data-remove-file]").count(), 0, "no way to remove a file");
      await openFile(page, "tone"); await openFile(page, "plain-claims"); await openFile(page, "exemplars");
      assert.equal(await page.locator("[data-story-picker]").count(), 0, "no picker");
      const boxes = page.locator("[data-writing-guidelines-page-body='edit'] [data-file-editor] textarea, [data-writing-guidelines-page-body='edit'] [data-file-editor] input");
      assert.ok(await boxes.count() > 5);
      for (let index = 0; index < await boxes.count(); index += 1) assert.equal(await boxes.nth(index).isDisabled(), true, "every box is read only");
      assert.match(await (await body(page, "tone")).inputValue(), /Plain and specific/);
      await pageButton(page, "history").click(); await page.locator("[data-version='1']").waitFor();
      await shoot(page, "editor-read-only-1440");
      assert.equal((await saves(page)).length, 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async reason_required() {
    const { browser, page, errors } = await setup("ready");
    try {
      await (await body(page, "tone")).fill("- Changed.\n");
      assert.equal(await page.locator("[data-save]").isDisabled(), true, "saving is not possible without a reason");
      await page.locator("[data-reason-needed]").getByText(/once you give a reason/).waitFor();
      await page.locator("[data-save-reason]").fill("   ");
      assert.equal(await page.locator("[data-save]").isDisabled(), true, "blank spaces are not a reason");
      await page.locator("[data-save-reason]").fill("Because");
      assert.equal(await page.locator("[data-save]").isDisabled(), false);
      await page.locator("[data-reject-all]").click();
      assert.equal(await file(page, "tone").getAttribute("data-file-state"), "unchanged", "Reject all changes puts the saved set back");
      assert.match(await page.locator("[data-change-count]").innerText(), /No file has changed/);
      assert.equal((await saves(page)).length, 0);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async exemplar_pick() {
    const { browser, page, errors } = await setup("ready");
    try {
      await openFile(page, "exemplars");
      await page.locator("[data-story-picker] input").fill("headline");
      await page.locator("[data-story-option]").getByText("What a good headline does").waitFor();
      assert.equal(await page.locator("[data-story-option]").count(), 1, "the picker narrows to matching published Stories");
      await page.locator("[data-story-option='story-3'] button").click();
      await page.locator("[data-exemplar='story-3']").getByText("What a good headline does").waitFor();
      await page.getByLabel("Why What a good headline does is a good example").fill("Says the news in nine words.");
      await page.locator("[data-save-reason]").fill("Add a voice example");
      await page.locator("[data-save]").click();
      await status(page).getByText(/Saved as version 2/).waitFor();
      const text: string = (await saves(page))[0].input.files["exemplars/GUIDELINE.md"];
      assert.deepEqual(JSON.parse(/```json\n([\s\S]*)\n```/.exec(text)![1]), [{ storyLineageId: "story-3", note: "Says the news in nine words." }]);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async empty_and_checks() {
    const empty = await setup("empty");
    try {
      assert.match(await empty.page.locator("[data-writing-guidelines-warning]").innerText(), /no writing guidelines yet/);
      await empty.page.locator("[data-save-reason]").fill("First guidelines");
      await empty.page.locator("[data-add-field-file='tone']").click();
      await (await body(empty.page, "tone")).fill("- Plain.\n");
      await empty.page.locator("[data-save]").click();
      await status(empty.page).getByText(/Saved as version 1/).waitFor();
      assert.equal((await saves(empty.page))[0].input.expectedCurrentVersionId, "none");
      assert.deepEqual(empty.errors, []);
    } finally { await empty.browser.close(); }
    const { browser, page, errors } = await setup("ready");
    try {
      await page.locator("[data-derived-check='c1']").waitFor();
      assert.equal(await page.locator("[data-derived-check]").count(), 2, "only checks drawn from these guidelines are listed");
      assert.match(await page.locator("[data-derived-checks]").innerText(), /Avoid the word leverage/);
      assert.equal(await page.locator("[data-checks-link]").getAttribute("href"), "/newsroom/administration/editorial-checks");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async screenshots() {
    for (const mode of ["light", "dark"] as const) for (const width of [1440, 375]) {
      const { browser, page } = await setup("ready", width, 1000, mode);
      await openFile(page, "plain-claims");
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
