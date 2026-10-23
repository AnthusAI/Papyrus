/** Full-app, fixture-only layout regression. Opt in with a running local demo URL. */
import assert from "node:assert/strict";
import { chromium } from "playwright";

async function main() {
  const configured = process.env.PAPYRUS_REFERENCE_LAYOUT_URL;
  if (!configured) {
    console.log("Reference editor layout skipped: set PAPYRUS_REFERENCE_LAYOUT_URL to a local demo URL.");
    return;
  }
  const target = new URL(configured);
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(target.hostname), "layout acceptance only runs against a local server");
  assert.equal(target.searchParams.get("demo"), "1", "layout acceptance requires synthetic demo mode");
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.goto(target.href, { waitUntil: "domcontentloaded" });
    const row = page.locator('[data-news-desk-section="references"] [data-newsroom-card-id]').first();
    await row.waitFor({ state: "attached" });
    await page.locator("[data-reference-cyclotron-status]").waitFor({ state: "attached" });
    const geometry = await row.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      const viewport = element.closest(".papyrus-ui-scroll-area")?.getBoundingClientRect();
      let top = Math.max(bounds.top, 0);
      let bottom = Math.min(bounds.bottom, window.innerHeight);
      const clippers: Array<{ tag: string; top: number; height: number }> = [];
      for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor);
        if (/auto|scroll|hidden|clip/.test(style.overflowY)) {
          const clip = ancestor.getBoundingClientRect();
          clippers.push({ tag: ancestor.getAttribute("data-slot") || ancestor.tagName, top: clip.top, height: clip.height });
          top = Math.max(top, clip.top);
          bottom = Math.min(bottom, clip.bottom);
        }
      }
      return { rowTop: bounds.top, rowHeight: bounds.height, scrollHeight: viewport?.height ?? 0, visibleHeight: Math.max(0, bottom - top), clippers };
    });
    assert.ok(geometry.scrollHeight > 0 && geometry.visibleHeight > 0,
      `The first reference must be visible inside its scroll viewport at 1280x720: ${JSON.stringify(geometry)}`);
    await page.getByRole("tab", { name: /^Pending/ }).click();
    await row.click();
    await page.locator('[data-news-desk-reference-detail]:visible').waitFor();
    const feedback = page.locator('[data-news-desk-reference-detail]:visible').getByLabel("Review explanation (optional)", { exact: true });
    await feedback.scrollIntoViewIfNeeded();
    if (process.env.PAPYRUS_REFERENCE_LAYOUT_SCREENSHOT) {
      await page.screenshot({ path: process.env.PAPYRUS_REFERENCE_LAYOUT_SCREENSHOT, fullPage: false });
    }
    console.log(`Reference editor layout passed at 1280x720: ${JSON.stringify(geometry)}`);
  } finally { await browser.close(); }
}

void main().catch((error) => { console.error(error); process.exitCode = 1; });
