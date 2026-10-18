#!/usr/bin/env node
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const previewBaseUrl = process.env.PAPYRUS_PREVIEW_URL?.trim() || "http://127.0.0.1:3002";
const outputDirectory = path.resolve(process.env.PAPYRUS_PREVIEW_SCREENSHOT_DIR?.trim() || "preview-screenshots");
const requestedRoutes = process.argv.slice(2);
const routesToCapture = requestedRoutes.length ? requestedRoutes : ["/newsroom/work"];

const viewportsToCapture = [
  { name: "desktop", width: 1440, height: 900, colorScheme: "light" },
  { name: "desktop-dark", width: 1440, height: 900, colorScheme: "dark" },
  { name: "mobile", width: 390, height: 844, colorScheme: "light" },
];

function fileNameForRoute(route) {
  return route.replace(/^\/+/, "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/-+$/, "") || "home";
}

mkdirSync(outputDirectory, { recursive: true });
const preinstalledChromiumPath = "/opt/pw-browsers/chromium";
const chromiumExecutablePath = process.env.PAPYRUS_PREVIEW_CHROMIUM?.trim()
  || (existsSync(preinstalledChromiumPath) ? preinstalledChromiumPath : undefined);
const browser = await chromium.launch({ executablePath: chromiumExecutablePath });
try {
  for (const viewport of viewportsToCapture) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      colorScheme: viewport.colorScheme,
    });
    const page = await context.newPage();
    for (const route of routesToCapture) {
      await page.goto(new URL(route, previewBaseUrl).toString(), { waitUntil: "networkidle", timeout: 120000 });
      await page.waitForTimeout(1500);
      const outputPath = path.join(outputDirectory, `${fileNameForRoute(route)}-${viewport.name}.png`);
      await page.screenshot({ path: outputPath, fullPage: true });
      console.log(outputPath);
    }
    await context.close();
  }
} finally {
  await browser.close();
}
