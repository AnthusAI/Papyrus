#!/usr/bin/env node
/**
 * Screenshots of the References feed from the local preview (see scripts/export-reference-feed-fixture.py), at 1440x1000 and 390x844.
 *   PAPYRUS_PREVIEW_URL=http://127.0.0.1:3002 PAPYRUS_FEED_SHOTS_DIR=<dir> node scripts/capture-reference-feed-shots.mjs
 * Chrome is taken from PAPYRUS_CHROMIUM_PATH, else the macOS Chrome app, else Playwright's own browser.
 */
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.PAPYRUS_PREVIEW_URL?.trim() || "http://127.0.0.1:3002";
const outputDirectory = path.resolve(process.env.PAPYRUS_FEED_SHOTS_DIR?.trim() || "feed-shots");
const chrome = process.env.PAPYRUS_CHROMIUM_PATH?.trim() || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
const viewports = [
  { name: "1440", width: 1440, height: 1000, scale: 1 },
  { name: "390", width: 390, height: 844, scale: 2 },
];
mkdirSync(outputDirectory, { recursive: true });

const browser = await chromium.launch({ executablePath: chrome });
const failures = [];
try {
  for (const viewport of viewports) {
    const open = async (query = "") => {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale, colorScheme: "light" });
      const page = await context.newPage();
      page.on("pageerror", (error) => failures.push(`${viewport.name}${query}: ${error.message}`));
      await page.goto(new URL(`/newsroom/references${query}`, base).toString(), { waitUntil: "networkidle", timeout: 180_000 });
      await page.locator("[data-reference-feed], [data-reference-feed-skeleton]").first().waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2500);
      return { context, page };
    };
    const shoot = async (page, name, options = {}) => {
      const file = path.join(outputDirectory, `feed-${name}-${viewport.name}.png`);
      await page.screenshot({ path: file, ...options });
      console.log(file);
    };
    const scrollToLast = async (page) => {
      await page.locator("[data-feed-card]").last().scrollIntoViewIfNeeded();
      await page.waitForTimeout(1200);
    };

    // Real data: the Cyclotron has only predicted Accept so far, so the Reject end needs the labelled preview-only synthetic ones.
    let session = await open();
    await shoot(session.page, "top");
    await scrollToLast(session.page);
    await shoot(session.page, "bottom-real");
    await session.context.close();

    session = await open("?feedSynthRejects=6");
    await shoot(session.page, "synthetic-rejects-top");
    await scrollToLast(session.page);
    await shoot(session.page, "bottom-strong-rejects");

    // Rate: one card the Cyclotron expected to be Accepted (a match) and one it expected to be Rejected (a miss), both answered Accept.
    const { page } = session;
    await page.locator("[data-feed-tab-button=feed]").scrollIntoViewIfNeeded();
    const predictedAccept = page.locator('[data-feed-card]:has([data-cyclotron-choice="accept"])').first();
    const predictedReject = page.locator('[data-feed-card]:has([data-cyclotron-choice="reject"])').first();
    await predictedAccept.locator('[data-review-choice="accept"]').click();
    await page.waitForTimeout(700);
    await predictedAccept.scrollIntoViewIfNeeded();
    await shoot(page, "after-rating-match", { clip: await clipOf(predictedAccept) });
    await predictedReject.scrollIntoViewIfNeeded();
    await predictedReject.locator('[data-review-choice="accept"]').click();
    await page.waitForTimeout(700);
    await predictedReject.scrollIntoViewIfNeeded();
    await shoot(page, "after-rating-miss", { clip: await clipOf(predictedReject) });
    await shoot(page, "after-rating-in-place");
    // Reject path: the card asks for a reason.
    const another = page.locator('[data-feed-card]:not([data-feed-rated]):has([data-cyclotron-choice="reject"])').first();
    await another.scrollIntoViewIfNeeded();
    await another.locator('[data-review-choice="reject"]').click();
    await page.waitForTimeout(400);
    await shoot(page, "reject-asks-reason", { clip: await clipOf(another) });
    await page.locator("[data-feed-tab-button=rated]").scrollIntoViewIfNeeded();
    await page.locator("[data-feed-tab-button=rated]").click();
    await page.waitForTimeout(1200);
    await shoot(page, "rated-tab");
    await page.locator("[data-feed-tab-button=feed]").click();
    await page.locator("[data-feed-open]").nth(2).click();
    await page.waitForTimeout(1500);
    await shoot(page, "detail-open");
    await session.context.close();

    session = await open("?feedTau=2");
    await session.page.locator("[data-feed-earlier]").evaluate((element) => element.scrollIntoView({ block: "start" }));
    await session.page.waitForTimeout(1200);
    await shoot(session.page, "earlier-section");
    await session.page.locator("[data-feed-ranking-info]").scrollIntoViewIfNeeded();
    await session.page.locator("[data-feed-ranking-info]").click();
    await session.page.waitForTimeout(500);
    await shoot(session.page, "ranking-popover");
    await session.context.close();

    session = await open("?feedState=loading");
    await shoot(session.page, "loading-skeleton");
    await session.context.close();

    session = await open();
    await session.page.locator("[data-reference-view=list]").click();
    await session.page.waitForTimeout(800);
    await shoot(session.page, "list-view");
    await session.context.close();
  }
} finally {
  await browser.close();
}
if (failures.length) {
  console.error(`page errors:\n${failures.join("\n")}`);
  process.exitCode = 1;
}

async function clipOf(locator) {
  await locator.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await locator.page().waitForTimeout(300);
  const box = await locator.boundingBox();
  return { x: Math.max(0, box.x - 8), y: Math.max(0, box.y - 8), width: box.width + 16, height: box.height + 16 };
}
