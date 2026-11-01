/** Fixture-only browser acceptance for the shared Accept / Reject control on a Reference and on a generated idea. No network, no production reads. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { isGeneratedIdeaFrontMatter, readIdeaDecision, writeIdeaDecision } from "../lib/idea-decision";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://idea-decision.test";
const screenshotDirectory = process.env.DECISION_SCREENSHOT_DIRECTORY;

const FRONT_MATTER = "title: Voice cloning rises\ngenerated:\n  origin: idea_pipeline # kept as written\n  run: run-1\n";
const stamp = { decision: "reject" as const, reasonCode: null, note: "Too close to last week's story", decidedBy: "editor", decidedAt: "2026-11-01T12:00:00Z" };

function roundTripOfFrontMatter() {
  assert.equal(isGeneratedIdeaFrontMatter(FRONT_MATTER), true);
  assert.equal(isGeneratedIdeaFrontMatter("title: A person's story\n"), false);
  assert.equal(readIdeaDecision(FRONT_MATTER), null);
  const written = writeIdeaDecision(FRONT_MATTER, stamp);
  assert.match(written, /# kept as written/);
  assert.deepEqual(readIdeaDecision(written), stamp);
  assert.equal(writeIdeaDecision("title: A person's story\n", stamp), "title: A person's story\n");
  console.log("PASS: front matter keeps the decision at generated.decision");
}

async function bundle(): Promise<string> {
  const result = await build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, logLevel: "silent",
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "idea-decision-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { IdeaDecision } from "./components/idea-decision";
import { ReviewCard } from "./components/reference-review-card";
window.decisions = [];
window.failNext = false;
const frontMatter = ${JSON.stringify(FRONT_MATTER)};
function App() {
  return <div className="grid gap-8 max-w-xl">
    <div data-fixture="reference"><ReviewCard decided={null} itemId="reference-1" onDecide={async () => undefined} prediction={{ state: "none" }} summary="A short summary of the Reference." title="A Reference about voice cloning" /></div>
    <div data-fixture="idea">
      <h2 className="text-lg font-semibold mb-2">Voice cloning rises</h2>
      <IdeaDecision decidedBy="editor" frontMatterYaml={frontMatter} onDecide={async (record) => { if (window.failNext) { window.failNext = false; throw new Error("Save failed."); } window.decisions.push(record); }} now={() => "2026-11-01T12:00:00Z"} />
    </div>
  </div>;
}
createRoot(document.getElementById("root")).render(<App />);
` },
  });
  return result.outputFiles[0].text;
}

async function tailwind(): Promise<string> {
  const file = `${root}app/tailwind.css`;
  const { default: postcss } = await import("postcss");
  const { default: tailwindPlugin } = await import("@tailwindcss/postcss");
  return (await postcss([tailwindPlugin() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
}

const FIXTURE_CSS = "body{margin:0;font:16px sans-serif;--feed-control:#e8e8e2;--feed-card:#fff;--feed-radius-md:16px;--feed-quiet:.6}button,textarea{font:inherit}";

async function browserScenarios() {
  const script = await bundle();
  const css = await tailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${css}</style><style>${FIXTURE_CSS}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/`);
  const idea = page.locator('[data-fixture="idea"]');
  const reference = page.locator('[data-fixture="reference"]');

  for (const scope of [idea, reference]) {
    const accept = scope.locator('[data-review-choice="accept"]');
    const reject = scope.locator('[data-review-choice="reject"]');
    assert.match((await accept.innerText()).trim(), /Accept/);
    assert.match((await reject.innerText()).trim(), /Reject/);
    assert.equal(await accept.locator("svg").count() > 0 && await reject.locator("svg").count() > 0, true);
    assert.match(await scope.locator("[data-review-reason] label").innerText(), scope === idea ? /optional/i : /reason/i);
    assert.equal(await scope.locator("[data-review-reason] textarea").count(), 1);
    assert.equal(await scope.locator("select, [role=listbox], [role=menu]").count(), 0);
  }
  console.log("PASS: Accept and Reject carry a mark and a word, with an optional reason box, on a Reference and on an idea");

  if (screenshotDirectory) {
    fs.mkdirSync(screenshotDirectory, { recursive: true });
    await reference.screenshot({ path: `${screenshotDirectory}/decision-control-reference.png` });
    await idea.screenshot({ path: `${screenshotDirectory}/decision-control-idea-before.png` });
  }

  await idea.locator("[data-review-reason] textarea").fill("Too close to last week's story");
  await idea.locator('[data-review-choice="reject"]').click();
  await idea.locator("[data-review-saved]").waitFor();
  const decisions = await page.evaluate(() => (window as unknown as { decisions: unknown[] }).decisions);
  assert.deepEqual(decisions, [{ decision: "reject", reasonCode: null, note: "Too close to last week's story", decidedBy: "editor", decidedAt: "2026-11-01T12:00:00Z" }]);
  assert.match(await idea.locator("[data-review-saved]").innerText(), /Recorded/);
  assert.match(await idea.locator("[data-review-saved]").innerText(), /reason saved/);
  console.log("PASS: rejecting an idea records the decision with the typed reason");

  if (screenshotDirectory) await idea.screenshot({ path: `${screenshotDirectory}/decision-control-idea-rejected.png` });

  await idea.locator('[data-review-choice="accept"]').click();
  await page.waitForFunction(() => (window as unknown as { decisions: unknown[] }).decisions.length === 2);
  const second = (await page.evaluate(() => (window as unknown as { decisions: Array<{ decision: string }> }).decisions))[1];
  assert.equal(second.decision, "accept");
  console.log("PASS: accepting an idea afterwards records the new decision");

  await page.evaluate(() => { (window as unknown as { failNext: boolean }).failNext = true; });
  await idea.locator('[data-review-choice="reject"]').click();
  await idea.locator('[role="alert"]').waitFor();
  assert.match(await idea.locator('[role="alert"]').innerText(), /Save failed/);
  console.log("PASS: a failed save says so in words");

  assert.deepEqual(errors, []);
  await browser.close();
}

roundTripOfFrontMatter();
browserScenarios().catch((error) => { console.error(error); process.exit(1); });
