/** Fixture-only browser acceptance for the public handle field in the settings panel at 390 and 1440 pixels. No network beyond the fixture origin. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://public-handle.test";
const shots = process.env.PUBLIC_HANDLE_SHOTS_DIR;

async function bundle(): Promise<string> {
  const result = await build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, logLevel: "silent",
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "public-handle-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { useState } from "react";
import { PublicHandleField } from "./components/public-handle-field";

const taken = ["bob"];
function Fixture() {
  const [calls, setCalls] = useState([]);
  window.__calls = calls;
  const save = async (handle) => {
    calls.push(handle);
    if (handle && taken.includes(handle)) throw new Error("That handle is taken");
    return handle;
  };
  return <main className="settings-page"><section className="settings-panel"><h1>Settings</h1><PublicHandleField storedHandle={null} save={save} /></section></main>;
}
createRoot(document.getElementById("root")).render(<Fixture />);
` },
  });
  return result.outputFiles[0].text;
}

async function shot(page: Page, name: string, width: number) {
  if (shots) await page.screenshot({ path: `${shots}/${name}-${width}.png`, fullPage: true });
}

async function withPage(width: number, body: (page: Page) => Promise<void>) {
  const script = await bundle();
  const css = fs.readFileSync(`${root}app/globals.css`, "utf8");
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 800 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${css}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  try {
    await page.goto(`${origin}/`);
    await body(page);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
}

async function main() {
for (const width of [390, 1440]) {
  await withPage(width, async (page) => {
    const section = page.locator("[data-public-handle]");
    await section.waitFor();
    assert.match(await section.innerText(), /Shown next to your messages on the public site\. Leave empty to be shown as Editor\. Never your email\./);
    assert.match(await section.innerText(), /Shown as Editor/);
    assert.equal(await section.locator("svg.lucide-at-sign").count(), 1, "a Lucide at-sign marks the field");
    const flat = await section.evaluate((node) => [...node.querySelectorAll(".public-handle__field, .public-handle__save, .public-handle__input")].map((element) => getComputedStyle(element).borderTopWidth));
    assert.deepEqual(flat, ["0px", "0px", "0px"], "no borders");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true, "no horizontal scroll");
    await shot(page, "profile-handle-empty", width);

    const input = section.locator("input");
    const status = section.locator("[data-public-handle-state]");
    await input.fill("ab");
    await section.getByRole("button", { name: "Save" }).click();
    await page.waitForFunction(() => document.querySelector("[data-public-handle-state]")?.textContent?.includes("3 to 24 letters, digits and hyphens"));
    assert.equal(await status.getAttribute("data-public-handle-state"), "error");
    assert.equal(await page.evaluate(() => (window as any).__calls.length), 0, "a handle that breaks the rules is not sent");
    await shot(page, "profile-handle-rule-error", width);

    await input.fill("you@example.test");
    await section.getByRole("button", { name: "Save" }).click();
    await page.waitForFunction(() => document.querySelector("[data-public-handle-state]")?.textContent?.includes("3 to 24"));

    await input.fill("Bob");
    await section.getByRole("button", { name: "Save" }).click();
    await page.waitForFunction(() => document.querySelector("[data-public-handle-state]")?.textContent?.includes("That handle is taken"));
    await shot(page, "profile-handle-taken", width);

    await input.fill("Ryan-P");
    await section.getByRole("button", { name: "Save" }).click();
    await page.waitForFunction(() => document.querySelector("[data-public-handle-state='saved']"));
    assert.equal(await input.inputValue(), "ryan-p");
    assert.match(await section.innerText(), /Shown as ryan-p/);
    assert.equal(await page.evaluate(() => (window as any).__calls.at(-1)), "ryan-p");
    await shot(page, "profile-handle-saved", width);

    await input.fill("");
    await section.getByRole("button", { name: "Save" }).click();
    await page.waitForFunction(() => document.querySelector("[data-public-handle-state='saved']")?.textContent?.includes("Cleared"));
    assert.equal(await page.evaluate(() => (window as any).__calls.at(-1)), null, "an empty field clears the handle");
    assert.match(await section.innerText(), /Shown as Editor/);
    await shot(page, "profile-handle-cleared", width);
  });
}
console.log("public handle browser checks passed at 390 and 1440");
}
void main().catch((error) => {
  console.error(error);
  process.exit(1);
});
