#!/usr/bin/env node
/**
 * Screenshots of the captured-record panel, the card/pane sync and Previous/Next selection, from the local preview with the real
 * Anth.us export (scripts/export-reference-feed-fixture.py --capture-text).
 *   PAPYRUS_PREVIEW_URL=http://127.0.0.1:3004 PAPYRUS_FEED_SHOTS_DIR=<dir> node scripts/capture-review-sync-shots.mjs
 */
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.PAPYRUS_PREVIEW_URL?.trim() || "http://127.0.0.1:3004";
const route = process.env.PAPYRUS_FEED_ROUTE?.trim() || "/references";
const outputDirectory = path.resolve(process.env.PAPYRUS_FEED_SHOTS_DIR?.trim() || "feed-shots-sync");
const chrome = process.env.PAPYRUS_CHROMIUM_PATH?.trim() || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
mkdirSync(outputDirectory, { recursive: true });
const viewports = [{ name: "1440", width: 1440, height: 1000, scale: 1 }, { name: "900", width: 900, height: 900, scale: 1 }, { name: "390", width: 390, height: 844, scale: 2 }];

const browser = await chromium.launch({ executablePath: chrome });
try {
  for (const scheme of ["light", "dark"]) for (const viewport of viewports) {
    const phone = viewport.width < 768;
    const newPage = async () => {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale, colorScheme: scheme });
      const page = await context.newPage();
      await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
        const style = document.createElement("style"); style.textContent = "nextjs-portal{display:none!important}"; document.head.appendChild(style);
      }));
      await page.goto(new URL(route, base).toString(), { waitUntil: "networkidle", timeout: 180_000 });
      await page.locator("[data-feed-card]").first().waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2500);
      return { context, page };
    };
    const name = (shot) => path.join(outputDirectory, `${shot}-${viewport.name}-${scheme}.png`);
    const review = (page) => page.locator("[data-review-card]").locator("visible=true").first();
    const openCard = async (page, selector) => {
      const card = page.locator(`[data-feed-card]${selector}`).first();
      await card.evaluate((element) => element.scrollIntoView({ block: "center" }));
      await card.locator("[data-feed-open]").click();
      await review(page).waitFor();
      await page.waitForTimeout(900);
      return card;
    };
    const shootPanel = async (page, shot) => {
      const panel = page.locator("[data-capture-panel]").locator("visible=true").first();
      await panel.evaluate((element) => element.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(500);
      await page.screenshot({ path: name(shot) });
      console.log(name(shot));
    };

    let { context, page } = await newPage();
    // Stability: the grid before and after selecting five items in turn (clicks that do not scroll): the cards have not moved.
    await page.screenshot({ path: name("stable-1-before-selecting") });
    console.log(name("stable-1-before-selecting"));
    const ids = await page.locator("[data-feed-card]").evaluateAll((cards) => cards.slice(0, 5).map((card) => card.getAttribute("data-feed-card")));
    for (const id of ids) {
      await page.locator(`[data-feed-card="${id}"] [data-feed-open]`).evaluate((element) => element.click());
      await page.waitForTimeout(400);
      if (phone) { await page.keyboard.press("Escape"); await page.waitForTimeout(300); }
    }
    await page.waitForTimeout(600);
    await page.screenshot({ path: name("stable-2-after-selecting-five") });
    console.log(name("stable-2-after-selecting-five"));
    await context.close();
    if (viewport.name === "900") continue;
    ({ context, page } = await newPage());
    await page.screenshot({ path: name("feed-with-capture-badges") });
    console.log(name("feed-with-capture-badges"));
    await openCard(page, ":has([data-capture-badge=full])");
    await shootPanel(page, "detail-full-text");
    if (phone) { await page.keyboard.press("Escape"); await page.waitForTimeout(400); }
    await openCard(page, ":has([data-capture-badge=thin])");
    await shootPanel(page, "detail-teaser");
    if (phone) { await page.keyboard.press("Escape"); await page.waitForTimeout(400); }
    await openCard(page, ":has([data-capture-badge=none])");
    await shootPanel(page, "detail-no-text");
    await context.close();

    // Sync: vote on the card, then a reason in the pane (both show Saved); a Reject on the card, its reason chosen in the pane.
    ({ context, page } = await newPage());
    const accept = page.locator("[data-feed-card]:not([data-feed-rated]):has([data-predicted][data-cyclotron-choice=accept])").first();
    await accept.evaluate((element) => element.scrollIntoView({ block: "center" }));
    await accept.locator("[data-review-choice=accept]").click();
    await page.waitForTimeout(600);
    await accept.locator("[data-feed-open]").click();
    await review(page).waitFor();
    await review(page).getByLabel("Why? (optional)", { exact: true }).fill("Squarely in our beat, and well sourced.");
    await page.waitForTimeout(2200);
    await review(page).getByLabel("Why? (optional)", { exact: true }).evaluate((element) => element.scrollIntoView({ block: "center" }));
    await page.screenshot({ path: name("sync-vote-then-reason") });
    console.log(name("sync-vote-then-reason"));
    if (phone) { await page.keyboard.press("Escape"); await page.waitForTimeout(500); await accept.evaluate((element) => element.scrollIntoView({ block: "center" })); await page.screenshot({ path: name("sync-card-after-pane-reason") }); console.log(name("sync-card-after-pane-reason")); }
    const reject = page.locator("[data-feed-card]:not([data-feed-rated]):has([data-predicted][data-cyclotron-choice=accept])").nth(1);
    await reject.evaluate((element) => element.scrollIntoView({ block: "center" }));
    await reject.locator("[data-review-choice=reject]").click();
    await reject.locator("[data-feed-open]").click();
    await review(page).waitFor();
    await review(page).locator('[data-review-reason="duplicate"]').click();
    await page.waitForTimeout(1200);
    if (phone) { await page.keyboard.press("Escape"); await page.waitForTimeout(500); }
    await reject.evaluate((element) => element.scrollIntoView({ block: "center" }));
    await page.screenshot({ path: name("sync-reject-reason-from-pane") });
    console.log(name("sync-reject-reason-from-pane"));
    await context.close();

    // Previous / Next: the grid follows, the card is selected (tint and a ring outside the card).
    ({ context, page } = await newPage());
    await openCard(page, "");
    const queue = page.locator("[data-review-queue-bar]").locator("visible=true").first();
    for (let step = 0; step < (phone ? 3 : 7); step += 1) { await queue.getByRole("button", { name: "Next" }).click(); await page.waitForTimeout(350); }
    await page.waitForTimeout(1200);
    if (phone) { await page.keyboard.press("Escape"); await page.waitForTimeout(700); }
    await page.screenshot({ path: name("previous-next-selected") });
    console.log(name("previous-next-selected"));
    await context.close();
  }
} finally {
  await browser.close();
}
