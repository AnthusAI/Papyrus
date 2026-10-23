import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { build } from "esbuild";
import { chromium } from "playwright";

const root = path.resolve(import.meta.dirname, "..");
const fixture = path.join(root, "scripts/reference-import-refresh");

// CI installs the browser with `npx playwright install chromium`; locally set PAPYRUS_CHROMIUM_PATH to reuse one.
const launch = () => chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });

async function bundle() {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "reference-import-refresh-"));
  const stubs = path.join(fixture, "stubs.tsx");
  await build({
    entryPoints: [path.join(fixture, "app.tsx")], bundle: true, outfile: path.join(out, "app.js"), platform: "browser",
    jsx: "automatic", define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' }, logLevel: "silent", absWorkingDir: root,
    alias: { "next/navigation": stubs, "next/link": stubs },
    plugins: [{
      name: "offline", setup(b) {
        b.onResolve({ filter: /(news-desk-client-provider|reader-auth-control|news-desk-taxonomy-client|amplify-client-provider)$/ }, () => ({ path: stubs }));
      },
    }],
  });
  return fs.readFileSync(path.join(out, "app.js"), "utf8");
}

test("References reloads suggestions by itself after an import is saved", async () => {
  const script = await bundle();
  const browser = await launch();
  try {
    const page = await browser.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: script });

    await page.getByText("Add a reference and prediction activity", { exact: true }).click();
    await page.getByText("Suggestions for this publication").waitFor();
    assert.equal(await page.getByText("Newly added reference").count(), 0, "nothing imported yet");
    const before = await page.evaluate(() => (window as any).__fixture.snapshots);

    await page.getByRole("button", { name: "Import a file" }).click();
    await page.getByLabel("Reference file").setInputFiles({ name: "references.csv", mimeType: "text/csv", buffer: Buffer.from("title\nImported paper\n") });
    await page.getByText("Preview ·").waitFor();
    await page.getByRole("button", { name: "Relevant: include" }).click();
    await page.getByRole("button", { name: "Add references", exact: true }).click();
    await page.getByText("Added 1 reference.").waitFor();

    // No click on Refresh: the panel reloads on its own.
    await page.getByText("Newly added reference").waitFor();
    assert.ok(await page.evaluate(() => (window as any).__fixture.snapshots) > before, "the panel asked for fresh suggestions");
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});

test("Leaving an import before saving does not reload suggestions", async () => {
  const script = await bundle();
  const browser = await launch();
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: script });
    await page.getByText("Add a reference and prediction activity", { exact: true }).click();
    await page.getByText("Suggestions for this publication").waitFor();
    const before = await page.evaluate(() => (window as any).__fixture.snapshots);
    await page.getByRole("button", { name: "Import a file" }).click();
    await page.getByLabel("Reference file").setInputFiles({ name: "references.csv", mimeType: "text/csv", buffer: Buffer.from("title\nImported paper\n") });
    await page.getByText("Preview ·").waitFor();
    await page.getByRole("button", { name: "Cancel import" }).click();
    await page.getByText("Import cancelled. No references were saved.").waitFor();
    assert.equal(await page.evaluate(() => (window as any).__fixture.snapshots), before);
    assert.equal(await page.getByText("Newly added reference").count(), 0);
  } finally {
    await browser.close();
  }
});
