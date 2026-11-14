#!/usr/bin/env node
/**
 * Screenshots of the decision control (prediction bar, the two buttons, the reason field) on feed cards and in the review card, from the local preview.
 *   PAPYRUS_PREVIEW_URL=http://127.0.0.1:3003 PAPYRUS_FEED_SHOTS_DIR=<dir> node scripts/capture-rating-grid-shots.mjs
 * The Reject-leaning cards use the preview-only, labelled synthetic Rejects (?feedSynthRejects=6): real data has none yet.
 */
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.PAPYRUS_PREVIEW_URL?.trim() || "http://127.0.0.1:3003";
const route = process.env.PAPYRUS_FEED_ROUTE?.trim() || "/references";
const outputDirectory = path.resolve(process.env.PAPYRUS_FEED_SHOTS_DIR?.trim() || "feed-shots-rating");
const chrome = process.env.PAPYRUS_CHROMIUM_PATH?.trim() || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
mkdirSync(outputDirectory, { recursive: true });
const viewports = [{ name: "1440", width: 1440, height: 1000, scale: 1 }, { name: "390", width: 390, height: 844, scale: 2 }];

const browser = await chromium.launch({ executablePath: chrome });
try {
  for (const scheme of ["light", "dark"]) for (const viewport of viewports) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale, colorScheme: scheme });
    const page = await context.newPage();
    await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
      const style = document.createElement("style"); style.textContent = "nextjs-portal{display:none!important}"; document.head.appendChild(style);
    }));
    await page.goto(new URL(`${route}?feedSynthRejects=6`, base).toString(), { waitUntil: "networkidle", timeout: 180_000 });
    await page.locator("[data-feed-card]").first().waitFor({ timeout: 60_000 });
    await page.waitForTimeout(2500);
    const shoot = async (locator, name) => {
      await locator.evaluate((element) => element.scrollIntoView({ block: "center" }));
      await page.waitForTimeout(500);
      const file = path.join(outputDirectory, `${name}-${viewport.name}-${scheme}.png`);
      await locator.screenshot({ path: file });
      console.log(file);
    };
    const accept = page.locator('[data-feed-card]:has([data-review-choice="accept"][data-predicted])').first();
    const reject = page.locator('[data-feed-card]:has([data-review-choice="reject"][data-predicted])').first();
    await shoot(accept, "card-accept-leaning");
    await shoot(reject, "card-reject-leaning-synthetic");
    await accept.locator('[data-review-choice="accept"]').click();
    await page.waitForTimeout(700);
    await shoot(accept, "card-after-match");
    await reject.locator('[data-review-choice="accept"]').click();
    await page.waitForTimeout(700);
    await shoot(reject, "card-after-miss-synthetic");

    // The same grid in the review card: open an unrated Accept-leaning and an unrated Reject-leaning card.
    const review = () => page.locator("[data-review-card]").locator("visible=true").first();
    const open = async (selector) => { await page.locator(selector).first().locator("[data-feed-open]").click(); await review().waitFor(); await page.waitForTimeout(700); };
    await open('[data-feed-card]:not([data-feed-rated]):has([data-review-choice="accept"][data-predicted])');
    await shoot(review(), "detail-accept-leaning");
    await review().locator('[data-review-choice="accept"]').click();
    await page.waitForTimeout(900);
    await shoot(review(), "detail-after-match");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);
    await open('[data-feed-card]:not([data-feed-rated]):has([data-review-choice="reject"][data-predicted])');
    await shoot(review(), "detail-reject-leaning-synthetic");
    await review().locator('[data-review-choice="accept"]').click();
    await page.waitForTimeout(900);
    await shoot(review(), "detail-after-miss-synthetic");
    await context.close();
  }
} finally {
  await browser.close();
}
