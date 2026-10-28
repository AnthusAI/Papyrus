#!/usr/bin/env node
/**
 * Screenshots of the "What needs me" feed from the local preview (see scripts/export-notification-center-fixture.py), at 1440x1000
 * and 390x844, light and dark. `?ncState=mixed` adds the invented hard gate, flag and held email to the real data.
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
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale, colorScheme: scheme });
    const page = await context.newPage();
    await page.addInitScript(() => {
      const style = document.createElement("style");
      style.textContent = "nextjs-portal{display:none!important}";
      document.addEventListener("DOMContentLoaded", () => document.head.appendChild(style));
    });
    page.on("pageerror", (error) => failures.push(`${viewport.name} ${scheme}: ${error.message}`));
    await page.goto(new URL("/?ncState=mixed", base).toString(), { waitUntil: "networkidle", timeout: 240_000 });
    await page.locator("[data-needs-me-card]").first().waitFor({ timeout: 90_000 });
    await page.waitForTimeout(3000);
    const shoot = async (name, options = {}) => {
      const file = path.join(outputDirectory, `needsme-${name}-${viewport.name}-${scheme}.png`);
      await page.screenshot({ path: file, ...options });
      console.log(file);
    };
    const toTop = () => page.evaluate(() => document.querySelector("[data-notification-center]").scrollIntoView({ block: "start" }));
    const open = async (selector, ready) => {
      await page.locator(selector).first().evaluate((element) => element.scrollIntoView({ block: "center" }));
      await page.locator(`${selector} [data-feed-open]`).first().click();
      await page.locator(ready).first().waitFor();
      await page.waitForTimeout(1200);
    };
    const close = async () => { await page.keyboard.press("Escape"); await page.waitForTimeout(500); };

    await shoot("1-mixed-feed-hard-gate-first");
    await page.locator("[data-shaping-strip]").evaluate((element) => element.scrollIntoView({ block: "start" }));
    await shoot("2-shaping-strip");
    await toTop();
    await page.locator('[data-notification-filter="drafts"]').click();
    await page.waitForTimeout(600);
    await shoot("3-filtered-to-drafts");
    await page.locator('[data-notification-filter="all"]').click();
    await open('[data-needs-me-card="draft"]', '[data-needs-me-detail-type="draft"]');
    await shoot("4-detail-draft");
    await close();
    await open('[data-needs-me-card="held_email"]', "[data-email-body]");
    await shoot("5-detail-held-email");
    await close();
    await open('[data-needs-me-card="reference"]', '[data-needs-me-detail-type="reference"]');
    await shoot("6-detail-reference");
    await close();
    await open('[data-needs-me-card="stage_review"]', '[data-needs-me-detail-type="stage_review"]');
    await shoot("7-detail-hard-gate");
    await close();
    const auto = page.locator('[data-notification-section="auto-decided"]');
    if (await auto.count()) {
      await auto.locator("summary").evaluate((element) => element.scrollIntoView({ block: "center" }));
      await auto.locator("summary").click();
      await page.waitForTimeout(700);
      await shoot("8-decided-automatically");
    }
    await context.close();
  }
} finally {
  await browser.close();
}
if (failures.length) {
  console.error(`page errors:\n${failures.join("\n")}`);
  process.exitCode = 1;
}
