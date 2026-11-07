/**
 * Fixture-only browser acceptance for Administration > Policies > Visual style: Brand, Image types, a type's page, its Examples grid and the no-style warning, in light and
 * dark, on an in-memory stand-in for the image door. No network, no AWS, nothing written anywhere. Run one scenario with `tsx scripts/test-visual-style-admin.ts brand_page`;
 * set PAPYRUS_VISUAL_STYLE_SHOTS=<dir> to write the screenshots (page, a type's page, the examples grid and the warning, light and dark, at 1440 and 375 wide).
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Locator, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://visual-style.test";
const shots = process.env.PAPYRUS_VISUAL_STYLE_SHOTS;
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

const DOOR_STUB = `export const imageDoor = async () => { throw new Error("The fixture supplies its own door."); }; export const uploadExample = imageDoor; export const exampleUrl = imageDoor;`;

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent", loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    plugins: [{ name: "fixture-door", setup(builder) {
      builder.onResolve({ filter: /image-door-client$/ }, () => ({ path: "door", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ contents: DOOR_STUB, loader: "js", resolveDir: root }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "visual-style-fixture-entry.tsx", contents: `
import { createRoot } from "react-dom/client";
import { VisualStyleAdmin } from "./components/visual-style-admin";
import { createFixtureBackend } from "./scripts/fixtures/visual-style-fixture";
const backend = createFixtureBackend(new URLSearchParams(location.search).get("scenario") || "ready");
window.fixtureBackend = backend;
createRoot(document.getElementById("root")).render(
  <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode={document.documentElement.dataset.colorMode || "light"} style={{ display: "block", height: "100vh", overflowY: "auto", padding: "0 16px" }}>
    <div className="news-desk-columns news-desk-columns--administration" data-news-desk-section="administration" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", width: "100%" }}><div className="news-desk-main-column">
      <section className="category-steering-section category-steering-section--lead"><h2 style={{ fontSize: "1.25rem", fontWeight: 600, padding: "12px 0" }}>Administration</h2>
        <div className="news-desk-settings-shell">
          <nav className="news-desk-settings-nav" aria-label="Administration settings"><a href="#users"><strong>Users</strong><span>Roles and identity merges</span></a><a data-active="true" href="#policies"><strong>Policies</strong><span>Publication and category doctrine</span></a><a href="#procedures"><strong>Procedures</strong><span>Procedure registry</span></a></nav>
          <div className="news-desk-settings-panel">
            <div data-news-desk-admin-panel="policies">
              <VisualStyleAdmin door={backend.door} isAdmin pictureUrl={backend.url} uploadPicture={backend.upload} />
            </div>
          </div>
        </div></section>
    </div></div>
  </div>
);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

async function setup(scenario: string, width = 1440, height = 1000, mode: "light" | "dark" = "light") {
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
  await page.goto(`${origin}/?scenario=${scenario}`);
  await page.locator("[data-news-desk-admin-panel='visual-style']").waitFor();
  return { browser, page, errors };
}

const calls = (page: Page) => page.evaluate(() => (window as any).fixtureBackend.calls as { op: string; input: any }[]);
const flat = (text: string) => text.replace(/\s+/g, " ");
const status = (page: Page) => page.locator("[data-visual-style-status]");
const typeRow = (page: Page, key: string) => page.locator(`[data-image-type-row="${key}"]`);
const noOverflow = async (page: Page) => assert.equal(await page.evaluate(() => { const root = document.querySelector(".newsroom-organizer")!; return root.scrollWidth <= root.clientWidth && document.documentElement.scrollWidth <= window.innerWidth; }), true, "no horizontal scroll");

async function shoot(page: Page, name: string, target?: Locator) {
  if (!shots) return;
  fs.mkdirSync(shots, { recursive: true });
  if (target) { await target.scrollIntoViewIfNeeded(); await target.screenshot({ path: `${shots}/${name}.png` }); return; }
  // The whole page: grow the window to the page's height for the picture, then put it back.
  const size = page.viewportSize()!;
  const height = await page.evaluate(() => Math.ceil(document.querySelector(".newsroom-organizer")!.scrollHeight));
  await page.setViewportSize({ width: size.width, height: Math.min(Math.max(height, size.height), 8000) });
  await page.screenshot({ path: `${shots}/${name}.png` });
  await page.setViewportSize(size);
}

async function openTypes(page: Page) { await page.getByRole("button", { name: /Image types/ }).click(); await page.locator("[data-visual-style-page='types']").waitFor(); }
async function openType(page: Page, key: string) { await openTypes(page); await typeRow(page, key).getByRole("button", { name: "Open" }).click(); await page.locator(`[data-image-type="${key}"]`).waitFor(); }

const scenarios: Record<string, () => Promise<void>> = {
  async brand_page() {
    const { browser, page, errors } = await setup("ready");
    try {
      const text = await page.locator("[data-news-desk-admin-panel='visual-style']").innerText();
      assert.match(text, /Visual style/); assert.match(text, /Version 3, last changed by Ryan/); assert.match(text, /Binding rules/);
      assert.equal(await page.locator("[data-review-choice='after_the_fact']").getAttribute("aria-pressed"), "true");
      assert.match(await page.locator("[data-review-choice='after_the_fact']").innerText(), /\(selected\)/, "the selection is said in words, not only shown");
      assert.equal(await page.locator("select").count(), 0, "buttons and text boxes, never dropdowns");
      await page.locator("[data-review-choice='before_publish']").click();
      await status(page).getByText(/Review setting saved \(version 4\)/).waitFor();
      assert.match(await page.locator("[data-review-choice='before_publish']").innerText(), /\(selected\)/);
      const saved = (await calls(page)).filter((call) => call.op === "image_profile_save");
      assert.deepEqual(saved[0].input.document, { imageReview: "before_publish" }); assert.equal(saved[0].input.expectedCurrentVersionId, "item-editorial-doctrine-visual-style-v3");
      await page.getByLabel("Summary").fill("Calmer.");
      await page.getByRole("button", { name: "Save brand" }).click();
      await status(page).getByText(/Brand saved \(version 5\)/).waitFor();
      assert.equal(await page.evaluate(() => (window as any).fixtureBackend.current().identity.summary), "Calmer.");
      assert.equal(await page.getByLabel("Colour 1 hex value").inputValue(), "#e9ecf0");
      await page.getByLabel("Colour 1 hex value").fill("nope");
      await page.getByRole("button", { name: "Save brand" }).click();
      await status(page).getByText(/Every colour needs a name and a hex value/).waitFor();
      await noOverflow(page);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async image_types_list() {
    const { browser, page, errors } = await setup("ready");
    try {
      await openTypes(page);
      assert.equal(await page.locator("[data-image-type-row]").count(), 6);
      const social = flat(await typeRow(page, "cover-illustration").innerText());
      assert.match(social, /Headline illustration/); assert.match(social, /As a thumbnail, as small as 160px/); assert.match(social, /3 pictures/); assert.match(social, /1\. Stock 2\. Generated/);
      assert.match(flat(await typeRow(page, "inline-illustration").innerText()), /Never as a thumbnail, as small as 343px/);
      assert.match(flat(await typeRow(page, "inline-illustration").innerText()), /Starts from Headline illustration. Its examples are its own/);
      assert.match(await typeRow(page, "inline-illustration").innerText(), /None yet/);
      await page.locator("[data-add-type]").click();
      await page.getByRole("button", { name: "Add this type" }).click();
      await page.getByText("Give the type a name.").waitFor();
      await page.getByLabel("Name", { exact: true }).fill("Social card");
      await page.getByRole("button", { name: "Add this type" }).click();
      await page.getByText(/There is already a type called Social card/).waitFor();
      await page.getByLabel("Name", { exact: true }).fill("Newsletter picture");
      await page.getByLabel("One plain sentence about it").fill("A picture at the top of the newsletter.");
      await page.getByRole("group", { name: "Start from" }).getByRole("button", { name: "Social card" }).click();
      await page.getByRole("button", { name: "Add this type" }).click();
      await page.locator("[data-image-type='newsletter-picture']").waitFor();
      const added = (await calls(page)).filter((call) => call.op === "image_profile_save").at(-1)!.input.document;
      assert.deepEqual(added.imageTypes["newsletter-picture"], { label: "Newsletter picture", description: "A picture at the top of the newsletter.", extends: "social-card" });
      assert.match(await page.locator("[data-image-type='newsletter-picture']").innerText(), /Starts from Social card/);
      await page.getByRole("button", { name: "All image types" }).click();
      await typeRow(page, "newsletter-picture").getByRole("button", { name: "Retire" }).click();
      await page.getByText("Retired types").waitFor();
      assert.equal(await page.locator("[data-image-type-row][data-retired]").count(), 1);
      await typeRow(page, "newsletter-picture").getByRole("button", { name: "Bring back" }).click();
      await page.getByText(/Image type brought back/).waitFor();
      await noOverflow(page);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async type_page() {
    const { browser, page, errors } = await setup("ready");
    try {
      await openType(page, "inline-illustration");
      const effective = page.locator("[data-visual-style-effective]");
      await effective.locator("[data-effective-rules]").waitFor();
      const lines = await effective.locator("[data-effective-line]").allInnerTexts();
      assert.ok(lines.some((line) => /Flat shapes with generous rounded corners/.test(line) && /from Brand/.test(line)), lines.join("|"));
      assert.ok(lines.some((line) => /One large disc cropped by the edge/.test(line) && /from Parent type: Headline illustration/.test(line)));
      assert.ok(lines.some((line) => /Several elements may share the scene/.test(line) && /from This type/.test(line)));
      assert.ok(lines.some((line) => /A place or a moment/.test(line) && /from Family: Editorial illustration/.test(line)));
      const effectiveText = await effective.innerText();
      assert.ok(!/small details/.test(effectiveText.split("Taken off by this type")[0] ?? ""), "a removed item is not in the rules");
      assert.match(effectiveText, /Taken off by this type/); assert.match(effectiveText, /Avoid 'small details' \(taken off by this type\)/); assert.match(effectiveText, /Binding rules \(cannot be loosened\)/);
      assert.match(flat(await page.locator("[data-visual-style-source-order]").innerText()), /1\. Generated .*2\. Stock/);
      await page.getByRole("button", { name: "Move Generated down" }).click();
      await status(page).getByText(/Sources reordered/).waitFor();
      assert.match(flat(await page.locator("[data-visual-style-source-order]").innerText()), /1\. Stock .*2\. Generated/);
      assert.deepEqual((await calls(page)).filter((call) => call.op === "image_profile_save").at(-1)!.input.document, { imageTypes: { "inline-illustration": { sources: ["stock", "generated"] } } });
      await page.getByLabel("What this type should look like").fill("Several elements may share the scene; keep one focal subject.");
      await page.getByRole("button", { name: "Save guidance" }).click();
      await status(page).getByText(/Guidance saved/).waitFor();
      await page.getByRole("button", { name: "All image types" }).click();
      await openType(page, "cover-illustration");
      assert.ok(await page.locator("[data-safe-zones]").isVisible(), "the safe zone is drawn on a sample frame with its words");
      assert.match(await page.locator("[data-safe-zones]").innerText(), /upper third.*hatched on the frame/s);
      await noOverflow(page);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async examples_grid() {
    const { browser, page, errors } = await setup("ready");
    try {
      await openType(page, "cover-illustration");
      const grid = page.locator("[data-examples-grid='cover-illustration']");
      assert.equal(await grid.locator("[data-example]").count(), 3);
      assert.equal(await grid.locator("[data-example-kind='exemplar']").count(), 1);
      assert.match(await grid.innerText(), /Good example/); assert.match(await grid.innerText(), /Avoid this/);
      assert.match(await grid.innerText(), /As a card: 160px/, "a thumbnail type shows each example at its smallest size");
      assert.match(await grid.innerText(), /Not sent to the image model/); assert.match(await grid.innerText(), /Sent to the image model as a style reference/);
      await grid.locator("[data-add-picture]").click();
      await grid.getByRole("button", { name: /Add this picture/ }).click();
      await grid.getByText("Choose a picture first.").waitFor();
      await grid.locator("input[type=file]").setInputFiles({ name: "notes.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") });
      await grid.getByRole("button", { name: /Add this picture/ }).click();
      await grid.getByText(/not a PNG, JPEG or WebP picture/).waitFor();
      await grid.locator("input[type=file]").setInputFiles({ name: "huge.png", mimeType: "image/png", buffer: Buffer.alloc(10 * 1024 * 1024 + 1) });
      await grid.getByRole("button", { name: /Add this picture/ }).click();
      await grid.getByText(/Example pictures must be 10 MB or smaller/).waitFor();
      await grid.locator("input[type=file]").setInputFiles({ name: "calm.png", mimeType: "image/png", buffer: Buffer.from("\x89PNG\r\n\x1a\nfixture") });
      await grid.getByRole("button", { name: "Avoid this", exact: true }).click();
      await grid.getByRole("button", { name: /Add this picture/ }).click();
      await grid.getByText("Say in a few words what to avoid about this picture.").waitFor();
      await grid.getByLabel("What should be avoided?").fill("A busy scene with a face in it.");
      await grid.getByRole("button", { name: /Send to the image model as a style reference: No/ }).click();
      await grid.getByRole("button", { name: /Add this picture/ }).click();
      await status(page).getByText(/Picture added as a picture to avoid \(version 4\)/).waitFor();
      assert.equal(await grid.locator("[data-example]").count(), 4);
      const added = (await calls(page)).find((call) => call.op === "image_profile_example_add")!.input;
      const { attachmentId, ...rest } = added; assert.ok(attachmentId); assert.deepEqual(rest, { imageType: "cover-illustration", kind: "negative", note: "A busy scene with a face in it.", sendToProvider: true, reason: "Added an example picture in Administration", expectedCurrentVersionId: "item-editorial-doctrine-visual-style-v3" });
      await grid.getByRole("button", { name: /Remove this example: A busy scene/ }).click();
      await status(page).getByText(/Picture removed \(version 5\). Older versions of the style still list it./).waitFor();
      assert.equal(await grid.locator("[data-example]").count(), 3);
      await page.getByRole("button", { name: "All image types" }).click();
      await openType(page, "inline-illustration");
      assert.equal(await page.locator("[data-examples-grid='inline-illustration'] [data-example]").count(), 0, "a child type does not inherit its parent's examples");
      assert.match(await page.locator("[data-examples-grid='inline-illustration']").innerText(), /No example pictures yet/);
      await noOverflow(page);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async stale_edit() {
    const { browser, page, errors } = await setup("ready");
    try {
      await page.evaluate(() => (window as any).fixtureBackend.injectConcurrentChange());
      await page.locator("[data-review-choice='before_publish']").click();
      await status(page).getByText(/Someone else changed the style while you were editing/).waitFor();
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async no_style() {
    const { browser, page, errors } = await setup("none");
    try {
      const warning = page.locator("[data-visual-style-warning='no-style']");
      await warning.waitFor();
      const text = await warning.innerText();
      assert.match(text, /This publication has no image style guidelines, so generated images will look unpredictable\. Add guidelines and example pictures here\./);
      assert.match(text, /Pictures can still be searched for and made without a style/);
      assert.equal(await page.locator("[data-visual-style-nav]").count(), 0, "no tabs before there is a profile");
      await warning.getByRole("button", { name: "Draft a starting style" }).click();
      await page.locator("[data-visual-style-draft]").waitFor();
      assert.match(await page.locator("[data-visual-style-draft]").innerText(), /It is not saved yet/);
      assert.equal((await calls(page)).filter((call) => call.op === "image_profile_save").length, 0, "drafting saves nothing");
      await page.getByRole("button", { name: "Save this draft as the first version" }).click();
      await page.getByText(/The first version of the style is saved/).waitFor();
      assert.equal(await page.locator("[data-visual-style-warning]").count(), 0);
      await openTypes(page);
      assert.equal(await page.locator("[data-image-type-row]").count(), 3);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async screenshots() {
    if (!shots) return;
    const pages: Record<string, { scenario: string; steps: (page: Page) => Promise<void>; target?: (page: Page) => Locator }> = {
      "1-visual-style-page": { scenario: "ready", steps: async () => {} },
      "2-image-types": { scenario: "ready", steps: openTypes },
      "3-type-page-inline-illustration": { scenario: "ready", steps: async (page) => { await openType(page, "inline-illustration"); await page.locator("[data-visual-style-effective] [data-effective-rules]").waitFor(); } },
      "4-examples-grid": { scenario: "ready", steps: async (page) => { await openType(page, "cover-illustration"); await page.locator("[data-examples-grid='cover-illustration'] [data-example]").first().waitFor(); await page.waitForTimeout(200); }, target: (page) => page.locator("[data-visual-style-examples]") },
      "5-add-picture": { scenario: "ready", steps: async (page) => { await openType(page, "cover-illustration"); await page.locator("[data-add-picture]").click(); await page.waitForTimeout(200); }, target: (page) => page.locator("[data-visual-style-examples]") },
      "6-no-style-warning": { scenario: "none", steps: async (page) => { await page.locator("[data-visual-style-warning]").waitFor(); } },
    };
    for (const mode of ["light", "dark"] as const) {
      for (const width of [1440, 375]) {
        for (const [name, entry] of Object.entries(pages)) {
          const { browser, page } = await setup(entry.scenario, width, 1000, mode);
          await entry.steps(page);
          await shoot(page, `${name}-${mode}-${width}`, entry.target?.(page));
          await browser.close();
        }
      }
    }
  },
};

scenarios.peek = async () => { const { browser, page } = await setup("ready", 1440, 900, "light"); await page.screenshot({ path: process.env.PEEK ?? "/tmp/peek.png" }); await browser.close(); };
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
