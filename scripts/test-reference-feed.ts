/** Fixture-only browser acceptance for the References feed at 375 and 1440 pixels. No network beyond the fixture origin, no production reads. */
import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium, type Page } from "playwright";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const origin = "http://reference-feed.test";
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
    stdin: { resolveDir: root, loader: "tsx", sourcefile: "reference-feed-fixture.tsx", contents: `
import { createRoot } from "react-dom/client";
import { useMemo, useState } from "react";
import { ReferenceFeed } from "./components/reference-feed";
import { ReferencesPageLoading } from "./components/references-page-loading";
import { partitionReferenceFeed } from "./lib/reference-feed-ranking";

const params = new URLSearchParams(location.search);
const NOW = Date.parse("2026-10-27T12:00:00Z");
const DAY = 86400000;
const ago = (days) => new Date(NOW - days * DAY).toISOString();
const decision = (label, confidence) => ({ decisionRelationId: "r", decisionId: "d", label, confidence, version: 1, reviewRecommended: false, reviewReason: null, reviewDetail: null,
  classes: ["include", "exclude"], positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null });
const make = (id, fields = {}) => ({ id: id + "-v1", lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title: "Title of " + id, sourceUri: "https://" + id + ".example.org/story", curationStatus: "pending", createdAt: ago(0.4), sourcePublishedAt: ago(0.4), ...fields });
const learned = params.has("tau") ? Array.from({ length: 10 }, (_, index) => make("learned-" + index, { curationStatus: "accepted", createdAt: ago(6), sourcePublishedAt: ago(6), curationStatusUpdatedAt: ago(5) })) : [];
const auto = params.has("auto") ? [
  make("auto-accepted", { curationStatus: "accepted", curationStatusUpdatedBy: "auto:cyclotron", curationStatusUpdatedAt: ago(0.1), curationStatusReason: "Accepted automatically by the Cyclotron: it was 96.0% sure." }),
  make("rule-accepted", { curationStatus: "accepted", curationStatusUpdatedBy: "auto:rule", curationStatusUpdatedAt: ago(0.15), curationStatusReason: "Accepted automatically by the ttab monitor's rule." }),
  make("editor-accepted", { curationStatus: "accepted", curationStatusUpdatedBy: "editor@example.test", curationStatusUpdatedAt: ago(0.2) }),
] : [];
const FIXTURE = [
  ...auto,
  make("strong-accept"), make("mid-accept"), make("no-prediction"), make("weak-reject"), make("broken-image"), make("strong-reject"),
  ...(params.has("tau") ? [make("aged-out", { createdAt: ago(9), sourcePublishedAt: ago(9) })] : []),
  ...learned,
];
const DECISIONS = new Map([["strong-accept", decision("include", 0.96)], ["mid-accept", decision("include", 0.7)], ["weak-reject", decision("exclude", 0.62)],
  ["broken-image", decision("include", 0.8)], ["strong-reject", decision("exclude", 0.94)], ["aged-out", decision("include", 0.9)]]);
const previews = new Map(FIXTURE.map((item) => [item.lineageId, { imageUrl: item.lineageId === "broken-image" ? "https://images.example.org/missing.png" : "https://images.example.org/ok.svg", description: "A one line dek for " + item.lineageId + ".", siteName: item.lineageId.replace(/-/g, " "), title: null }]));
previews.delete("no-prediction");
previews.set("mid-accept", { ...previews.get("mid-accept"), imageUrl: "https://opengraph.githubassets.com/abc/owner/repo" });
window.calls = [];
let tick = 0;

function Harness() {
  const [references, setReferences] = useState(FIXTURE);
  const [visitRated, setVisitRated] = useState(new Set());
  const [tab, setTab] = useState("feed");
  const partition = useMemo(() => partitionReferenceFeed(references, DECISIONS, { now: NOW, visitRated, tauDaysOverride: params.has("tau") ? Number(params.get("tau")) : null }), [references, visitRated]);
  return <ReferenceFeed
    loading={params.has("loading")}
    now={NOW}
    onOpen={(id) => window.calls.push({ type: "open", id })}
    onRate={async (reference, choice, reasonCode) => {
      window.calls.push({ type: "rate", id: reference.lineageId, choice, reasonCode });
      if (params.has("fail")) throw new Error("The backend refused this.");
      setReferences((current) => current.map((item) => item.lineageId === reference.lineageId
        ? { ...item, curationStatus: choice === "accept" ? "accepted" : "rejected", curationStatusUpdatedAt: new Date(NOW + (tick += 1) * 1000).toISOString() } : item));
    }}
    onTabChange={setTab}
    onVisitRated={(id) => setVisitRated((current) => new Set(current).add(id))}
    partition={partition}
    previews={previews}
    tab={tab}
    visitRated={visitRated}
    disabledReason={params.get("disabled")}
  />;
}
createRoot(document.getElementById("root")).render(params.has("page-loading") ? <ReferencesPageLoading /> : <Harness />);
` },
  }).then((result) => result.outputFiles[0].text);
  return bundle;
}

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#6a8"/></svg>';
const fixtureCss = "body{margin:0;font:16px sans-serif}button,textarea{font:inherit}";

async function setup(options = "", width = 1440, beforeLoad?: (page: Page) => Promise<void>) {
  const script = await browserBundle();
  const tailwind = await compiledTailwind();
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(4000);
  const errors: string[] = [];
  const requests: Array<{ url: string; referrer: string | undefined }> = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === "https://opengraph.githubassets.com") {
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640"><rect width="1280" height="640" fill="#fff"/></svg>' });
    }
    if (url.origin === "https://images.example.org") {
      requests.push({ url: url.href, referrer: route.request().headers().referer });
      return url.pathname.endsWith("ok.svg") ? route.fulfill({ contentType: "image/svg+xml", body: SVG }) : route.fulfill({ status: 404, body: "" });
    }
    if (url.origin !== origin) return route.abort();
    if (url.pathname === "/api/newsroom/source-icon") {
      requests.push({ url: url.href, referrer: route.request().headers().referer });
      return url.searchParams.get("host")?.includes("broken") ? route.fulfill({ status: 404, body: "" }) : route.fulfill({ contentType: "image/svg+xml", body: SVG });
    }
    if (url.pathname === "/fixture.js") return route.fulfill({ contentType: "text/javascript", body: script });
    return route.fulfill({ contentType: "text/html", body: `<html><head><meta name="viewport" content="width=device-width"><style>${tailwind}</style><style>${fixtureCss}</style></head><body><div id="root" class="p-4"></div><script src="/fixture.js"></script></body></html>` });
  });
  if (beforeLoad) await beforeLoad(page);
  await page.goto(`${origin}/${options}`);
  return { browser, page, errors, requests };
}

async function run(options: string, widths: number[], body: (page: Page, width: number, extra: { requests: Array<{ url: string; referrer: string | undefined }> }) => Promise<void>, beforeLoad?: (page: Page) => Promise<void>) {
  for (const width of widths) {
    const { browser, page, errors, requests } = await setup(options, width, beforeLoad);
    try {
      await body(page, width, { requests });
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  }
}

const cards = (page: Page) => page.locator("[data-feed-card]");
const order = (page: Page) => cards(page).evaluateAll((elements) => elements.map((element) => element.getAttribute("data-feed-card")));
const card = (page: Page, id: string) => page.locator(`[data-feed-card="${id}"]`);

const scenarios: Record<string, () => Promise<void>> = {
  /** A responsive grid, a larger lead card, and the strongest Accepts first and the strongest Rejects last. */
  async layout() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      assert.deepEqual(await order(page), ["strong-accept", "broken-image", "mid-accept", "no-prediction", "weak-reject", "strong-reject"]);
      const columns = await page.locator("[data-feed-grid]").first().evaluate((grid) => getComputedStyle(grid).gridTemplateColumns.split(" ").length);
      const lead = (await card(page, "strong-accept").boundingBox())!;
      const second = (await card(page, "mid-accept").boundingBox())!;
      if (width === 375) {
        assert.equal(columns, 1, "one column on a phone");
        assert.ok(Math.abs(lead.width - second.width) < 2);
      } else {
        assert.ok(columns >= 3, "three or more columns on a desktop, got " + columns);
        assert.ok(lead.width > second.width * 1.5, "the lead card is larger than the others");
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "nothing scrolls sideways");
      const first = card(page, "strong-accept");
      assert.ok((await first.innerText()).includes("Title of strong-accept"), "the title");
      assert.ok((await first.innerText()).includes("A one line dek for strong-accept."), "the one-line dek");
      assert.ok((await first.locator("[data-feed-source]").innerText()).includes("strong accept"), "the source name");
      assert.ok((await first.locator("time").innerText()).length > 0, "its age");
      // The prediction: its side marked on the button, its confidence in the bar.
      const marked = first.locator("[data-review-choice][data-predicted]");
      assert.equal((await marked.innerText()).replace(/\s+/g, " ").trim().toLowerCase(), "accept predicted");
      assert.ok((await marked.locator("svg").count()) >= 1, "a Lucide icon, never colour alone");
      assert.equal(await first.locator("[data-confidence-value]").innerText(), "96%", "the confidence is in the bar");
      assert.equal((await card(page, "strong-reject").locator("[data-review-choice][data-predicted]").innerText()).replace(/\s+/g, " ").trim().toLowerCase(), "reject predicted");
      assert.equal(await card(page, "strong-reject").locator("[data-confidence-value]").innerText(), "94%");
      assert.match(await card(page, "no-prediction").locator("[data-prediction-caption]").innerText(), /^no prediction$/i);
      for (const choice of ["accept", "reject"]) {
        const box = (await first.locator(`[data-review-choice=${choice}]`).boundingBox())!;
        assert.ok(box.height >= 36 && box.width >= 60, `a tap-sized ${choice} button`);
      }
      assert.equal(await page.locator("select").count(), 0, "no drop-downs");
      assert.deepEqual(await page.locator('[role=tab]').evaluateAll((tabs) => tabs.map((tab) => tab.textContent!.replace(/\d+$/, "").trim())), ["Feed", "Rated", "Earlier"]);
    });
  },

  /** Flat surfaces: no borders, outlines, rules or boxes anywhere in the feed; rounded cards and pills; sections with real headings. */
  async design() {
    await run("", [375, 1440], async (page, width) => {
      await cards(page).first().waitFor();
      await page.locator("[data-feed-tab-button=feed]").hover();
      const offenders = await page.locator("[data-reference-feed], [data-reference-feed] *").evaluateAll((elements) => elements.flatMap((element) => {
        const style = getComputedStyle(element);
        const edges = ["Top", "Right", "Bottom", "Left"].some((edge) => parseFloat(style.getPropertyValue(`border-${edge.toLowerCase()}-width`)) > 0 && style.getPropertyValue(`border-${edge.toLowerCase()}-style`) !== "none");
        const outline = style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
        return edges || outline || element.tagName === "HR" ? [element.tagName + "." + String(element.getAttribute("class")).slice(0, 60)] : [];
      }));
      assert.deepEqual(offenders, [], "no border, outline or rule");
      const radius = (selector: string) => page.locator(selector).first().evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
      assert.ok((await radius("[data-feed-card]")) >= 8, "cards are about 8 to 10px round (the --feed-radius tokens)");
      assert.ok((await radius("[data-review-choice=accept]")) >= 6, "buttons are rounded rectangles");
      assert.ok((await radius("[data-review-choice][data-predicted]")) >= 6);
      assert.ok((await radius("[data-confidence-bar]")) >= 4);
      assert.ok((await radius("[data-feed-tab-button=feed]")) >= 6);
      // The image is full-bleed across the top of the card: as wide as the card, starting at its top edge.
      const box = (await card(page, "mid-accept").boundingBox())!;
      const image = (await card(page, "mid-accept").locator("[data-feed-image]").boundingBox())!;
      assert.ok(Math.abs(image.width - box.width) < 1 && Math.abs(image.y - box.y) < 1, "full-bleed top image");
      // Three real sections with large type, no lines.
      assert.deepEqual(await page.locator("[data-feed-group] h3").allInnerTexts(), ["Top predictions", "More for you", "Least likely"]);
      const heading = page.locator("[data-feed-group=top] h3");
      assert.ok(parseFloat(await heading.evaluate((element) => getComputedStyle(element).fontSize)) >= 28, "large section type");
      assert.equal(await page.locator("[data-feed-group=least] [data-feed-card]").count(), 2);
      // Phone: the first card is on the first screen.
      if (width === 375) assert.ok((await card(page, "strong-accept").locator("[data-feed-image]").boundingBox())!.y < 500, "the first card's picture is on the first screen");
      // A card that adds nothing to its headline drops its dek.
      assert.equal(await card(page, "strong-accept").locator("[data-feed-dek]").count(), 1);
    });
  },

  /** One control: the prediction bar, the two buttons and the reason field share one column, and the predicted side is marked on the button itself. */
  async grid() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const box = async (selector: string) => (await page.locator(selector).first().boundingBox())!;
      for (const id of ["strong-accept", "strong-reject", "no-prediction"]) {
        const base = `[data-feed-card="${id}"]`;
        const row = await box(`${base} [data-review-row=you]`);
        // One column: the bar, the pair of buttons and the reason field start and end together.
        for (const [name, part] of [["the bar", await box(`${base} [data-confidence-bar]`)], ["the reason field", await box(`${base} [data-review-reason] textarea`)]] as const) {
          assert.ok(Math.abs(part.x - row.x) < 0.5 && Math.abs(part.width - row.width) < 0.5, `${id}: ${name} is the same width as the buttons`);
        }
        const accept = await box(`${base} [data-review-choice=accept]`);
        const reject = await box(`${base} [data-review-choice=reject]`);
        assert.ok(accept.x < reject.x && accept.y === reject.y, "Accept is the left button, Reject the right, on one row");
        assert.ok(Math.abs(accept.width - reject.width) < 0.5, `${id}: the two buttons are the same width`);
      }
      // There is no second row of prediction cells: the prediction lives on the button and in the bar.
      assert.equal(await page.locator("[data-review-row=cyclotron], [data-cyclotron-choice]").count(), 0, "no prediction row");
      const predicted = card(page, "strong-accept").locator("[data-review-choice][data-predicted]");
      assert.equal(await predicted.getAttribute("data-review-choice"), "accept", "the predicted side is marked on the button");
      assert.equal(await predicted.getAttribute("data-state"), "predicted");
      assert.ok(/predicted/i.test(await predicted.innerText()), "and says so in words (the label is uppercased in CSS)");
      assert.equal(await card(page, "strong-accept").locator("[data-review-choice=reject][data-predicted]").count(), 0);
      const fill = async (id: string) => page.locator(`[data-feed-card="${id}"] [data-confidence-fill]`).evaluate((el) => {
        const bar = el.parentElement!.getBoundingClientRect(); const rect = el.getBoundingClientRect();
        return { centre: bar.x + bar.width / 2, left: rect.x, right: rect.x + rect.width, share: rect.width / bar.width };
      });
      const lean = await fill("strong-accept");
      assert.ok(lean.right <= lean.centre + 1 && lean.left < lean.centre, "an Accept-leaning bar fills from the centre toward Accept (left)");
      assert.ok(Math.abs(lean.share - 0.46) < 0.02, "its length is |P - 0.5| x 2 of half the bar: 0.96 gives 46%");
      const against = await fill("strong-reject");
      assert.ok(against.left >= against.centre - 1 && against.right > against.centre, "a Reject-leaning bar fills from the centre toward Reject (right)");
      assert.ok(Math.abs(against.share - 0.44) < 0.02, "0.06 gives 44%");
      assert.equal(await page.locator('[data-feed-card="no-prediction"] [data-confidence-fill]').count(), 0, "no prediction: an empty bar");
      assert.equal(await page.locator('[data-feed-card="no-prediction"] [data-confidence-bar]').getAttribute("data-confidence-direction"), "none");
      assert.match(await card(page, "no-prediction").locator("[data-prediction-caption]").innerText(), /^no prediction$/i, "and says so above the empty bar");
      // The confidence is printed in the bar and on no button.
      assert.equal(await card(page, "strong-accept").locator("[data-confidence-fill] [data-confidence-value]").innerText(), "96%");
      for (const choice of ["accept", "reject"]) {
        assert.ok(!/%/.test(await card(page, "strong-accept").locator(`[data-review-choice=${choice}]`).innerText()), `no percentage on the ${choice} button`);
      }
      // A fill too short to hold its number keeps the number beside it instead (0.62 the other way is a 12% fill).
      assert.equal(await card(page, "weak-reject").locator("[data-confidence-fill] [data-confidence-value]").count(), 0, "a narrow fill holds no number");
      assert.equal(await card(page, "weak-reject").locator("[data-confidence-bar] > [data-confidence-value]").innerText(), "62%", "the number sits beside the fill");
      assert.equal(await page.locator("[data-feed-card] [data-review-choice] [data-verdict]").count(), 0, "no verdict before an answer");
      // Nothing spills out of a button at any card width the feed uses, down to a narrow card.
      for (const width of [240, 280, 360]) {
        const spills = await page.locator('[data-feed-card="strong-accept"] [data-decision-control]').evaluate((control, cardWidth) => {
          (control as HTMLElement).style.width = `${cardWidth}px`;
          const found = ([...control.querySelectorAll("[data-review-choice]")] as HTMLElement[]).filter((cell) => [...cell.querySelectorAll("*")].some((child) => {
            const outer = cell.getBoundingClientRect(); const inner = child.getBoundingClientRect();
            return inner.left < outer.left - 0.5 || inner.right > outer.right + 0.5;
          })).map((cell) => cell.getAttribute("data-review-choice"));
          (control as HTMLElement).style.width = "";
          return found;
        }, width);
        assert.deepEqual(spills, [], `at a ${width}px control every icon and word fits inside its button`);
      }
    });
  },

  /** After an answer: the prediction's marker and the bar carry the verdict; the answer itself never changes colour. */
  async verdict() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const rgb = (selector: string, property: "backgroundColor" | "color") => page.locator(selector).first().evaluate((el, prop) => {
        const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
        const context = canvas.getContext("2d")!; context.fillStyle = "#000"; context.fillStyle = getComputedStyle(el)[prop as "color"]; context.fillRect(0, 0, 1, 1);
        const [r, g, b] = context.getImageData(0, 0, 1, 1).data; return { r, g, b };
      }, property);
      // A confirmation: answer with the predicted side.
      await card(page, "strong-accept").locator("[data-review-choice=accept]").click();
      await card(page, "strong-accept").locator("[data-prediction-mark][data-verdict=match]").waitFor();
      assert.ok(/confirmed/i.test(await card(page, "strong-accept").locator("[data-review-choice=accept]").innerText()), "the answer says Confirmed");
      const markMatch = await rgb('[data-feed-card="strong-accept"] [data-prediction-mark][data-verdict=match]', "color");
      assert.ok(markMatch.g > markMatch.r && markMatch.g > markMatch.b, "the prediction's marker is green: " + JSON.stringify(markMatch));
      const barMatch = await rgb('[data-feed-card="strong-accept"] [data-confidence-fill]', "backgroundColor");
      assert.ok(barMatch.g > barMatch.r, "the bar turns green too: " + JSON.stringify(barMatch));
      // An overturn: answer Accept on a card predicted Reject.
      await card(page, "strong-reject").locator("[data-review-choice=accept]").click();
      await card(page, "strong-reject").locator("[data-prediction-mark][data-verdict=miss]").waitFor();
      assert.ok(/overturned/i.test(await card(page, "strong-reject").locator("[data-review-choice=accept]").innerText()), "the answer says Overturned");
      const markMiss = await rgb('[data-feed-card="strong-reject"] [data-prediction-mark][data-verdict=miss]', "color");
      assert.ok(markMiss.r > markMiss.g && markMiss.r > markMiss.b, "the marker is red: " + JSON.stringify(markMiss));
      const barMiss = await rgb('[data-feed-card="strong-reject"] [data-confidence-fill]', "backgroundColor");
      assert.ok(barMiss.r > barMiss.g, "the bar turns red too: " + JSON.stringify(barMiss));
      // The marker stays on the side the prediction picked, which is the losing side after an overturn.
      assert.equal(await card(page, "strong-reject").locator("[data-review-choice=reject][data-predicted] [data-prediction-mark]").count(), 1, "the marker stays on the predicted side");
      // The editor's own answer is never tinted by the verdict: the same fill confirms and overturns.
      const chosen = (id: string) => rgb(`[data-feed-card="${id}"] [data-review-choice=accept]`, "backgroundColor");
      assert.deepEqual(await chosen("strong-accept"), await chosen("strong-reject"), "a confirmed answer and an overturned one are the same colour");
      // Your chosen button is filled and the other quiet; tapping the chosen one never unselects it.
      const pressed = (id: string, choice: string) => card(page, id).locator(`[data-review-choice=${choice}]`).getAttribute("aria-pressed");
      assert.equal(await pressed("strong-accept", "accept"), "true");
      assert.equal(await pressed("strong-accept", "reject"), "false");
      await card(page, "strong-accept").locator("[data-review-choice=accept]").click();
      assert.equal(await pressed("strong-accept", "accept"), "true", "tapping the chosen answer does not unselect it");
      const classes = (choice: string) => card(page, "strong-accept").locator(`[data-review-choice=${choice}]`).getAttribute("class");
      assert.ok(/bg-\[var\(--primary\)\]/.test((await classes("accept")) ?? "") && /font-semibold/.test((await classes("accept")) ?? ""), "the chosen button is filled");
      assert.ok(!/bg-\[var\(--primary\)\]/.test((await classes("reject")) ?? ""), "the other is quiet");
    });
  },

  /** The image is lazy, has a fixed frame and no referrer; a missing image becomes a tile with the source name. */
  async images() {
    await run("", [375, 1440], async (page, _width, { requests }) => {
      await cards(page).first().waitFor();
      const image = card(page, "strong-accept").locator("[data-feed-image] img");
      await image.waitFor();
      assert.equal(await image.getAttribute("loading"), "lazy");
      assert.equal(await image.getAttribute("referrerpolicy"), "no-referrer");
      await page.waitForFunction(() => document.querySelector('[data-feed-card="strong-accept"] [data-feed-image]')?.getAttribute("data-feed-image-state") === "loaded");
      const frame = (await card(page, "strong-accept").locator("[data-feed-image]").boundingBox())!;
      assert.ok([1.6, 2, 21 / 9].some((ratio) => Math.abs(frame.width / frame.height - ratio) < 0.1), "the lead frame has a fixed ratio");
      const other = (await card(page, "weak-reject").locator("[data-feed-image]").boundingBox())!;
      assert.ok(Math.abs(other.width / other.height - 16 / 10) < 0.05, "other cards are 16:10");
      // A text card (a GitHub social card) is shown whole: its own ratio, contained, never cropped at the edges. Photos stay cover.
      const textCard = card(page, "mid-accept").locator("[data-feed-image]");
      await page.waitForFunction(() => document.querySelector('[data-feed-card="mid-accept"] [data-feed-image]')?.getAttribute("data-feed-image-state") === "loaded");
      assert.equal(await textCard.getAttribute("data-feed-image-fit"), "contain");
      assert.equal(await textCard.locator("img").evaluate((element) => getComputedStyle(element).objectFit), "contain");
      const cardBox = (await textCard.boundingBox())!;
      assert.ok(Math.abs(cardBox.width / cardBox.height - 2) < 0.05, "the frame takes the card's own 2:1 ratio");
      assert.equal(await card(page, "strong-accept").locator("[data-feed-image]").getAttribute("data-feed-image-fit"), "cover");
      await page.waitForFunction(() => document.querySelector('[data-feed-card="broken-image"] [data-feed-image-fallback]'));
      const fallback = card(page, "broken-image").locator("[data-feed-image-fallback]");
      assert.ok((await fallback.innerText()).includes("broken image"), "the tile names the source");
      assert.equal(await fallback.locator("svg").count(), 0, "no outline icon");
      assert.equal(await fallback.locator("[data-feed-source-mark]").count(), 1, "the source's mark, large and centred");
      assert.ok(/gradient/.test(await fallback.evaluate((element) => getComputedStyle(element).backgroundImage)), "a soft gradient from the source name");
      const noPreview = card(page, "no-prediction").locator("[data-feed-image-fallback]");
      assert.equal(await noPreview.count(), 1, "a Reference with no preview shows the tile at once");
      assert.ok(requests.every((request) => request.referrer === undefined || request.url.includes("/api/newsroom/source-icon")), "images are requested with no referrer");
      // Source icons come from the newsroom's own icon route, never a guessed /favicon.ico on the source; no icon means the letter.
      const marks = await page.locator("[data-feed-source-mark] img").evaluateAll((images) => images.map((image) => (image as HTMLImageElement).getAttribute("src") ?? ""));
      assert.ok(marks.length > 0 && marks.every((src) => src.startsWith("/api/newsroom/source-icon?host=")), "every source icon is asked of the newsroom");
      await page.waitForFunction(() => !document.querySelector('[data-feed-card="broken-image"] [data-feed-image-fallback] [data-feed-source-mark] img'));
      assert.match(await fallback.locator("[data-feed-source-mark]").innerText(), /^\S$/, "a source with no icon shows its first letter");
    });
  },

  /** A Reference the Cyclotron accepted on its own says so in words with an icon, and an editor's accept does not. */
  async auto() {
    await run("?auto", [375, 1440], async (page) => {
      await page.locator("[data-feed-tab-button=rated]").click();
      await card(page, "auto-accepted").waitFor();
      const badge = card(page, "auto-accepted").locator("[data-auto-accepted]");
      assert.equal(await badge.count(), 1, "the automatically accepted card carries the badge");
      assert.ok((await badge.innerText()).includes("Accepted automatically"), "in words");
      assert.equal(await badge.locator("svg").count(), 1, "with a Lucide icon");
      const byRule = card(page, "rule-accepted").locator("[data-auto-accepted=rule]");
      assert.equal(await byRule.count(), 1, "a rule monitor's delivery carries the badge too");
      assert.ok((await byRule.innerText()).includes("Accepted automatically (by rule)"), "and says it was by rule");
      assert.equal(await card(page, "editor-accepted").locator("[data-auto-accepted]").count(), 0, "an editor's accept is not marked");
      assert.equal(await card(page, "auto-accepted").getAttribute("data-feed-rated"), "accept", "it still reads as accepted, and the editor can change it");
    });
  },

  /** A rated card stays in place showing the answer, undo is the other choice, then it is under Rated. */
  async lifecycle() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const before = await order(page);
      await card(page, "mid-accept").locator("[data-review-choice=accept]").click();
      await card(page, "mid-accept").locator("[data-prediction-mark][data-verdict=match]").waitFor();
      assert.deepEqual(await order(page), before, "the rated card stays in place");
      assert.equal(await card(page, "mid-accept").getAttribute("data-feed-rated"), "accept");
      assert.ok(/confirmed/i.test(await card(page, "mid-accept").locator("[data-review-choice=accept]").innerText()), "the answer says Confirmed");
      assert.equal(await card(page, "mid-accept").locator("[data-prediction-mark] svg").count(), 1, "with its marker, never colour alone");
      assert.ok((await card(page, "mid-accept").locator("[data-feed-saved]").innerText()).includes("Recorded"));
      assert.equal(await card(page, "mid-accept").locator("[data-review-choice=accept]").getAttribute("aria-pressed"), "true");
      assert.equal(await page.locator("[data-feed-tab-button=rated] [data-feed-tab-count]").innerText(), "1");

      // The other choice is the undo: Reject waits for a written reason, and nothing changes until one is given.
      await card(page, "mid-accept").locator("[data-review-choice=reject]").click();
      assert.equal(await card(page, "mid-accept").locator("[data-review-record]").count(), 1, "a reason is asked for in words");
      assert.ok((await card(page, "mid-accept").locator("[data-feed-saved]").innerText()).includes("A reason is needed"));
      assert.ok(/needs a reason/i.test(await card(page, "mid-accept").locator("[data-review-choice=reject]").innerText()), "the staged button says what is missing, not that it is unrecorded");
      assert.equal(await card(page, "mid-accept").getAttribute("data-feed-rated"), "accept", "nothing changes until a reason is written");
      await card(page, "mid-accept").locator("[data-review-reason] textarea").fill("The same study, already in the corpus.");
      await card(page, "mid-accept").locator("[data-review-record]").click();
      await card(page, "mid-accept").locator("[data-prediction-mark][data-verdict=miss]").waitFor();
      assert.ok(/overturned/i.test(await card(page, "mid-accept").locator("[data-review-choice=reject]").innerText()));
      assert.deepEqual(await order(page), before);
      const calls = await page.evaluate(() => (window as unknown as { calls: unknown[] }).calls);
      assert.deepEqual(calls, [
        { type: "rate", id: "mid-accept", choice: "accept", reasonCode: null },
        { type: "rate", id: "mid-accept", choice: "reject", reasonCode: "other" },
      ], "a written reason files the rejection under other, which the policy already accepts");

      // A Reject that was predicted is a confirmation, and it also needs its reason in words.
      await card(page, "strong-reject").locator("[data-review-choice=reject]").click();
      assert.equal(await card(page, "strong-reject").locator("[data-review-record]").count(), 1);
      await card(page, "strong-reject").locator("[data-review-reason] textarea").fill("Out of scope for this desk.");
      await card(page, "strong-reject").locator("[data-review-record]").click();
      await card(page, "strong-reject").locator("[data-prediction-mark][data-verdict=match]").waitFor();

      await page.locator("[data-feed-tab-button=rated]").click();
      assert.deepEqual(await order(page), ["strong-reject", "mid-accept"], "Rated lists the most recent answer first");
      await page.locator("[data-feed-tab-button=feed]").click();
      await card(page, "weak-reject").locator("[data-review-choice=accept]").first().waitFor();
      await card(page, "strong-accept").locator("[data-feed-open]").click();
      assert.deepEqual((await page.evaluate(() => (window as unknown as { calls: Array<{ type: string; id: string }> }).calls)).at(-1), { type: "open", id: "strong-accept" }, "the card body opens the review");
    });
  },

  /** Unrated items past the learned freshness move to an Earlier section at the bottom, still ratable. */
  async earlier() {
    await run("?tau=2", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const feedOrder = await order(page);
      assert.equal(feedOrder.at(-1), "aged-out", "after everything in the feed");
      assert.ok(feedOrder.indexOf("strong-reject") < feedOrder.indexOf("aged-out"));
      assert.equal(await page.locator("[data-feed-earlier] h3").innerText(), "Earlier");
      assert.equal(await page.locator("[data-feed-earlier] [data-feed-card]").count(), 1);
      assert.equal(await page.locator("[data-feed-tab-button=earlier] [data-feed-tab-count]").innerText(), "1");
      await card(page, "aged-out").locator("[data-review-choice=accept]").click();
      await card(page, "aged-out").locator("[data-verdict=match]").waitFor();
      assert.equal(await page.locator("[data-feed-earlier] [data-feed-card]").count(), 1, "rated in place, not removed");
      await page.locator("[data-feed-tab-button=earlier]").click();
      assert.deepEqual(await order(page), ["aged-out"]);
    });
  },

  /** The shell and card skeletons show at once, with no "checking" text. */
  async skeleton() {
    await run("?loading=1", [375, 1440], async (page) => {
      const skeleton = page.locator("[data-reference-feed-skeleton]");
      await skeleton.waitFor();
      assert.equal(await skeleton.getAttribute("role"), "status");
      assert.equal(await skeleton.getAttribute("aria-label"), "Loading references");
      assert.ok((await skeleton.locator(".animate-pulse").count()) > 10);
      assert.equal(await cards(page).count(), 0);
      assert.equal(await page.locator('[role=tab]').count(), 3, "the feed's tabs are already on the page");
      assert.ok(!/checking|credentials/i.test(await page.locator("body").innerText()));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    });
  },

  /** A return visit paints the last saved cards at once, read only, with the reason in words. */
  async cached() {
    const snapshot = JSON.stringify({
      savedAt: Date.now(),
      references: [1, 2, 3].map((index) => ({ id: `saved-${index}-v1`, lineageId: `saved-${index}`, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: `saved-${index}`, title: `Saved title ${index}`, sourceUri: `https://saved${index}.example.org/a`, curationStatus: "pending", createdAt: new Date(Date.now() - 3_600_000 * index).toISOString() })),
      previews: [["saved-1", { imageUrl: "https://images.example.org/ok.svg", description: "Saved dek.", siteName: "Saved One", title: null }]],
      decisions: [],
    });
    await run("?page-loading=1", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      assert.equal(await cards(page).count(), 3);
      const text = await page.locator("body").innerText();
      assert.ok(text.includes("Saved title 1") && text.includes("Saved dek."));
      assert.ok(!/checking credentials|checking sign-in/i.test(text), "no checking screen in front of the cards");
      assert.ok(text.includes("Showing your last view while it updates"));
      assert.ok(text.includes("Confirming your sign-in. You can answer in a moment."), "the disabled controls say why");
      await card(page, "saved-1").locator("[data-review-choice=accept]").click({ force: true });
      assert.equal(await card(page, "saved-1").getAttribute("data-feed-rated"), null, "a saved copy never answers on its own");
      await card(page, "saved-1").locator("[data-feed-open]").click();
      assert.ok((await page.locator("[role=status]").allInnerTexts()).join(" ").includes("available in a moment"), "opening says what is happening");
    }, async (page) => {
      await page.addInitScript((value) => { try { localStorage.setItem("papyrus.references.feed.v1.papyrus", value); } catch { /* none */ } }, snapshot);
    });
    // With no saved copy the page shows skeleton cards, not an empty page.
    await run("?page-loading=1", [375], async (page) => {
      await page.locator("[data-reference-feed-skeleton]").waitFor();
      assert.equal(await page.getByRole("heading", { name: "References" }).count(), 1);
    });
  },

  /** The ranking is explained in plain words, with this site's learned numbers. */
  async popover() {
    await run("", [375, 1440], async (page) => {
      await cards(page).first().waitFor();
      const button = page.getByRole("button", { name: "How this feed is ranked" });
      await button.click();
      const panel = page.locator("[data-feed-ranking-panel]");
      const text = await panel.innerText();
      for (const expected of ["A feed run by algorithms you control", "Best bets first", "Confidence counts", "toward", "Earlier", "Your answers stay put", "Age does not change the order yet", "of the 10 needed"]) {
        assert.ok(text.includes(expected), `the popover says: ${expected}`);
      }
      const box = (await panel.boundingBox())!;
      assert.ok(box.x >= 0 && box.x + box.width <= (await page.evaluate(() => window.innerWidth)), "inside the screen");
      await page.keyboard.press("Escape");
      assert.equal(await panel.count(), 0);
    });
    await run("?tau=2", [1440], async (page) => {
      await page.getByRole("button", { name: "How this feed is ranked" }).click();
      const text = await page.locator("[data-feed-ranking-panel]").innerText();
      assert.ok(text.includes("loses half its pull every") && text.includes("Unrated items older than 6 days"));
    });
  },

  /** A refused save is said in words and the card keeps its place. */
  async refusal() {
    await run("?fail=1", [375], async (page) => {
      await cards(page).first().waitFor();
      await card(page, "mid-accept").locator("[data-review-choice=accept]").click();
      assert.ok((await card(page, "mid-accept").locator("[role=alert]").innerText()).includes("The backend refused this."));
      assert.equal(await card(page, "mid-accept").getAttribute("data-feed-rated"), null);
    });
    await run("?disabled=Editor%20access%20is%20required.", [375], async (page) => {
      await cards(page).first().waitFor();
      await card(page, "mid-accept").locator("[data-review-choice=accept]").click({ force: true });
      assert.ok((await card(page, "mid-accept").locator("[data-review-disabled-reason]").innerText()).includes("Editor access is required."));
      assert.equal(await page.evaluate(() => (window as unknown as { calls: unknown[] }).calls.length), 0);
    });
  },
};

async function main() {
  const requested = process.argv[2];
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (requested && requested !== name) continue;
    await scenario();
    console.log(`Reference feed scenario passed: ${name}`);
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
