import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import { CONFIRM_TOKEN, MANAGE_TOKEN, startHarness, type Harness } from "./newsletter-page-harness";

// The newsletter pages in a real browser: confirm, confirmed, preferences (save, unsubscribe all, re-subscribe, delete) and the
// unsubscribe landing page, in light and dark. The routes are the real handlers behind a loopback server with a stub
// newsletter function and a fixture site shell (features/fixtures/newsletter-site); no AWS. The server answers like the
// edge does: a 403 or 404 from a newsletter route becomes the site's 404 page, so a rejected form post fails these tests.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const site = resolve(root, "features/fixtures/newsletter-site");
const components = resolve(root, "src/papyrus_content/projection/standard/assets/markus-components.css");

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

async function chrome(page: Page, scheme: "light" | "dark", heading: string) {
  await page.getByRole("heading", { level: 1, name: heading }).waitFor();
  assert.equal(await page.locator("header.markus-site-masthead").count(), 1, `${heading}: the site header`);
  assert.equal(await page.locator("footer.markus-site-footer").count(), 1, `${heading}: the site footer`);
  assert.equal(await page.locator("main#main [data-newsletter-page]").count(), 1, `${heading}: the content is in the main area`);
  assert.equal(await page.locator("head style").count(), 0, `${heading}: the site's stylesheet, not the self-contained page`);
  assert.ok((await page.locator('link[rel="stylesheet"][href="/css/site-theme.css"]').count()) === 1);
  assert.equal(await page.locator('meta[name="theme-color"]').first().getAttribute("content"), "#C6F432");
  assert.equal(await page.locator('meta[name="robots"]').getAttribute("content"), "noindex, nofollow");
  assert.equal(await page.locator('link[rel="canonical"]').count(), 0);
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
}

for (const scheme of ["light", "dark"] as const) {
  test(`${scheme}: confirm, then manage preferences (save, unsubscribe all, re-subscribe, delete) inside the site's chrome`, async () => {
    const harness: Harness = await startHarness(site, { "/css/markus-components.css": components });
    const context: BrowserContext = await browser.newContext({ colorScheme: scheme });
    await context.route((url) => !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
    const page = await context.newPage();
    const posts: Array<{ url: string; origin: string | undefined; referer: string | undefined }> = [];
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push({ url: request.url(), origin: request.headers().origin, referer: request.headers().referer });
    });
    try {
      // The confirm prompt (a GET that changes nothing), then the button.
      await page.goto(`${harness.origin}/api/newsletter/confirm?t=${CONFIRM_TOKEN}`);
      await chrome(page, scheme, "Confirm your subscription");
      assert.equal(harness.backend.confirmed, false, "the prompt changes nothing");
      await page.getByRole("button", { name: "Confirm subscription" }).click();
      await chrome(page, scheme, "You are subscribed");
      assert.equal(harness.backend.confirmed, true);
      assert.equal(posts[0].origin, harness.origin, "the browser sent the site's real origin, not null");
      assert.ok(posts[0].referer?.startsWith(`${harness.origin}/api/newsletter/confirm`));

      // Preferences: save, unsubscribe from everything, subscribe again.
      await page.getByRole("link", { name: "Manage your subscriptions" }).click();
      await chrome(page, scheme, "Your subscriptions");
      assert.equal(await page.getByLabel(/Weekly roundup/).isChecked(), true);
      await page.getByLabel(/Alerts/).check();
      await page.getByRole("button", { name: "Save preferences" }).click();
      await chrome(page, scheme, "Your subscriptions");
      await page.getByRole("status").filter({ hasText: "Your preferences are saved." }).waitFor();
      assert.deepEqual([...harness.backend.subscribed].sort(), ["alerts-x", "weekly"]);

      await page.getByRole("button", { name: "Unsubscribe from everything" }).click();
      await page.getByRole("status").filter({ hasText: "You are unsubscribed from everything." }).waitFor();
      assert.equal(harness.backend.subscribed.size, 0);
      assert.equal(await page.getByLabel(/Weekly roundup/).isChecked(), false);

      await page.getByLabel(/Weekly roundup/).check();
      await page.getByRole("button", { name: "Save preferences" }).click();
      await page.getByRole("status").filter({ hasText: "Your preferences are saved." }).waitFor();
      assert.deepEqual([...harness.backend.subscribed], ["weekly"], "ticking a list again re-subscribes");

      // The unsubscribe landing page and its button.
      await page.goto(`${harness.origin}/api/newsletter/unsubscribe?t=${MANAGE_TOKEN}&l=weekly`);
      await chrome(page, scheme, "Unsubscribe");
      await page.getByRole("button", { name: "Unsubscribe from this list" }).click();
      await chrome(page, scheme, "You are unsubscribed");
      assert.equal(harness.backend.subscribed.size, 0);

      // Delete my data: a confirm step first, then the deletion.
      await page.goto(`${harness.origin}/api/newsletter/preferences?t=${MANAGE_TOKEN}`);
      await page.getByRole("button", { name: "Delete my data" }).click();
      await chrome(page, scheme, "Delete your data?");
      assert.equal(harness.backend.deleted, false, "nothing is deleted before the confirm step");
      await page.getByRole("button", { name: "Yes, delete my data" }).click();
      await chrome(page, scheme, "Your data is deleted");
      assert.equal(harness.backend.deleted, true);

      // An expired link is a styled page with a status the edge passes through.
      await page.goto(`${harness.origin}/api/newsletter/confirm?t=${CONFIRM_TOKEN}`);
      await chrome(page, scheme, "This link has expired");

      for (const post of posts) assert.equal(post.origin, harness.origin, `${post.url} carried the site origin`);
      const hidden = harness.requests.filter((entry) => entry.path.startsWith("/api/newsletter/") && [403, 404].includes(entry.status));
      assert.deepEqual(hidden, [], "no newsletter route answered 403 or 404");
    } finally {
      await context.close();
      await harness.close();
    }
  });
}

test("a form post whose Origin is null is refused with a styled 400, not a masked 404", async () => {
  const harness = await startHarness(site, { "/css/markus-components.css": components });
  try {
    const response = await fetch(`${harness.origin}/api/newsletter/confirm`, {
      method: "POST",
      headers: { origin: "null", "content-type": "application/x-www-form-urlencoded" },
      body: `t=${CONFIRM_TOKEN}`,
    });
    assert.equal(response.status, 400);
    assert.match(await response.text(), /did not go through/);
    assert.equal(harness.backend.confirmed, false);
  } finally {
    await harness.close();
  }
});

test("when the site shell cannot be fetched the self-contained page still works and posts correctly", async () => {
  const harness = await startHarness(resolve(site, "css"), { "/css/markus-components.css": components });
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(`${harness.origin}/api/newsletter/confirm?t=${CONFIRM_TOKEN}`);
    assert.equal(await page.locator("head style").count(), 1);
    await page.getByRole("button", { name: "Confirm subscription" }).click();
    await page.getByRole("heading", { level: 1, name: "You are subscribed" }).waitFor();
    assert.equal(harness.backend.confirmed, true);
  } finally {
    await context.close();
    await harness.close();
  }
});
