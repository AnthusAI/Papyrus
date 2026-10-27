#!/usr/bin/env node
/**
 * Screenshots of the Notification Center from the local preview (see scripts/export-notification-center-fixture.py), at 1440x1000
 * and 390x844, light and dark.
 *   PAPYRUS_PREVIEW_URL=http://127.0.0.1:3012 PAPYRUS_NC_SHOTS_DIR=<dir> node scripts/capture-notification-center-shots.mjs
 * Chrome is taken from PAPYRUS_CHROMIUM_PATH, else the macOS Chrome app, else Playwright's own browser.
 */
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.PAPYRUS_PREVIEW_URL?.trim() || "http://127.0.0.1:3012";
const outputDirectory = path.resolve(process.env.PAPYRUS_NC_SHOTS_DIR?.trim() || "nc-shots");
const chrome = process.env.PAPYRUS_CHROMIUM_PATH?.trim() || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
const schemes = (process.env.PAPYRUS_NC_SCHEMES?.trim() || "light,dark").split(",");
const viewports = [
  { name: "1440", width: 1440, height: 1000, scale: 1 },
  { name: "390", width: 390, height: 844, scale: 2 },
];
mkdirSync(outputDirectory, { recursive: true });

const browser = await chromium.launch({ executablePath: chrome });
const failures = [];
try {
  for (const scheme of schemes) for (const viewport of viewports) {
    const open = async (query = "") => {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale, colorScheme: scheme });
      const page = await context.newPage();
      await page.addInitScript(() => {
        const style = document.createElement("style");
        style.textContent = "nextjs-portal{display:none!important}";
        document.addEventListener("DOMContentLoaded", () => document.head.appendChild(style));
      });
      page.on("pageerror", (error) => failures.push(`${viewport.name}${query}: ${error.message}`));
      await page.goto(new URL(`/${query}`, base).toString(), { waitUntil: "networkidle", timeout: 180_000 });
      await page.locator("[data-notification-center], [data-notification-skeleton]").first().waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2500);
      return { context, page };
    };
    const shoot = async (page, name, options = {}) => {
      const file = path.join(outputDirectory, `nc-${name}-${viewport.name}-${scheme}.png`);
      await page.screenshot({ path: file, ...options });
      console.log(file);
    };
    /** The console scrolls inside its own container, so a full-length shot is taken by growing the viewport to the content. */
    const tall = async (page) => {
      const height = await page.evaluate(() => {
        let element = document.querySelector("[data-notification-center]");
        while (element && element !== document.body) {
          const style = getComputedStyle(element);
          if (/(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 4) return element.scrollHeight + (window.innerHeight - element.clientHeight);
          element = element.parentElement;
        }
        return document.documentElement.scrollHeight;
      });
      await page.setViewportSize({ width: viewport.width, height: Math.min(height, 9000) });
      await page.waitForTimeout(2500);
    };
    const scrollTo = async (page, selector) => {
      await page.locator(selector).first().evaluate((element) => element.scrollIntoView({ block: "start" }));
      await page.waitForTimeout(1500);
    };
    const clipOf = async (locator) => {
      await locator.evaluate((element) => element.scrollIntoView({ block: "center" }));
      await locator.page().waitForTimeout(400);
      const box = await locator.boundingBox();
      return { x: Math.max(0, box.x - 8), y: Math.max(0, box.y - 8), width: box.width + 16, height: box.height + 16 };
    };

    // Real Anth.us data: three monitor-story drafts and the pending References.
    let session = await open();
    await shoot(session.page, "top");
    await scrollTo(session.page, '[data-notification-section="references"]');
    await shoot(session.page, "references");
    await session.page.locator('[data-notification-more-references]').click();
    await session.page.waitForTimeout(800);
    await session.page.evaluate(() => document.querySelector("[data-notification-center]").scrollIntoView({ block: "start" }));
    await tall(session.page);
    await shoot(session.page, "all-full-length");
    await session.page.setViewportSize({ width: viewport.width, height: viewport.height });
    await session.page.locator('[data-notification-filter="drafts"]').click();
    await session.page.waitForTimeout(600);
    await shoot(session.page, "filter-drafts");
    // Accept one draft; Reject another, which asks what the AI should learn.
    const drafts = session.page.locator("[data-review-draft]");
    await drafts.nth(0).locator('textarea').fill("Clear, sourced, and on topic for readers.");
    await drafts.nth(0).locator('[data-review-choice="accept"]').click();
    await session.page.waitForTimeout(900);
    await shoot(session.page, "draft-accepted", { clip: await clipOf(drafts.nth(0)) });
    await drafts.nth(1).locator('[data-review-choice="reject"]').click();
    await session.page.waitForTimeout(500);
    await shoot(session.page, "draft-reject-asks", { clip: await clipOf(drafts.nth(1)) });
    await session.context.close();

    session = await open("?ncState=loading");
    await shoot(session.page, "loading-skeleton");
    await session.context.close();

    session = await open("?ncState=caught-up");
    await shoot(session.page, "all-caught-up");
    await session.context.close();

    // The invented sample has what real data does not today: a hard gate, a soft review, a flag.
    session = await open("?ncState=sample");
    await session.page.locator('[data-notification-filter="other"]').click();
    await session.page.waitForTimeout(600);
    await tall(session.page);
    await shoot(session.page, "other-hard-gate-and-flags");
    await session.context.close();
  }
} finally {
  await browser.close();
}
if (failures.length) {
  console.error(`page errors:\n${failures.join("\n")}`);
  process.exitCode = 1;
}
