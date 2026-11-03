/** Fixture-only browser acceptance for the side-by-side variations of a Story (PPY-9e7a4a). The panel runs against an in-memory source; no production calls. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://story-variations.test";
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
    banner: { js: 'window.process = { env: { NODE_ENV: "development" } };' },
    plugins: [{ name: "fixture-boundaries", setup(builder) {
      builder.onResolve({ filter: /story-variations-client$/ }, () => ({ path: "source", namespace: "fixture" }));
      builder.onResolve({ filter: /^next\/link$/ }, () => ({ path: "link", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ resolveDir: root, loader: "tsx", contents: path === "link"
        ? "export default function Link({ href, children, ...rest }) { return <a href={href} {...rest}>{children}</a>; }"
        : "export const resolveVariationSource = () => window.fixtureSource;" }));
    } }],
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "story-variations-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { StoryVariationsPanel } from "./components/story-variations";
const connection = (kind, id, title, how) => ({ kind, id, title, how });
const row = (number, extra = {}) => ({
  id: "v" + number, storyLineageId: "item-1", variationNumber: number, status: "offered", point: "Point " + number + ": a claim the source does not make.", headline: "Headline " + number, deck: "Deck " + number + ".",
  bodyMarkus: number === 1 ? "The body of variation one." : null, section: null, origin: "generated", pointCheck: { verdict: "adds", claim: "Claim " + number, reason: null }, decidedByLabel: null, decidedAt: null, decisionReason: null,
  connections: [[connection("reference", "ref-" + number, "Reference " + number, "Linked by an editor")], [connection("story", "item-9", "Another Story", "Rests on a related Reference")], [connection("concept", "c-1", "#source-audits", "Tagged by an editor"), connection("reference", "ref-3", "Third", null)]][number - 1] ?? [connection("reference", "ref-1", "Only", null)],
  ...extra,
});
const options = new URLSearchParams(window.location.search);
const count = Number(options.get("count") ?? 3);
let rows = Array.from({ length: count }, (_, index) => row(index + 1));
window.fixtureDecisions = [];
window.fixtureSaved = [];
window.fixtureSource = {
  load: async () => rows.map((entry) => ({ ...entry })),
  decide: async (variation, decision, by, reason, siblings) => {
    window.fixtureDecisions.push({ id: variation.id, decision, by: by.label, reason, siblings: siblings.length });
    rows = rows.map((entry) => entry.id === variation.id ? { ...entry, status: decision, decidedByLabel: by.label, decisionReason: reason || null } : decision === "accepted" && entry.status === "accepted" ? { ...entry, status: "offered" } : entry);
  },
};
const applyWording = async (variation, reason) => {
  if (options.get("failSave")) throw new Error("The new version could not be saved.");
  window.fixtureSaved.push({ id: variation.id, number: variation.variationNumber, reason });
};
createRoot(document.getElementById("root")).render(count === 0 ? <div data-empty-marker>{""}<StoryVariationsPanel applyWording={applyWording} decidedBy="Ryan" lineageId="item-1" /></div> : <div className="@container" data-kanbus-theme="" style={{ padding: 16 }}><div data-feed-surface=""><StoryVariationsPanel applyWording={applyWording} decidedBy="Ryan" lineageId="item-1" /></div></div>);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const fixtureCss = `body{margin:0;font:16px sans-serif;--feed-control:#e4e2da;--feed-footer:#f1efe8;--primary:#1f4d3a;--primary-foreground:#fff;--foreground:#161616}button,textarea,select{font:inherit}`;

async function setup(options = "", width = 1280) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>` });
  });
  await page.goto(`${origin}/newsroom/work${options}`);
  return { browser, page, errors };
}

const card = (page: Page, id: string) => page.locator(`[data-story-variation="${id}"]`);
type Fixture = { fixtureDecisions: unknown[]; fixtureSaved: unknown[] };
const decisions = (page: Page) => page.evaluate(() => (window as unknown as Fixture).fixtureDecisions);
const saved = (page: Page) => page.evaluate(() => (window as unknown as Fixture).fixtureSaved);
const box = async (page: Page, id: string) => (await card(page, id).boundingBox())!;

const scenarios: Record<string, () => Promise<void>> = {
  /** Three variations sit side by side on a wide screen, each with its point first, then headline, deck and connections that link to the Reference, Story and concept. */
  async side_by_side() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "v3").waitFor();
      const [first, second, third] = [await box(page, "v1"), await box(page, "v2"), await box(page, "v3")];
      assert.ok(first.y === second.y && second.y === third.y, "the cards share a row");
      assert.ok(first.x < second.x && second.x < third.x, "in the order they were offered");
      assert.match(await page.locator("[data-variations-count]").innerText(), /3 ways to connect this/);
      const parts = await card(page, "v1").evaluate((element) => [...element.querySelectorAll("[data-variation-point],[data-variation-headline],[data-variation-deck],[data-variation-connections]")].map((part) => part.getAttribute("data-variation-point") !== null ? "point" : part.getAttribute("data-variation-headline") !== null ? "headline" : part.getAttribute("data-variation-deck") !== null ? "deck" : "connections"));
      assert.deepEqual(parts, ["point", "headline", "deck", "connections"], "the point leads");
      assert.equal(await card(page, "v1").locator("[data-variation-point]").innerText(), "Point 1: a claim the source does not make.");
      const links = await page.locator("[data-variation-connection]").evaluateAll((anchors) => anchors.map((anchor) => [anchor.getAttribute("data-variation-connection"), anchor.getAttribute("href")]));
      assert.deepEqual(links, [["reference", "/newsroom/references/ref-1"], ["story", "/newsroom/articles/item-9"], ["concept", "/newsroom/concepts?node=c-1"], ["reference", "/newsroom/references/ref-3"]], "a Reference, a Story and a concept, each a link");
      assert.equal(await card(page, "v1").locator("[data-variation-body]").count(), 0, "the body waits behind a button");
      await card(page, "v1").locator("[data-variation-body-toggle]").click();
      assert.equal(await card(page, "v1").locator("[data-variation-body]").innerText(), "The body of variation one.");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Accept with a reason: the wording is saved as the Story's next version first, then the variation is recorded as accepted with who and why. */
  async accept_makes_the_next_version() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "v2").waitFor();
      await card(page, "v2").locator("[data-variation-reason]").fill("This is the real disagreement");
      await card(page, "v2").locator("[data-variation-accept]").click();
      await page.waitForFunction(() => (window as unknown as Fixture).fixtureDecisions.length === 1);
      assert.deepEqual(await saved(page), [{ id: "v2", number: 2, reason: "This is the real disagreement" }]);
      assert.deepEqual(await decisions(page), [{ id: "v2", decision: "accepted", by: "Ryan", reason: "This is the real disagreement", siblings: 3 }]);
      await page.waitForSelector('[data-story-variation="v2"][data-variation-status="accepted"]');
      assert.match(await card(page, "v2").locator("[data-variation-decided]").innerText(), /Accepted by Ryan\. Its wording is the Story's current version/);
      assert.equal(await card(page, "v1").getAttribute("data-variation-status"), "offered");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A Story has one accepted wording: accepting a second variation makes another version and puts the first back on offer. */
  async a_second_accept_puts_the_first_back_on_offer() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "v1").waitFor();
      await card(page, "v1").locator("[data-variation-accept]").click();
      await page.waitForSelector('[data-story-variation="v1"][data-variation-status="accepted"]');
      await card(page, "v3").locator("[data-variation-accept]").click();
      await page.waitForSelector('[data-story-variation="v3"][data-variation-status="accepted"]');
      assert.equal(await card(page, "v1").getAttribute("data-variation-status"), "offered", "the first is on offer again");
      assert.equal(await card(page, "v1").locator("[data-variation-accept]").isEnabled(), true, "and can be accepted again");
      assert.deepEqual((await saved(page) as { id: string }[]).map((entry) => entry.id), ["v1", "v3"], "two versions, one per accept; the first stays in version history");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Reject records the reason and changes nothing on the Story. */
  async reject_with_a_reason() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "v3").waitFor();
      await card(page, "v3").locator("[data-variation-reason]").fill("Only restates the source");
      await card(page, "v3").locator("[data-variation-reject]").click();
      await page.waitForSelector('[data-story-variation="v3"][data-variation-status="rejected"]');
      assert.deepEqual(await saved(page), [], "no version was made");
      assert.deepEqual(await decisions(page), [{ id: "v3", decision: "rejected", by: "Ryan", reason: "Only restates the source", siblings: 3 }]);
      assert.equal(await card(page, "v3").locator("[data-variation-reason]").inputValue(), "Only restates the source", "the reason stays readable");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** A wording that could not be saved is not recorded as accepted. */
  async a_failed_save_is_not_an_accept() {
    const { browser, page, errors } = await setup("?failSave=1");
    try {
      await card(page, "v1").waitFor();
      await card(page, "v1").locator("[data-variation-accept]").click();
      await card(page, "v1").locator('[role="alert"]').waitFor();
      assert.match(await card(page, "v1").locator('[role="alert"]').innerText(), /could not be saved/);
      assert.deepEqual(await decisions(page), []);
      assert.equal(await card(page, "v1").getAttribute("data-variation-status"), "offered");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** With one way to connect, there is one card and it says so; with none, nothing is shown. */
  async one_or_none() {
    const one = await setup("?count=1");
    try {
      await card(one.page, "v1").waitFor();
      assert.match(await one.page.locator("[data-variations-help]").innerText(), /Only one way to connect this was found/);
      assert.match(await one.page.locator("[data-variations-count]").innerText(), /1 way to connect this/);
    } finally { await one.browser.close(); }
    const none = await setup("?count=0");
    try {
      await none.page.waitForSelector("[data-empty-marker]", { state: "attached" });
      await none.page.waitForTimeout(300);
      assert.equal(await none.page.locator("[data-story-variations]").count(), 0);
    } finally { await none.browser.close(); }
  },

  /** On a phone the cards stack in one column, nothing scrolls sideways and the buttons are big enough to tap. */
  async phone() {
    const { browser, page, errors } = await setup("", 390);
    try {
      await card(page, "v3").waitFor();
      const [first, second, third] = [await box(page, "v1"), await box(page, "v2"), await box(page, "v3")];
      assert.ok(first.x === second.x && second.x === third.x && first.y < second.y && second.y < third.y, "one column, in order");
      assert.ok(first.width <= 390, "within the screen");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true, "nothing scrolls sideways");
      for (const selector of ["[data-variation-accept]", "[data-variation-reject]"]) assert.ok((await card(page, "v1").locator(selector).boundingBox())!.height >= 44, `${selector} is tall enough to tap`);
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },

  /** Accept and Reject are words with Lucide icons, the state is a word with an icon, there are no dropdowns, and nothing is outlined. */
  async words_icons_and_flat_backgrounds() {
    const { browser, page, errors } = await setup();
    try {
      await card(page, "v1").waitFor();
      await card(page, "v1").locator("[data-variation-reject]").click();
      await page.waitForSelector('[data-story-variation="v1"][data-variation-status="rejected"]');
      const labels = await page.locator("[data-variation-accept],[data-variation-reject]").evaluateAll((buttons) => buttons.map((button) => [button.textContent?.trim(), button.querySelector("svg.lucide") !== null]));
      assert.deepEqual(labels, Array.from({ length: 3 }).flatMap(() => [["Accept", true], ["Reject", true]]));
      assert.match(await card(page, "v1").locator("[data-variation-status-chip]").innerText(), /Rejected/);
      assert.equal(await card(page, "v1").locator("[data-variation-status-chip] svg.lucide").count(), 1, "the state has an icon as well as a word");
      assert.equal(await page.locator("select, [role=combobox], [role=listbox]").count(), 0, "no dropdowns");
      assert.equal(await page.locator("[data-variation-reason]").first().evaluate((element) => element.tagName), "TEXTAREA");
      const outlined = await page.locator("[data-story-variations] *").evaluateAll((elements) => elements.filter((element) => { const style = getComputedStyle(element); return ["Top", "Right", "Bottom", "Left"].some((side) => parseFloat(style.getPropertyValue(`border-${side.toLowerCase()}-width`)) > 0 && style.getPropertyValue(`border-${side.toLowerCase()}-style`) !== "none") || (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0); }).length);
      assert.equal(outlined, 0, "no borders or outlines");
      const radius = await card(page, "v1").evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
      assert.ok(radius >= 8, "rounded rectangles");
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  },
};

async function main() {
  const name = process.argv[2];
  if (!name || !(name in scenarios)) {
    for (const [scenario, run] of Object.entries(scenarios)) { await run(); console.log(`ok ${scenario}`); }
  } else {
    await scenarios[name]!();
    console.log(`ok ${name}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
