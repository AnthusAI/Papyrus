#!/usr/bin/env node

const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const targetUrl = process.env.PAPYRUS_BLOG_HEADER_URL ?? "http://127.0.0.1:3001/2026/july/04";

async function waitForObstacles(page) {
  await page.waitForSelector(".blog-page-background[data-blog-page-background-obstacles]", { timeout: 15000 });
  await page.waitForFunction(() => {
    const element = document.querySelector(".blog-page-background[data-blog-page-background-obstacles]");
    if (!element) return false;
    try {
      return JSON.parse(element.getAttribute("data-blog-page-background-obstacles") ?? "[]").length > 0;
    } catch {
      return false;
    }
  }, null, { timeout: 15000 });
}

async function evaluateWithNavigationRetry(page, callback, attempts = 4) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      await waitForObstacles(page);
      return await page.evaluate(callback);
    } catch (error) {
      lastError = error;
      const message = error instanceof Error ? error.message : String(error);
      if (!/Execution context was destroyed|Cannot find context|navigation|Timeout/i.test(message)) {
        throw error;
      }
      await page.waitForLoadState("domcontentloaded").catch(() => undefined);
      await page.waitForTimeout(250);
    }
  }
  throw lastError;
}

async function assertDesktopBlankRegion(browser) {
  const page = await browser.newPage({ viewport: { width: 1254, height: 716 } });
  try {
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    const result = await evaluateWithNavigationRetry(page, () => {
      function textRect(element) {
        const textNode = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
        if (!textNode || !textNode.textContent?.trim()) {
          throw new Error(`Missing text node for ${element.textContent}`);
        }
        const leadingWhitespace = textNode.textContent.search(/\S/);
        const range = document.createRange();
        range.setStart(textNode, Math.max(0, leadingWhitespace));
        range.setEnd(textNode, textNode.textContent.trimEnd().length);
        const rect = range.getBoundingClientRect();
        range.detach();
        return {
          bottom: rect.bottom,
          left: rect.left,
          right: rect.right,
          top: rect.top,
        };
      }

      const background = document.querySelector(".blog-page-background[data-blog-page-background-obstacles]");
      if (!background) throw new Error("Missing blog background");
      const containerRect = background.getBoundingClientRect();
      const threat = Array.from(document.querySelectorAll(".presentation-header h1 span"))
        .find((span) => span.textContent?.trim() === "THREAT");
      if (!threat) throw new Error("Missing THREAT masthead span");

      const spanRect = threat.getBoundingClientRect();
      const renderedTextRect = textRect(threat);
      const obstacles = JSON.parse(background.getAttribute("data-blog-page-background-obstacles") ?? "[]");
      const blankWidth = spanRect.right - renderedTextRect.right;
      const probe = {
        x: ((renderedTextRect.right + spanRect.right) / 2) - containerRect.left,
        y: ((renderedTextRect.top + renderedTextRect.bottom) / 2) - containerRect.top,
      };
      const overlappingProbe = obstacles.filter((obstacle) => (
        probe.x >= obstacle.x
        && probe.x <= obstacle.x + obstacle.width
        && probe.y >= obstacle.y
        && probe.y <= obstacle.y + obstacle.height
      ));
      const threatLineObstacles = obstacles.filter((obstacle) => (
        probe.y >= obstacle.y
        && probe.y <= obstacle.y + obstacle.height
        && obstacle.x <= renderedTextRect.right - containerRect.left
      ));
      const threatTextRight = renderedTextRect.right - containerRect.left;
      const maxThreatObstacleRight = threatLineObstacles.reduce((max, obstacle) => (
        Math.max(max, obstacle.x + obstacle.width)
      ), -Infinity);

      return {
        blankWidth,
        maxThreatObstacleRight,
        obstacleCount: obstacles.length,
        overlappingProbeCount: overlappingProbe.length,
        probe,
        spanRight: spanRect.right - containerRect.left,
        threatTextRight,
      };
    });

    assert.ok(result.obstacleCount > 0, "expected the rendered page to expose header text obstacles");
    assert.ok(
      result.blankWidth > 80,
      `expected a meaningful blank region to the right of THREAT, got ${result.blankWidth}`,
    );
    assert.equal(
      result.overlappingProbeCount,
      0,
      `blank region probe should not be covered by text obstacles: ${JSON.stringify(result.probe)}`,
    );
    assert.ok(
      result.maxThreatObstacleRight <= result.threatTextRight + 28,
      `THREAT obstacle should hug rendered text, got obstacle right ${result.maxThreatObstacleRight} vs text right ${result.threatTextRight}`,
    );
  } finally {
    await page.close();
  }
}

async function assertNarrowCoreGap(browser) {
  const page = await browser.newPage({ viewport: { width: 558, height: 716 } });
  try {
    await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    const result = await evaluateWithNavigationRetry(page, () => {
      const background = document.querySelector(".blog-page-background[data-blog-page-background-obstacles]");
      if (!background) throw new Error("Missing blog background");
      const containerRect = background.getBoundingClientRect();
      const core = document.querySelector('[data-blog-node-id="core"]');
      const threat = Array.from(document.querySelectorAll(".presentation-header h1 span"))
        .find((span) => span.textContent?.trim() === "THREAT");
      const intelligence = Array.from(document.querySelectorAll(".presentation-header h1 span"))
        .find((span) => span.textContent?.trim() === "INTELLIGENCE");
      if (!threat || !intelligence) throw new Error("Missing masthead words");

      const threatRect = threat.getBoundingClientRect();
      const intelligenceRect = intelligence.getBoundingClientRect();
      const coreRect = core
        ? {
            cx: Number(core.getAttribute("cx")),
            cy: Number(core.getAttribute("cy")),
            r: Number(core.getAttribute("r")),
          }
        : null;
      const obstacles = JSON.parse(background.getAttribute("data-blog-page-background-obstacles") ?? "[]");
      const threatObstacle = obstacles
        .filter((obstacle) => obstacle.y <= ((threatRect.top + threatRect.bottom) / 2) - containerRect.top
          && obstacle.y + obstacle.height >= ((threatRect.top + threatRect.bottom) / 2) - containerRect.top)
        .sort((left, right) => (right.x + right.width) - (left.x + left.width))[0];

      return {
        core: coreRect,
        intelligenceTop: intelligenceRect.top - containerRect.top,
        obstacleCount: obstacles.length,
        threatBottom: threatRect.bottom - containerRect.top,
        threatObstacleRight: threatObstacle ? threatObstacle.x + threatObstacle.width : null,
      };
    });

    assert.ok(result.obstacleCount > 0, "expected narrow header text obstacles");
    assert.ok(result.core, "core node should remain visible at 558px");
    assert.ok(
      result.threatObstacleRight !== null && result.core.cx > result.threatObstacleRight + result.core.r,
      `core should sit to the right of the THREAT obstacle, got core ${JSON.stringify(result.core)} and obstacle right ${result.threatObstacleRight}`,
    );
    assert.ok(
      result.core.cy < result.intelligenceTop,
      `core should sit above INTELLIGENCE, got core y ${result.core.cy} and intelligence top ${result.intelligenceTop}`,
    );
  } finally {
    await page.close();
  }
}

async function main() {
  const browser = await chromium.launch();
  try {
    await assertDesktopBlankRegion(browser);
    await assertNarrowCoreGap(browser);
  } finally {
    await browser.close();
  }
}

main()
  .then(() => {
    console.log("blog header obstacle measurement test passed");
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
