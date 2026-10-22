import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import { chromium } from "playwright";

const root = new URL("..", import.meta.url).pathname;
const launch = () => chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
const LABELS = ["include", "exclude"] as const;

test("The Paste a URL form rates with buttons and asks for a reason in a text area below", async () => {
  (globalThis as { React?: typeof React }).React = React;
  const { ReferenceCyclotronPriming } = await import("../components/reference-cyclotron-priming");
  const html = renderToStaticMarkup(createElement(ReferenceCyclotronPriming, {
    labels: LABELS, requests: [], onRequestPriming: () => undefined,
  }));
  assert.ok(!/<select/i.test(html), "no drop-down anywhere in the form");
  assert.ok(html.includes('role="radiogroup"'));
  assert.equal((html.match(/role="radio"/g) ?? []).length, 2, "one button per label");
  assert.ok(html.includes('aria-checked="true"') && html.includes('aria-checked="false"'));
  const group = html.indexOf('role="radiogroup"');
  const area = html.indexOf("<textarea");
  assert.ok(group >= 0 && area > group, "the explanation sits below the rating");
  assert.ok(html.includes('rows="4"'), "multi-line");
  assert.ok(!/<input[^>]*aria-label="Reason"/.test(html), "the reason is no longer a one-line input");
  assert.ok(html.includes("Why? A sentence or two helps Papyrus learn what you want."));
  assert.ok(!/cyclotron-(?!review)|priming|classifier|calibration|sweep|version/i.test(html.replace(/data-reference-cyclotron-priming|cyclotron-review-secondary/g, "")), "plain copy");
});

test("Choosing a rating, arrow keys and submit behave as before", async () => {
  const bundled = await build({
    stdin: {
      contents: `import { createRoot } from "react-dom/client";
import { ReferenceCyclotronPriming } from "./components/reference-cyclotron-priming";
(window as any).sent = [];
createRoot(document.getElementById("root")!).render(
  <ReferenceCyclotronPriming labels={["include","exclude"]} requests={[]} onRequestPriming={(input) => { (window as any).sent.push(input); }} />);`,
      resolveDir: root, loader: "tsx", sourcefile: "entry.tsx",
    },
    bundle: true, write: false, platform: "browser", jsx: "automatic", define: { "process.env.NODE_ENV": '"development"' },
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' }, logLevel: "silent", absWorkingDir: root,
  });
  const browser = await launch();
  try {
    const page = await browser.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: bundled.outputFiles[0].text });

    const include = page.getByRole("radio", { name: "include" });
    const exclude = page.getByRole("radio", { name: "exclude" });
    assert.equal(await page.locator("select").count(), 0);
    assert.equal(await include.getAttribute("aria-checked"), "true");
    assert.equal(await exclude.getAttribute("aria-checked"), "false");

    await exclude.click();
    assert.equal(await exclude.getAttribute("aria-checked"), "true");
    assert.equal(await include.getAttribute("aria-checked"), "false");
    await page.keyboard.press("ArrowLeft");
    assert.equal(await include.getAttribute("aria-checked"), "true", "arrow keys move the choice");
    assert.ok(await include.evaluate((node) => node === document.activeElement), "and the focus");
    await page.keyboard.press("ArrowRight");
    assert.equal(await exclude.getAttribute("aria-checked"), "true");

    const reason = page.getByLabel("Reason");
    const [ratingBox, reasonBox] = [await exclude.boundingBox(), await reason.boundingBox()];
    assert.ok(reasonBox!.y >= ratingBox!.y + ratingBox!.height, "the text area is below the buttons");
    assert.ok(reasonBox!.height > 50, "tall enough for a sentence or two");
    assert.equal(await reason.evaluate((node) => node.tagName), "TEXTAREA");

    await page.getByLabel("Reference URL").fill("https://example.org/a");
    await reason.fill("Marketing, not reporting.");
    await page.getByRole("button", { name: "Add reference" }).click();
    await page.getByText("Added. The page will be read shortly.").waitFor();
    assert.deepEqual(await page.evaluate(() => (window as any).sent),
      [{ url: "https://example.org/a", label: "exclude", explanation: "Marketing, not reporting." }]);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
