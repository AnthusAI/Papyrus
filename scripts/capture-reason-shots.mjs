#!/usr/bin/env node
/**
 * Screenshots of a decision's reason given after the label, and of reopening a decided item to read and change it, for an AI draft,
 * a Reference and a held email, from the local preview with the real Anth.us export
 * (scripts/export-notification-center-fixture.py, scripts/export-reference-feed-fixture.py) in the anth-us brand, at 1440x1000 and 390x844,
 * light and dark. `?ncState=mixed` adds the invented held email to the real data.
 *   PAPYRUS_PREVIEW_URL=http://127.0.0.1:3021 PAPYRUS_REASON_SHOTS_DIR=<dir> node scripts/capture-reason-shots.mjs
 */
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.PAPYRUS_PREVIEW_URL?.trim() || "http://127.0.0.1:3021";
const outputDirectory = path.resolve(process.env.PAPYRUS_REASON_SHOTS_DIR?.trim() || "reason-shots");
const chrome = process.env.PAPYRUS_CHROMIUM_PATH?.trim() || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
const referencesUrl = process.env.PAPYRUS_REFERENCES_URL?.trim();
const viewports = [{ name: "1440", width: 1440, height: 1000, scale: 1 }, { name: "390", width: 390, height: 844, scale: 2 }];
mkdirSync(outputDirectory, { recursive: true });

const browser = await chromium.launch({ executablePath: chrome });
const failures = [];
try {
  for (const scheme of ["light", "dark"]) for (const viewport of viewports) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: viewport.scale, colorScheme: scheme });
    const page = await context.newPage();
    await page.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
      const style = document.createElement("style"); style.textContent = "nextjs-portal{display:none!important}"; document.head.appendChild(style);
    }));
    page.on("pageerror", (error) => failures.push(`${viewport.name} ${scheme}: ${error.message}`));
    await page.goto(new URL("/?ncState=mixed", base).toString(), { waitUntil: "networkidle", timeout: 240_000 });
    await page.locator("[data-needs-me-card]").first().waitFor({ timeout: 90_000 });
    await page.waitForTimeout(3000);
    const shoot = async (name) => {
      const file = path.join(outputDirectory, `${name}-${viewport.name}-${scheme}.png`);
      await page.screenshot({ path: file });
      console.log(file);
    };
    const pane = () => page.locator("[data-needs-me-detail]").locator("visible=true").first();
    const open = async (selector) => {
      const card = page.locator(selector).first();
      await card.evaluate((element) => element.scrollIntoView({ block: "center" }));
      await card.locator("[data-feed-open]").click();
      await pane().waitFor();
      await page.waitForTimeout(900);
    };
    const close = async () => { await page.keyboard.press("Escape"); await page.waitForTimeout(600); };
    const toDecision = async () => {
      await pane().locator("[data-review-reason] textarea").evaluate((element) => element.scrollIntoView({ block: "center" }));
      await page.waitForTimeout(500);
    };
    const reasonAfterVote = async (selector, choice, reason, name, saved) => {
      await open(selector);
      await pane().locator(`[data-review-choice="${choice}"]`).first().click();
      await page.waitForTimeout(1500);
      const why = pane().locator("[data-review-reason] textarea");
      await why.fill(reason);
      await why.blur();
      await pane().locator(saved).first().waitFor();
      await toDecision();
      await shoot(`${name}-1-reason-added-saved-tick`);
      await close();
      await open(selector);
      await toDecision();
      await shoot(`${name}-2-reopened-editable`);
      await close();
    };

    // Previous / Next in the bottom-right corner, at rest and after the feed has scrolled to its end.
    await open('[data-needs-me-card="draft"]');
    await shoot("needsme-bar-bottom-right");
    await page.evaluate(() => { for (const node of document.querySelectorAll("[data-needs-me-scroll]")) node.scrollTop = 99999; });
    await page.waitForTimeout(600);
    await shoot("needsme-bar-after-scroll");
    await close();
    await reasonAfterVote('[data-needs-me-card="draft"]', "accept", "Specific, sourced and a story our readers will want. Keep the second paragraph.", "draft", "[data-reason-saved]");
    await reasonAfterVote('[data-needs-me-card="held_email"]', "reject", "A newsletter we do not use for sourcing; the links are all promotions.", "held-email", "[data-reason-saved]");
    await reasonAfterVote('[data-needs-me-card="reference"]', "accept", "On topic and from a primary source.", "reference", "[data-review-saved]");
    if (referencesUrl) {
      await page.goto(referencesUrl, { waitUntil: "networkidle", timeout: 240_000 });
      await page.locator("[data-feed-card]").first().waitFor({ timeout: 90_000 });
      await page.waitForTimeout(3000);
      await page.locator("[data-feed-card] [data-feed-open]").first().click();
      await page.waitForTimeout(1500);
      await shoot("references-bar-bottom-right");
      await page.evaluate(() => { for (const node of document.querySelectorAll("*")) if (node.scrollHeight > node.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(node).overflowY)) node.scrollTop = 99999; });
      await page.waitForTimeout(600);
      await shoot("references-bar-after-scroll");
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
