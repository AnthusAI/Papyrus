/**
 * Full-app, fixture-only layout acceptance for the References page. Opt in with a running local preview URL
 * (`npm run dev:preview`, then PAPYRUS_REFERENCES_FILL_URL=http://localhost:3002/references?demo=1).
 *   - The grid scroller and the Detail pane both reach the bottom of the viewport (within 2px) at four desktop sizes.
 *   - The confidence bar sits in the vertical middle between the Cyclotron cells and the You buttons, on a card and in the Detail pane.
 *   - The gap under a card's You buttons is no larger than the card's horizontal inner padding.
 * PAPYRUS_REFERENCES_FILL_SHOTS_DIR=<dir> also saves a screenshot per size.
 */
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const SIZES = [[1440, 900], [1440, 1000], [1440, 1300], [1024, 768]] as const;
const TOLERANCE = 2;

async function main() {
  const configured = process.env.PAPYRUS_REFERENCES_FILL_URL;
  if (!configured) {
    console.log("References fill-viewport test skipped: set PAPYRUS_REFERENCES_FILL_URL to a local preview URL.");
    return;
  }
  const target = new URL(configured);
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(target.hostname), "layout acceptance only runs against a local server");
  const shots = process.env.PAPYRUS_REFERENCES_FILL_SHOTS_DIR;
  if (shots) mkdirSync(shots, { recursive: true });
  const chrome = process.env.PAPYRUS_CHROMIUM_PATH || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(existsSync);
  const browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: chrome });
  try {
    for (const [width, height] of SIZES) {
      const page = await browser.newPage({ viewport: { width, height } });
      await page.addInitScript("window.__name = (fn) => fn;"); // tsx wraps named arrow functions in __name, which page.evaluate does not carry
      await page.goto(target.href, { waitUntil: "networkidle", timeout: 180_000 });
      const card = page.locator("[data-feed-card]").first();
      await card.waitFor({ timeout: 60_000 });
      await card.locator("[data-feed-open]").click();
      await page.locator("[data-newsroom-list-detail-shell] [data-rating-grid]").waitFor({ timeout: 30_000 });
      await page.waitForTimeout(800);
      const size = `${width}x${height}`;

      const edges = await page.evaluate(() => {
        const bottom = (selector: string) => document.querySelector(selector)?.getBoundingClientRect().bottom ?? null;
        return { viewport: window.innerHeight, scroller: bottom("[data-reference-feed-scroll]"), detail: bottom("[data-newsroom-list-detail-shell]"), queueBar: bottom("[data-newsroom-list-detail-shell] [data-review-queue-bar]") };
      });
      for (const name of ["scroller", "detail", "queueBar"] as const) {
        const edge = edges[name];
        assert.ok(edge !== null, `${size}: ${name} is missing`);
        assert.ok(Math.abs(edge - edges.viewport) <= TOLERANCE, `${size}: the ${name} bottom (${edge}) must be within ${TOLERANCE}px of the viewport bottom (${edges.viewport})`);
      }

      // Bar centred between the Cyclotron cells and the You buttons, on a card and in the Detail pane.
      const grids = await page.evaluate(() => {
        const measure = (grid: Element) => {
          const rect = (selector: string) => grid.querySelector(selector)!.getBoundingClientRect();
          const bar = rect("[data-confidence-bar]");
          const above = bar.top + bar.height / 2 - rect("[data-cyclotron-choice]").bottom;
          const below = rect("[data-review-choice]").top - (bar.top + bar.height / 2);
          return { above, below };
        };
        const cardGrid = document.querySelector("[data-feed-card] [data-rating-grid]")!;
        const detailGrid = document.querySelector("[data-newsroom-list-detail-shell] [data-rating-grid]")!;
        const footer = cardGrid.closest("[data-feed-actions]")!;
        const owner = footer.closest("[data-feed-card]")!;
        const buttonBottom = cardGrid.querySelector("[data-review-choice]")!.getBoundingClientRect().bottom;
        return {
          card: measure(cardGrid), detail: measure(detailGrid),
          footerGap: owner.getBoundingClientRect().bottom - buttonBottom,
          footerPadding: parseFloat(getComputedStyle(footer).paddingLeft),
        };
      });
      for (const [where, { above, below }] of [["card", grids.card], ["detail", grids.detail]] as const) {
        assert.ok(Math.abs(above - below) <= TOLERANCE, `${size}: the confidence bar must sit midway in the ${where} (above ${above}, below ${below})`);
      }
      assert.ok(grids.footerGap <= grids.footerPadding + TOLERANCE, `${size}: the gap under the You buttons (${grids.footerGap}) must not exceed the card padding (${grids.footerPadding}) + ${TOLERANCE}`);

      if (shots) await page.screenshot({ path: path.join(shots, `references-${size}.png`) });
      console.log(`References fill-viewport passed at ${size}: ${JSON.stringify({ edges, grids })}`);
      await page.close();
    }
  } finally { await browser.close(); }
}

void main().catch((error) => { console.error(error); process.exitCode = 1; });
