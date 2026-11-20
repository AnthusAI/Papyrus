/**
 * Fixture-only browser acceptance for Administration > Editorial checks > Settings > how the site serves its languages: which enabled languages are public, each
 * language's URL prefix and slug policy, the server's refusal shown before saving, and a save that keeps every key the form did not edit. Runs the real panel at 1440
 * and 375 wide against the in-memory door of scripts/fixtures/editorial-languages-fixture.ts. No network, no AWS. Run one scenario with
 * `tsx scripts/test-editorial-languages-admin.ts make_public`; set PAPYRUS_EDITORIAL_LANGUAGES_SHOTS=<dir> to write screenshots.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://editorial-languages.test";
const shots = process.env.PAPYRUS_EDITORIAL_LANGUAGES_SHOTS;
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

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic", logLevel: "silent", loader: { ".css": "empty", ".woff2": "empty", ".woff": "empty" },
    define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    plugins: [{ name: "fixture-door", setup(builder) {
      builder.onResolve({ filter: /editorial-checks-client$/ }, () => ({ path: `${root}scripts/fixtures/editorial-languages-fixture.ts` }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "editorial-languages-entry.tsx", contents: `
import { createRoot } from "react-dom/client";
import { EditorialChecksAdminPanel } from "./components/editorial-checks-admin-panel";
createRoot(document.getElementById("root")).render(
  <div className="newsroom-organizer" data-kanbus-theme="newspaper-gothic" data-color-mode={document.documentElement.dataset.colorMode || "light"} style={{ display: "block", height: "100vh", overflowY: "auto", padding: "0 16px" }}>
    <div className="news-desk-columns news-desk-columns--administration" data-news-desk-section="administration" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", width: "100%" }}><div className="news-desk-main-column">
      <section className="category-steering-section category-steering-section--lead"><h2 style={{ fontSize: "1.25rem", fontWeight: 600, padding: "12px 0" }}>Administration</h2>
        <div className="news-desk-settings-panel"><EditorialChecksAdminPanel /></div>
      </section>
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
  await page.locator("[data-editorial-languages]").waitFor();
  return { browser, page, errors };
}

const calls = (page: Page) => page.evaluate(() => (window as any).fixtureBackend.calls as { op: string; input: any }[]);
const saves = async (page: Page) => (await calls(page)).filter((call) => call.op === "saveSettings");
const language = (page: Page, tag: string) => page.locator(`[data-editorial-language='${tag}']`);
const saveButton = (page: Page) => page.getByRole("button", { name: "Save settings" });
const status = (page: Page) => page.locator("[data-editorial-languages-status]");
/** The languages controls fit the page width: nothing in them reaches past the organizer (the rest of the panel is not this feature's). */
const noOverflow = async (page: Page) => {
  const wide = await page.evaluate(() => {
    const root = document.querySelector("[data-editorial-languages]")!;
    const limit = document.querySelector(".newsroom-organizer")!.clientWidth;
    return [root, ...root.querySelectorAll("*")].filter((element) => element.getBoundingClientRect().right > limit + 1).slice(0, 3).map((element) => `${element.tagName}.${element.className} ${element.textContent?.slice(0, 40)}`);
  });
  if (process.env.DEBUG_WIDTH) console.log(await page.evaluate(() => { const f = document.querySelector("[data-editorial-languages]") as HTMLElement; f.style.display = "none"; const w = document.querySelector("section[data-news-desk-admin-panel]")!.getBoundingClientRect().right; f.style.display = ""; return `section right without the languages controls: ${w}`; })); if (process.env.DEBUG_WIDTH) console.log(await page.evaluate(() => { const out: string[] = []; let node: Element | null = document.querySelector("[data-editorial-languages]"); while (node) { const r = node.getBoundingClientRect(); out.push(`${node.tagName}.${String(node.className).slice(0, 30)} ${Math.round(r.left)}-${Math.round(r.right)} cw=${node.clientWidth}`); node = node.parentElement; } return out.join("\n"); }));
  assert.deepEqual(wide, [], "no horizontal scroll");
};
const settled = async (page: Page) => { await page.locator("[data-editorial-language]").first().waitFor(); await status(page).getByText("Checking").waitFor({ state: "detached" }); };

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
  async make_public() {
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("plain", width);
      try {
        const text = await page.locator("[data-editorial-languages]").innerText();
        assert.match(text, /An enabled language that is not public is written, translated and checked, but gets no page/);
        assert.match(text, /The primary language is always public/);
        await settled(page);
        assert.equal(await page.locator("[data-editorial-language]").count(), 2, "one block for each enabled language other than the primary");
        assert.equal(await language(page, "es-419").locator("[data-language-public]").isChecked(), false, "only the primary is public by default");
        await language(page, "es-419").locator("[data-language-public]").check();
        await settled(page);
        await saveButton(page).click();
        await page.getByText("Settings saved.").waitFor();
        const sent = (await saves(page))[0].input.settings;
        assert.deepEqual(sent.languages.public, ["en", "es-419"]);
        assert.deepEqual(sent.languages.futureKey, { kept: true }, "a key the form does not show is kept");
        assert.equal(sent.guidance, "Plain words.");
        assert.deepEqual(sent.languages.enabled, ["en", "es-419", "zh-Hans"]);
        await noOverflow(page);
        await shoot(page, `public-${width}`);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  async prefix_and_slug() {
    const { browser, page, errors } = await setup("plain");
    try {
      await settled(page);
      const es = language(page, "es-419");
      assert.equal(await es.locator("[data-language-prefix]").getAttribute("placeholder"), "es", "the default prefix is shown");
      assert.match(await es.innerText(), /Web address prefix \(default es\)/);
      assert.match(await es.innerText(), /Its pages live under \/es\//);
      assert.equal(await es.locator("[data-language-slug] option:checked").innerText(), "Default (translated title, in plain letters)");
      assert.match(await language(page, "zh-Hans").locator("[data-language-slug] option:checked").innerText(), /Default \(title in its own script/);
      await es.locator("[data-language-prefix]").fill("latam");
      await es.locator("[data-language-slug]").selectOption("primary");
      await es.getByText("Its pages live under /latam/").waitFor();
      await settled(page);
      await saveButton(page).click();
      await page.getByText("Settings saved.").waitFor();
      const sent = (await saves(page))[0].input.settings.languages;
      assert.deepEqual(sent.prefixes, { "es-419": "latam" });
      assert.deepEqual(sent.slugs, { "es-419": "primary" });
      assert.equal("public" in sent, false, "nothing made public, so no public list");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async refused() {
    for (const width of [1440, 375]) {
      const { browser, page, errors } = await setup("plain", width);
      try {
        await settled(page);
        await language(page, "es-419").locator("[data-language-prefix]").fill("zh");
        await page.locator("[data-editorial-languages-refusal]").getByText(/es-419 and zh-Hans would both be served under \/zh\//).waitFor();
        assert.equal(await saveButton(page).isDisabled(), true, "a refused setting cannot be saved");
        assert.equal((await saves(page)).length, 0);
        assert.equal(await language(page, "es-419").locator("[data-language-prefix]").isVisible(), true, "the field that caused it stays editable");
        await shoot(page, `refused-${width}`);
        await language(page, "es-419").locator("[data-language-prefix]").fill("latam");
        await page.locator("[data-editorial-languages-refusal]").waitFor({ state: "detached" });
        await settled(page);
        assert.equal(await saveButton(page).isDisabled(), false);
        await noOverflow(page);
        assert.deepEqual(errors, []);
      } finally { await browser.close(); }
    }
  },

  async keeps_stored() {
    const { browser, page, errors } = await setup("configured");
    try {
      await settled(page);
      assert.equal(await language(page, "es-419").locator("[data-language-public]").isChecked(), true);
      assert.equal(await language(page, "es-419").locator("[data-language-prefix]").inputValue(), "latam");
      assert.equal(await language(page, "zh-Hans").locator("[data-language-slug]").inputValue(), "pinyin");
      await page.getByLabel(/House guidance for rewrites/).fill("Plain words, short sentences.");
      await settled(page);
      await saveButton(page).click();
      await page.getByText("Settings saved.").waitFor();
      const sent = (await saves(page))[0].input.settings;
      assert.equal(sent.guidance, "Plain words, short sentences.");
      assert.deepEqual(sent.languages, {
        primary: "en", enabled: ["en", "es-419", "zh-Hans"], public: ["en", "es-419"], prefixes: { "es-419": "latam" }, slugs: { "zh-Hans": "pinyin" }, futureKey: { kept: true },
      }, "saving one setting leaves the serving keys exactly as stored");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async remove_language() {
    const { browser, page, errors } = await setup("configured");
    try {
      await settled(page);
      await page.getByLabel(/Languages the site writes in/).fill("en, es-419");
      await page.locator("[data-editorial-language='zh-Hans']").waitFor({ state: "detached" });
      await settled(page);
      await saveButton(page).click();
      await page.getByText("Settings saved.").waitFor();
      const sent = (await saves(page))[0].input.settings.languages;
      assert.deepEqual(sent.enabled, ["en", "es-419"]);
      assert.equal("slugs" in sent, false, "the language taken out takes its slug policy with it");
      assert.deepEqual(sent.public, ["en", "es-419"]);
      assert.deepEqual(sent.prefixes, { "es-419": "latam" });
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  async screenshots() {
    for (const mode of ["light", "dark"] as const) for (const width of [1440, 375]) {
      const { browser, page } = await setup("configured", width, 1000, mode);
      await settled(page);
      await shoot(page, `languages-${mode}-${width}`);
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
