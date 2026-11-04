/**
 * Fixture-only browser acceptance for the Reference card's medium label at 375 and 1440 pixels, light and dark. No network beyond the fixture origin.
 * `MEDIUM_SHOTS_DIR` names a folder to write screenshots to.
 */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://medium.test";
const shots = process.env.MEDIUM_SHOTS_DIR;
let bundle: Promise<string> | undefined;
let tailwindCss: Promise<string> | undefined;

function compiledTailwind(): Promise<string> {
  tailwindCss ??= (async () => {
    const file = `${root}app/tailwind.css`;
    const { default: postcss } = await import("postcss");
    const { default: tailwind } = await import("@tailwindcss/postcss");
    return (await postcss([tailwind() as never]).process(fs.readFileSync(file, "utf8"), { from: file })).css;
  })();
  return tailwindCss;
}

function browserBundle(): Promise<string> {
  bundle ??= build({
    absWorkingDir: root, bundle: true, write: false, platform: "browser", jsx: "automatic",
    define: { "process.env.NODE_ENV": '"development"' }, logLevel: "silent",
    plugins: [{ name: "fixture-stubs", setup(b) {
      b.onResolve({ filter: /^papyrus-amplify-outputs$/ }, () => ({ path: "papyrus-amplify-outputs", namespace: "fixture-stub" }));
      b.onLoad({ filter: /.*/, namespace: "fixture-stub" }, () => ({ contents: "export default {};", loader: "js" }));
    } }],
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "medium-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { ReferenceCardHeader } from "./components/reference-feed";

const base = { corpusId: "fixture", versionState: "current", versionNumber: 1, createdAt: "2026-11-03T08:15:00Z", sourcePublishedAt: "2026-11-02T09:00:00Z", curationStatus: "accepted" };
const REFERENCES = [
  { ...base, id: "video-1", lineageId: "video-1", title: "A talk on harbour dredging", sourceUri: "https://www.youtube.com/watch?v=dQw4w9WgXcQ", medium: "video" },
  { ...base, id: "article-1", lineageId: "article-1", title: "Council minutes on harbour dredging", sourceUri: "https://records.example.org/council/harbour-dredging" },
];
createRoot(document.getElementById("root")).render(
  <div className="mx-auto flex max-w-xl flex-col gap-4">
    {REFERENCES.map((reference) => (
      <div key={reference.id} className="flex flex-col rounded-[var(--feed-radius-md,16px)] bg-[var(--feed-card)]" data-fixture-feed-card={reference.id}>
        <ReferenceCardHeader now={Date.parse("2026-11-04T00:00:00Z")} preview={undefined} reference={reference as never} />
      </div>
    ))}
  </div>,
);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const darkCss = "html.dark body{background:#16150f;color:#ece8dc;--feed-card:#201e17;--feed-control:#2d2a20;--feed-footer:#26231b;--foreground-muted:#a39e8e;--primary:#c6f432;--primary-foreground:#1c1c1c;--muted-foreground:#a39e8e;--foreground:#ece8dc}";
const fixtureCss = "body{margin:0;font:16px sans-serif;background:#f4f1ea;color:#1c1c1c;--muted-foreground:#6b6b6b;--foreground:#1c1c1c;--feed-card:#fbf9f4;--feed-control:#e8e3d8;--feed-footer:#f0ece2;--feed-radius-xl:12px;--feed-radius-lg:10px;--feed-radius-md:8px;--feed-radius-pill:8px;--feed-quiet:.6;--foreground-muted:#6b6b6b;--primary:#46560f;--primary-foreground:#fff}";

async function check(width: number, dark: boolean) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 700 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html class="${dark ? "dark" : ""}"><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>${fixtureCss}${darkCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  try {
    await page.goto(`${origin}/`);
    const video = page.locator('[data-fixture-feed-card="video-1"]');
    const article = page.locator('[data-fixture-feed-card="article-1"]');
    await video.waitFor();
    const label = video.locator('[data-feed-medium="video"]');
    assert.equal(await label.count(), 1, "the video card carries the medium label");
    assert.equal((await label.innerText()).trim(), "Video", "in words");
    assert.equal(await label.locator("svg").count(), 1, "and with a Lucide icon, never colour alone");
    assert.equal(await label.locator("svg").evaluate((icon) => icon.getAttribute("class")?.includes("lucide-video") ?? false), true, "the Lucide video icon");
    assert.equal(await article.locator("[data-feed-medium]").count(), 0, "an ordinary page carries no medium label");
    const offenders = await label.evaluateAll((elements) => elements.flatMap((element) => {
      const style = getComputedStyle(element);
      const edges = ["top", "right", "bottom", "left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge}-width`)) > 0 && style.getPropertyValue(`border-${edge}-style`) !== "none");
      return edges || (parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== "none") ? ["label"] : [];
    }));
    assert.deepEqual(offenders, [], "no borders or outlines");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
    if (shots) {
      fs.mkdirSync(shots, { recursive: true });
      await page.screenshot({ path: `${shots}/card-${width === 375 ? "phone" : "desktop"}-${dark ? "dark" : "light"}.png`, fullPage: true });
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
}

async function main() {
  for (const dark of [false, true]) for (const width of [375, 1440]) await check(width, dark);
  console.log("Reference medium card passed");
}

main().catch((error) => { console.error(error); process.exit(1); });
