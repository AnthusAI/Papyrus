import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { chromium, type Browser, type BrowserContext, type Page, type Route } from "playwright";

// Behaviour of the reader islands (the reader-steering plugin's static assets) in a real browser against a fake reader API.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const assets = resolve(root, "src/papyrus_content/projection/plugin_assets");
const script = readFileSync(resolve(assets, "papyrus-reader.js"), "utf8");
const css = readFileSync(resolve(assets, "papyrus-reader.css"), "utf8");
const coreRuntime = readFileSync(resolve(root, "src/papyrus_content/projection/standard/assets/papyrus-islands.js"), "utf8");
const ORIGIN = "https://reader.example.test";
const SUBJECT = "item-one";
const READER_ID = ["00000000", "0000", "0000", "0000", "000000000005"].join("-");

const PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Reader islands</title>
<link rel="stylesheet" href="/_plugins/papyrus-reader@1.css"><script src="/_plugins/papyrus-reader@1.js" defer></script></head><body>
<header><div id="signin" data-island="ReaderSignIn"></div></header>
<main><h1>An item</h1>
<div id="vote" class="papyrus-island" data-island="Vote" data-props='{"subject":"${SUBJECT}","up":3}'><p class="papyrus-island-summary">3 upvotes</p></div>
<div id="usedit" data-island="UsedIt" data-props='{"subject":"${SUBJECT}","usedIt":1}'></div>
<div id="rating" data-island="Rating" data-props='{"subject":"${SUBJECT}","dimensions":["real","useful"],"ratings":{"real":{"reader":{"mean":3.5,"n":2,"hist":[0,0,1,1,0]},"editor":{"mean":null,"n":0,"hist":[0,0,0,0,0]}}}}'></div>
<div id="fresh" data-island="Freshness" data-props='{"generatedAt":"2000-01-01T00:00:00Z"}'></div></main></body></html>`;

type Fake = {
  me: { status: number; body: Record<string, unknown> };
  snapshot: Record<string, unknown> | null;
  writes: Array<{ path: string; body: Record<string, unknown> }>;
  meRequests: string[];
  snapshotRequests: number;
  writeAnswer: (path: string, body: Record<string, unknown>) => { status: number; body: Record<string, unknown> };
  holdSnapshot: Promise<void> | null;
};

const signedInMe = (changes: Record<string, unknown> = {}) => ({
  status: 200,
  body: { readerId: READER_ID, handle: "quiet-fox", karma: 7, state: "active", votes: {}, ...changes },
});
const snapshotAt = (generatedAt: string, item: Record<string, unknown> = {}) => ({
  generatedAt,
  items: { [SUBJECT]: { up: 5, usedIt: 2, ratings: { real: { reader: { mean: 4.2, n: 5, hist: [0, 0, 1, 2, 2] }, editor: { mean: 4, n: 1, hist: [0, 0, 0, 1, 0] } }, useful: { reader: { mean: null, n: 0, hist: [0, 0, 0, 0, 0] }, editor: { mean: null, n: 0, hist: [0, 0, 0, 0, 0] } } }, ...item } },
});

let browser: Browser;
before(async () => {
  browser = await chromium.launch({ args: ["--no-proxy-server"], executablePath: process.env.PAPYRUS_CHROMIUM_PATH || undefined });
});
after(async () => {
  await browser.close();
});

function fake(changes: Partial<Fake> = {}): Fake {
  return {
    me: signedInMe(),
    snapshot: snapshotAt(new Date(Date.now() - 5 * 60_000).toISOString()),
    writes: [],
    meRequests: [],
    snapshotRequests: 0,
    writeAnswer: (path, body) => ({ status: 200, body: path === "/api/reader/handle" ? { handle: String(body.handle).toLowerCase() } : { subject: body.subject, dimension: body.dimension } }),
    holdSnapshot: null,
    ...changes,
  };
}

async function open(context: BrowserContext, state: Fake, options: { clock?: boolean; page?: string } = {}): Promise<Page> {
  await context.route("**/*", async (route: Route) => {
    const url = new URL(route.request().url());
    const json = (status: number, body: unknown) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/article.html") return route.fulfill({ contentType: "text/html", body: options.page ?? PAGE });
    if (url.pathname === "/_plugins/papyrus-reader@1.js") return route.fulfill({ contentType: "text/javascript", body: script });
    if (url.pathname === "/_plugins/papyrus-islands-v1.js") return route.fulfill({ contentType: "text/javascript", body: coreRuntime });
    if (url.pathname === "/_plugins/papyrus-reader@1.css") return route.fulfill({ contentType: "text/css", body: css });
    if (url.pathname === "/_data/reader/items.json") {
      state.snapshotRequests += 1;
      if (state.holdSnapshot) await state.holdSnapshot;
      return state.snapshot ? json(200, state.snapshot) : json(404, {});
    }
    if (url.pathname === "/api/reader/me") {
      state.meRequests.push(url.search);
      return json(state.me.status, state.me.body);
    }
    if (url.pathname.startsWith("/api/reader/") && route.request().method() === "POST") {
      const body = JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>;
      state.writes.push({ path: url.pathname, body });
      const answer = state.writeAnswer(url.pathname, body);
      return json(answer.status, answer.body);
    }
    return route.fulfill({ status: 404, body: "" });
  });
  const page = await context.newPage();
  if (options.clock) await page.clock.install();
  await page.goto(`${ORIGIN}/article.html`);
  return page;
}

const unavailable = { status: 503, body: { error: "reader_identity_unavailable", message: "Reader sign-in is not open yet." } };

test("while the API answers 503 reader_identity_unavailable every control is disabled and says the sign-in is not open yet", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: unavailable }));
  await page.locator("#signin").getByText("Reader sign-in is not open yet").waitFor();
  for (const id of ["#vote", "#usedit", "#rating"]) {
    await page.locator(`${id} .papyrus-reader-status`).getByText("Reader sign-in is not open yet").waitFor();
    for (const button of await page.locator(`${id} button`).all()) assert.equal(await button.isDisabled(), true, `${id} button is disabled`);
  }
  assert.equal(await page.locator("#signin a").count(), 0, "no sign-in link while sign-in is closed");
  await context.close();
});

test("signed out: a Sign in link returns to this page and the controls say why they are off", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: { status: 401, body: { error: "signed_out" } } }));
  const link = page.getByRole("link", { name: "Sign in" });
  await link.waitFor();
  assert.equal(await link.getAttribute("href"), "/api/auth/prospectus/sign-in?returnTo=%2Farticle.html");
  await page.locator("#vote .papyrus-reader-status").getByText("Sign in to vote and rate").waitFor();
  assert.equal(await page.getByRole("button", { name: "Upvote" }).isDisabled(), true);
  await context.close();
});

test("the islands prerender their props before any request answers, and the page's text fallback is replaced", async () => {
  const context = await browser.newContext();
  let release: () => void = () => {};
  const held = new Promise<void>((resolveHeld) => { release = resolveHeld; });
  const page = await open(context, fake({ holdSnapshot: held }));
  await page.locator("#vote .papyrus-reader-count").getByText("3 upvotes").waitFor();
  assert.equal(await page.locator("#vote .papyrus-island-summary").count(), 0, "the no-JavaScript summary is removed once mounted");
  await page.locator("#usedit .papyrus-reader-count").getByText("1 reader used it").waitFor();
  await page.locator("#rating").getByText("Readers: 3.5 from 2 ratings").waitFor();
  await page.locator("#fresh").getByText(/Updated \d+ days? ago/).waitFor();
  release();
  await page.locator("#vote .papyrus-reader-count").getByText("5 upvotes").waitFor();
  await page.locator("#usedit .papyrus-reader-count").getByText("2 readers used it").waitFor();
  await page.locator("#fresh").getByText("Updated 5 min ago").waitFor();
  await page.locator("#rating").getByText("Editor: 4.0 from 1 rating").waitFor();
  await context.close();
});

test("signed in without a handle: the picker reports a taken handle and then shows the handle, karma and Sign out", async () => {
  const context = await browser.newContext();
  const state = fake({ me: signedInMe({ handle: null, karma: 0 }) });
  state.writeAnswer = (path, body) => body.handle === "taken-name" ? { status: 409, body: { error: "handle_taken", message: "That handle is taken." } } : { status: 200, body: { handle: String(body.handle).toLowerCase() } };
  const page = await open(context, state);
  const input = page.getByLabel("Choose a handle");
  await input.fill("taken-name");
  await page.getByRole("button", { name: "Save handle" }).click();
  await page.locator("#signin").getByText("That handle is taken. Try another.").waitFor();
  await input.fill("Quiet-Fox");
  await input.press("Enter");
  await page.locator("#signin .papyrus-reader-handle").getByText("quiet-fox").waitFor();
  await page.locator("#signin").getByText("Karma 0").waitFor();
  await page.locator("#signin").getByRole("button", { name: "Sign out" }).waitFor();
  assert.deepEqual(state.writes.map((write) => write.body.handle), ["taken-name", "Quiet-Fox"]);
  await context.close();
});

test("signed in with a handle: the handle, karma and a Sign out form that posts to the sign-out route", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake());
  await page.locator("#signin").getByText("Karma 7").waitFor();
  assert.equal(await page.locator("#signin .papyrus-reader-handle").textContent(), "quiet-fox");
  const form = page.locator("#signin form");
  assert.equal(await form.getAttribute("method"), "post");
  assert.equal(await form.getAttribute("action"), "/api/auth/prospectus/sign-out");
  await context.close();
});

test("a handle that looks like markup is shown as text", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: signedInMe({ handle: "<img src=x onerror=window.pwned=1>" }) }));
  await page.locator("#signin .papyrus-reader-handle").waitFor();
  assert.equal(await page.locator("#signin img").count(), 0);
  assert.equal(await page.evaluate(() => (window as unknown as { pwned?: number }).pwned), undefined);
  await context.close();
});

test("upvote: aria-pressed and words change at once, the count moves by one, and the write is a vote", async () => {
  const context = await browser.newContext();
  const state = fake({ me: signedInMe({ votes: {} }) });
  const page = await open(context, state);
  const button = page.locator("#vote button");
  await page.locator("#vote .papyrus-reader-count").getByText("5 upvotes").waitFor();
  assert.equal(await button.getAttribute("aria-pressed"), "false");
  assert.equal(await button.textContent(), "Upvote");
  await button.click();
  await page.locator("#vote button[aria-pressed=true]").waitFor();
  assert.equal(await button.textContent(), "Upvoted");
  await page.locator("#vote .papyrus-reader-count").getByText("6 upvotes").waitFor();
  assert.deepEqual(state.writes, [{ path: "/api/reader/vote", body: { subject: SUBJECT, dimension: "up", on: true } }]);
  await button.click();
  await page.locator("#vote button[aria-pressed=false]").waitFor();
  await page.locator("#vote .papyrus-reader-count").getByText("5 upvotes").waitFor();
  assert.deepEqual(state.writes[1].body, { subject: SUBJECT, dimension: "up", on: false });
  await context.close();
});

test("upvote is keyboard operable", async () => {
  const context = await browser.newContext();
  const state = fake();
  const page = await open(context, state);
  await page.locator("#vote button:not([disabled])").waitFor();
  await page.locator("#vote button").focus();
  await page.keyboard.press("Space");
  await page.locator("#vote button[aria-pressed=true][aria-busy=false]").waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.closest("#vote") !== null), true, "focus stays on the button while the write is in flight");
  await page.keyboard.press("Enter");
  await page.locator("#vote button[aria-pressed=false]").waitFor();
  assert.equal(state.writes.length, 2);
  await context.close();
});

test("a rejected vote is rolled back and says why in words, including the rate limit", async () => {
  const context = await browser.newContext();
  const state = fake();
  state.writeAnswer = () => ({ status: 429, body: { error: "rate_limited", message: "Too many actions.", retryAfter: 1800 } });
  const page = await open(context, state);
  await page.locator("#vote button:not([disabled])").waitFor();
  await page.locator("#vote button").click();
  await page.locator("#vote .papyrus-reader-status").getByText("Too many actions. Try again in about 30 minutes.").waitFor();
  assert.equal(await page.locator("#vote button").getAttribute("aria-pressed"), "false");
  await page.locator("#vote .papyrus-reader-count").getByText("5 upvotes").waitFor();
  await context.close();
});

test("a vote the server says needs a sign-in turns the controls into the signed-out state", async () => {
  const context = await browser.newContext();
  const state = fake();
  state.writeAnswer = () => ({ status: 401, body: { error: "signed_out" } });
  const page = await open(context, state);
  await page.locator("#vote button:not([disabled])").waitFor();
  await page.locator("#vote button").click();
  await page.getByRole("link", { name: "Sign in" }).waitFor();
  await page.locator("#vote .papyrus-reader-status").getByText("Sign in to vote and rate").waitFor();
  await context.close();
});

test("used it behaves like a vote on the used-it dimension", async () => {
  const context = await browser.newContext();
  const state = fake({ me: signedInMe({ votes: { [SUBJECT]: { "used-it": 1 } } }) });
  const page = await open(context, state);
  const button = page.locator("#usedit button");
  await page.locator("#usedit button[aria-pressed=true]").waitFor();
  assert.equal(await button.textContent(), "You used it");
  await button.click();
  await page.locator("#usedit button[aria-pressed=false]").waitFor();
  await page.locator("#usedit .papyrus-reader-count").getByText("1 reader used it").waitFor();
  assert.deepEqual(state.writes[0], { path: "/api/reader/vote", body: { subject: SUBJECT, dimension: "used-it", on: false } });
  await context.close();
});

test("rating: the reader's own value is optimistic and words, selecting it again clears it, and the keyboard works", async () => {
  const context = await browser.newContext();
  const state = fake({ me: signedInMe({ votes: { [SUBJECT]: { real: 2 } } }) });
  const page = await open(context, state);
  const real = page.locator("#rating [aria-label=real]");
  await real.getByText("Your rating: 2 of 5").waitFor();
  assert.equal(await real.getByRole("button", { name: "Rate real 2 of 5" }).getAttribute("aria-pressed"), "true");
  await real.getByRole("button", { name: "Rate real 4 of 5" }).click();
  await real.getByText("Your rating: 4 of 5").waitFor();
  assert.equal(await real.getByRole("button", { name: "Rate real 2 of 5" }).getAttribute("aria-pressed"), "false");
  assert.deepEqual(state.writes[0], { path: "/api/reader/rating", body: { subject: SUBJECT, dimension: "real", value: 4 } });
  await real.getByRole("button", { name: "Rate real 4 of 5" }).click();
  await real.getByText("Not rated").waitFor();
  assert.deepEqual(state.writes[1].body, { subject: SUBJECT, dimension: "real", value: null });
  const useful = page.locator("#rating [aria-label=useful]");
  await useful.getByRole("button", { name: "Rate useful 5 of 5" }).focus();
  await page.keyboard.press("Enter");
  await useful.getByText("Your rating: 5 of 5").waitFor();
  assert.deepEqual(state.writes[2].body, { subject: SUBJECT, dimension: "useful", value: 5 });
  await context.close();
});

test("the page asks /api/reader/me once for every subject on it, and the snapshot is polled while visible", async () => {
  const context = await browser.newContext();
  const state = fake();
  const page = await open(context, state, { clock: true });
  await page.locator("#vote button:not([disabled])").waitFor();
  assert.equal(state.meRequests.length, 1, "one request for all islands");
  assert.equal(state.meRequests[0], `?subjects=${SUBJECT}`);
  const before = state.snapshotRequests;
  await page.clock.fastForward(61_000);
  await page.waitForTimeout(100);
  assert.ok(state.snapshotRequests > before, "polled after 60 seconds");
  state.snapshot = snapshotAt(new Date().toISOString(), { up: 9 });
  await page.clock.fastForward(61_000);
  await page.locator("#vote .papyrus-reader-count").getByText("9 upvotes").waitFor();
  await context.close();
});

test("a newer snapshot replaces the optimistic adjustment instead of adding to it", async () => {
  const context = await browser.newContext();
  const state = fake();
  const page = await open(context, state, { clock: true });
  await page.locator("#vote button:not([disabled])").waitFor();
  await page.locator("#vote button").click();
  await page.locator("#vote .papyrus-reader-count").getByText("6 upvotes").waitFor();
  state.snapshot = snapshotAt(new Date(Date.now() + 120_000).toISOString(), { up: 6 });
  await page.clock.fastForward(61_000);
  await page.waitForTimeout(100);
  await page.locator("#vote .papyrus-reader-count").getByText("6 upvotes").waitFor();
  await context.close();
});

test("a missing snapshot leaves the prerendered numbers and the page working", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ snapshot: null }));
  await page.locator("#vote button:not([disabled])").waitFor();
  await page.locator("#vote .papyrus-reader-count").getByText("3 upvotes").waitFor();
  await context.close();
});

test("with the core islands runtime on the page each island still mounts exactly once", async () => {
  const context = await browser.newContext();
  const state = fake();
  const page = await open(context, state, { page: PAGE.replace("</head>", '<script src="/_plugins/papyrus-islands-v1.js" defer></script></head>') });
  assert.equal(await page.locator('script[src="/_plugins/papyrus-islands-v1.js"]').count(), 1, "the core runtime is on the page");
  await page.locator("#vote button:not([disabled])").waitFor();
  assert.equal(await page.locator("#vote button").count(), 1);
  assert.equal(await page.locator("#rating button").count(), 10);
  assert.equal(await page.locator("#signin .papyrus-reader-handle").count(), 1);
  await context.close();
});
