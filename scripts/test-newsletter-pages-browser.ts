import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import { CONFIRM_TOKEN, MANAGE_TOKEN, startHarness, type Harness } from "./newsletter-page-harness";

// The newsletter pages in a real browser, in light and dark: confirm -> confirmed, preferences (save, unsubscribe all, re-subscribe,
// delete with a confirm step), the unsubscribe landing page -> unsubscribed, the expired state, and old /api links redirecting.
// The pages are the standard projector's output (features/fixtures/newsletter-site, kept in step by
// procedures/newsroom/tests/test_newsletter_browser_fixture.py) served next to the real /api/newsletter route handlers with a stub
// newsletter function. The server answers like the edge does: a 403 or 404 from a newsletter route becomes the site's 404 page, so a
// rejected form post fails these tests. Every navigation must end on a clean URL, never under /api. No AWS.
//   NEWSLETTER_SCREENSHOTS=<dir> also saves a light and a dark screenshot of every page there.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const site = resolve(root, "features/fixtures/newsletter-site");
const assets = {
  "/css/markus-components.css": resolve(root, "src/papyrus_content/projection/standard/assets/markus-components.css"),
  "/css/markus-vendor.css": resolve(root, "src/papyrus_content/projection/standard/assets/markus-components.css"),
  "/_plugins/papyrus-newsletter-pages@1.js": resolve(root, "src/papyrus_content/projection/plugin_assets/papyrus-newsletter-pages.js"),
};
const screenshots = process.env.NEWSLETTER_SCREENSHOTS;

let browser: Browser;
before(async () => {
  browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
});
after(async () => {
  await browser.close();
});

const COLORS = {
  light: { body: "rgb(198, 244, 50)", main: "rgb(255, 253, 245)" },
  dark: { body: "rgb(198, 244, 50)", main: "rgb(22, 20, 18)" },
} as const;

async function newContext(scheme: "light" | "dark", javaScriptEnabled = true): Promise<{ context: BrowserContext; page: Page; visited: string[]; problems: string[] }> {
  const context = await browser.newContext({ colorScheme: scheme, javaScriptEnabled });
  await context.route((url) => !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  const page = await context.newPage();
  const visited: string[] = [];
  const problems: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) visited.push(frame.url());
  });
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(error.message));
  return { context, page, visited, problems };
}

/** The page is in the site's chrome, themed, noindex, and holds exactly one newsletter container. */
async function chrome(page: Page, scheme: "light" | "dark", heading: string, name: string) {
  await page.getByRole("heading", { level: 1, name: heading }).waitFor();
  assert.equal(await page.locator("header.markus-site-masthead").count(), 1, `${heading}: the site header`);
  assert.equal(await page.locator("footer.markus-site-footer").count(), 1, `${heading}: the site footer`);
  assert.equal(await page.locator("main#main [data-newsletter-page]").count(), 1, `${heading}: the content is in the main area`);
  assert.equal(await page.locator('link[rel="stylesheet"][href="/css/site-theme.css"]').count(), 1);
  assert.equal(await page.locator('meta[name="robots"]').getAttribute("content"), "noindex, nofollow");
  assert.equal(await page.locator('meta[name="referrer"]').getAttribute("content"), "same-origin");
  const painted = await page.evaluate(() => ({
    body: getComputedStyle(document.body).backgroundColor,
    main: getComputedStyle(document.querySelector("main")!).backgroundColor,
    scheme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
    button: document.querySelector("button.markus-button") ? getComputedStyle(document.querySelector("button.markus-button")!).backgroundColor : null,
  }));
  assert.equal(painted.scheme, scheme);
  assert.equal(painted.body, COLORS[scheme].body, `${heading}: lime body`);
  assert.equal(painted.main, COLORS[scheme].main, `${heading}: ${scheme} paper main`);
  if (painted.button !== null) assert.ok(painted.button === "rgb(198, 244, 50)" || painted.button === "rgba(0, 0, 0, 0)", `${heading}: the theme's button colours, got ${painted.button}`);
  if (screenshots) {
    mkdirSync(screenshots, { recursive: true });
    await page.screenshot({ path: join(screenshots, `${name}-${scheme}.png`), fullPage: true });
  }
}

const here = (page: Page) => new URL(page.url());

function assertClean(harness: Harness, visited: string[], problems: string[]) {
  for (const url of visited) assert.ok(!new URL(url).pathname.startsWith("/api"), `the browser never landed on an /api URL: ${url}`);
  const masked = harness.requests.filter((entry) => entry.path.startsWith("/api/newsletter/") && [403, 404].includes(entry.status));
  assert.deepEqual(masked, [], "no newsletter route answered 403 or 404");
  assert.deepEqual(harness.requests.filter((entry) => entry.status >= 500), [], "no server error");
  assert.deepEqual(harness.requests.filter((entry) => !entry.path.startsWith("/api/") && entry.status === 404 && !entry.path.endsWith("/favicon.ico")), [], "no missing page or file");
  assert.deepEqual(problems.filter((text) => !/favicon|Failed to load resource/.test(text)), [], "no script error or CSP violation");
}

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: confirm, then manage preferences (save, unsubscribe all, re-subscribe, delete) on clean pages`, async () => {
    const harness: Harness = await startHarness(site, assets);
    const { context, page, visited, problems } = await newContext(scheme);
    const posts: Array<{ url: string; origin: string | undefined; referer: string | undefined }> = [];
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push({ url: request.url(), origin: request.headers().origin, referer: request.headers().referer });
    });
    try {
      // The confirm page (reading state changes nothing), then the button.
      await page.goto(`${harness.origin}/newsletter/confirm/?token=${CONFIRM_TOKEN}`);
      await chrome(page, scheme, "Confirm your subscription", "confirm");
      await page.getByRole("button", { name: "Confirm subscription" }).waitFor();
      await page.getByText("Weekly roundup").waitFor();
      assert.equal(harness.backend.confirmed, false, "the page changes nothing");
      await page.getByRole("button", { name: "Confirm subscription" }).click();
      await chrome(page, scheme, "You are subscribed", "confirmed");
      assert.equal(here(page).pathname, "/newsletter/confirmed/");
      assert.equal(harness.backend.confirmed, true);
      await page.getByText("Weekly roundup").waitFor();
      assert.equal(posts[0].origin, harness.origin, "the browser sent the site's real origin, not null");
      assert.ok(posts[0].referer?.startsWith(`${harness.origin}/newsletter/confirm/`));

      // Preferences: save, unsubscribe from everything, subscribe again.
      await page.getByRole("link", { name: "Manage your subscriptions" }).click();
      await chrome(page, scheme, "Your subscriptions", "preferences");
      assert.equal(here(page).pathname, "/newsletter/preferences/");
      assert.equal(await page.getByLabel(/Weekly roundup/).isChecked(), true);
      await page.getByLabel(/Alerts/).check();
      await page.getByRole("button", { name: "Save preferences" }).click();
      await chrome(page, scheme, "Your subscriptions", "preferences-saved");
      await page.getByRole("status").filter({ hasText: "Your preferences are saved." }).waitFor();
      assert.equal(here(page).pathname, "/newsletter/preferences/");
      assert.deepEqual([...harness.backend.subscribed].sort(), ["alerts-x", "weekly"]);

      await page.getByRole("button", { name: "Unsubscribe from everything" }).click();
      await page.getByRole("status").filter({ hasText: "You are unsubscribed from everything." }).waitFor();
      assert.equal(harness.backend.subscribed.size, 0);
      assert.equal(await page.getByLabel(/Weekly roundup/).isChecked(), false);
      await chrome(page, scheme, "Your subscriptions", "preferences-unsubscribed");

      await page.getByLabel(/Weekly roundup/).check();
      await page.getByRole("button", { name: "Save preferences" }).click();
      await page.getByRole("status").filter({ hasText: "Your preferences are saved." }).waitFor();
      assert.deepEqual([...harness.backend.subscribed], ["weekly"], "ticking a list again re-subscribes");

      // The unsubscribe landing page and its button; the result links back to preferences.
      await page.goto(`${harness.origin}/newsletter/unsubscribe/?token=${MANAGE_TOKEN}&list=weekly`);
      await chrome(page, scheme, "Unsubscribe", "unsubscribe");
      await page.getByText(/Stop getting .Weekly roundup. from Fixture Site\?/).waitFor();
      await page.getByRole("button", { name: "Unsubscribe from this list" }).click();
      await chrome(page, scheme, "You are unsubscribed", "unsubscribed");
      assert.equal(here(page).pathname, "/newsletter/unsubscribed/");
      assert.equal(harness.backend.subscribed.size, 0);
      await page.getByText("Weekly roundup").waitFor();
      await page.getByRole("link", { name: /Manage your subscriptions/ }).click();
      await chrome(page, scheme, "Your subscriptions", "preferences");
      await page.getByLabel(/Weekly roundup/).check();
      await page.getByRole("button", { name: "Save preferences" }).click();
      await page.getByRole("status").filter({ hasText: "Your preferences are saved." }).waitFor();
      assert.deepEqual([...harness.backend.subscribed], ["weekly"], "the unsubscribed page leads back to re-subscribing");

      // Delete my data: a confirm step first, then the deletion.
      await page.getByRole("button", { name: "Delete my data" }).click();
      await chrome(page, scheme, "Delete your data?", "delete-confirm");
      assert.equal(here(page).search.includes("step=delete"), true);
      assert.equal(harness.backend.deleted, false, "nothing is deleted before the confirm step");
      await page.getByRole("link", { name: "No, go back" }).click();
      await chrome(page, scheme, "Your subscriptions", "preferences");
      await page.getByRole("button", { name: "Delete my data" }).click();
      await page.getByRole("button", { name: "Yes, delete my data" }).click();
      await chrome(page, scheme, "Your data is deleted", "deleted");
      assert.equal(harness.backend.deleted, true);
      assert.equal(here(page).search, "?msg=deleted", "the deleted page carries no token");

      // A used confirmation link ends on the expired page, not on an /api error.
      await page.goto(`${harness.origin}/newsletter/confirm/?token=${CONFIRM_TOKEN}`);
      await chrome(page, scheme, "This link did not work", "expired");
      assert.equal(here(page).pathname, "/newsletter/expired/");
      await page.getByRole("link", { name: /Back to Fixture Site/ }).waitFor();

      for (const post of posts) assert.equal(post.origin, harness.origin, `${post.url} carried the site origin`);
      assertClean(harness, visited, problems);
    } finally {
      await context.close();
      await harness.close();
    }
  });

  test(`${scheme}: links in emails sent before the pages moved still work and end on clean pages`, async () => {
    const harness = await startHarness(site, assets);
    const { context, page, visited, problems } = await newContext(scheme);
    try {
      await page.goto(`${harness.origin}/api/newsletter/confirm?t=${CONFIRM_TOKEN}`);
      await chrome(page, scheme, "Confirm your subscription", "legacy-confirm");
      assert.equal(here(page).pathname, "/newsletter/confirm/");
      assert.equal(here(page).searchParams.get("token"), CONFIRM_TOKEN);
      await page.getByRole("button", { name: "Confirm subscription" }).click();
      await chrome(page, scheme, "You are subscribed", "confirmed");

      await page.goto(`${harness.origin}/api/newsletter/preferences?t=${MANAGE_TOKEN}`);
      await chrome(page, scheme, "Your subscriptions", "preferences");
      assert.equal(here(page).pathname, "/newsletter/preferences/");

      await page.goto(`${harness.origin}/api/newsletter/unsubscribe?t=${MANAGE_TOKEN}&l=weekly`);
      await chrome(page, scheme, "Unsubscribe", "unsubscribe");
      assert.equal(here(page).pathname, "/newsletter/unsubscribe/");
      assert.equal(here(page).searchParams.get("list"), "weekly");
      await page.getByRole("button", { name: "Unsubscribe from this list" }).click();
      await chrome(page, scheme, "You are unsubscribed", "unsubscribed");

      // Old links with no token, or garbage, end on the expired page.
      await page.goto(`${harness.origin}/api/newsletter/unsubscribe`);
      await chrome(page, scheme, "This link did not work", "expired");
      assert.equal(here(page).pathname, "/newsletter/expired/");
      await page.goto(`${harness.origin}/newsletter/preferences/?token=nope%20nope`);
      await chrome(page, scheme, "This link did not work", "expired");
      assertClean(harness, visited, problems);
    } finally {
      await context.close();
      await harness.close();
    }
  });
}

test("without JavaScript the pages say so and offer no form", async () => {
  const harness = await startHarness(site, assets);
  const { context, page } = await newContext("light", false);
  try {
    for (const path of ["confirm/?token=" + CONFIRM_TOKEN, "preferences/?token=" + MANAGE_TOKEN, "unsubscribe/?token=" + MANAGE_TOKEN]) {
      await page.goto(`${harness.origin}/newsletter/${path}`);
      const note = await page.evaluate(() => {
        const paragraph = document.querySelector("noscript p");
        return { text: paragraph?.textContent ?? "", height: paragraph?.getBoundingClientRect().height ?? 0 };
      });
      assert.match(note.text, /needs JavaScript/, `${path}: the note`);
      assert.ok(note.height > 0, `${path}: the note is visible`);
      assert.equal(await page.locator("form:visible").count(), 0, `${path}: no form without JavaScript`);
      assert.equal(await page.locator('a[href*="/api"]').count(), 0, `${path}: nothing links to /api`);
    }
    assert.equal(harness.backend.confirmed, false);
  } finally {
    await context.close();
    await harness.close();
  }
});

test("a form post whose Origin is null is bounced to the expired page, never an /api error", async () => {
  const harness = await startHarness(site, assets);
  try {
    const response = await fetch(`${harness.origin}/api/newsletter/confirm`, {
      method: "POST",
      redirect: "manual",
      headers: { origin: "null", "content-type": "application/x-www-form-urlencoded" },
      body: `t=${CONFIRM_TOKEN}`,
    });
    assert.equal(response.status, 303);
    assert.equal(new URL(response.headers.get("location") ?? "").pathname, "/newsletter/expired/");
    assert.equal(harness.backend.confirmed, false);
  } finally {
    await harness.close();
  }
});

test("the RFC 8058 one-click POST stays a plain 200 with no redirect", async () => {
  const harness = await startHarness(site, assets);
  try {
    const response = await fetch(`${harness.origin}/api/newsletter/unsubscribe?t=${MANAGE_TOKEN}&l=weekly`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "List-Unsubscribe=One-Click",
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("location"), null);
    assert.equal(await response.text(), "Unsubscribed.");
  } finally {
    await harness.close();
  }
});
