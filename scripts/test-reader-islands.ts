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
  submissions: Array<Record<string, unknown>>;
  comments: Record<string, unknown> | null;
  writeAnswer: (path: string, body: Record<string, unknown>) => { status: number; body: Record<string, unknown> };
  holdSnapshot: Promise<void> | null;
  board: Record<string, unknown> | null;
  subjects: Record<string, unknown> | null;
  boardRequests: number;
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
    submissions: [],
    comments: null,
    writeAnswer: (path, body) => ({ status: 200, body: path === "/api/reader/handle" ? { handle: String(body.handle).toLowerCase() } : { subject: body.subject, dimension: body.dimension } }),
    holdSnapshot: null,
    board: null,
    subjects: null,
    boardRequests: 0,
    ...changes,
  };
}

async function open(context: BrowserContext, state: Fake, options: { clock?: boolean; page?: string; query?: string } = {}): Promise<Page> {
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
    if (url.pathname === "/_data/reader/comments/item-one.json") return state.comments ? json(200, state.comments) : json(404, {});
    if (url.pathname === "/_data/reader/board.json") {
      state.boardRequests += 1;
      return state.board ? json(200, state.board) : json(404, {});
    }
    if (url.pathname === "/_data/reader/subjects.json") return state.subjects ? json(200, state.subjects) : json(404, {});
    if (url.pathname === "/_data/reader/submissions.json") return json(200, { generatedAt: new Date().toISOString(), submissions: state.submissions });
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
  await page.goto(`${ORIGIN}/article.html${options.query ?? ""}`);
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

test("signed out: a Sign in button posts the way back to this page (people are never sent to an /api link) and the controls say why they are off", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: { status: 401, body: { error: "signed_out" } } }));
  const button = page.locator("#signin").getByRole("button", { name: "Sign in" });
  await button.waitFor();
  assert.equal(await page.locator("#signin a").count(), 0, "no link to /api");
  assert.equal(await page.locator("#signin form").getAttribute("method"), "post");
  assert.equal(await page.locator("#signin form").getAttribute("action"), "/api/auth/prospectus/sign-in");
  assert.equal(await page.locator('#signin input[name="returnTo"]').getAttribute("value"), "/article.html");
  await page.locator("#vote .papyrus-reader-status").getByText("Sign in to vote and rate").waitFor();
  assert.equal(await page.getByRole("button", { name: "Upvote" }).isDisabled(), true);
  await context.close();
});

test("a failed sign-in comes back with ?sign_in_error=, says so in words once, and tidies the address", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: { status: 401, body: { error: "signed_out" } } }), { query: "?x=1&sign_in_error=sign_in_declined" });
  await page.locator("#signin").getByText("Sign-in was cancelled.").waitFor();
  assert.equal(new URL(page.url()).search, "?x=1", "the error is removed from the address");
  assert.equal(await page.locator('#signin input[name="returnTo"]').getAttribute("value"), "/article.html?x=1");
  await context.close();
  const other = await browser.newContext();
  const failed = await open(other, fake({ me: { status: 401, body: { error: "signed_out" } } }), { query: "?sign_in_error=state_mismatch" });
  await failed.locator("#signin").getByText("Sign-in did not complete. Try again.").waitFor();
  await other.close();
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
  await page.locator("#signin").getByRole("button", { name: "Sign in" }).waitFor();
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
  assert.equal(await page.locator("#rating .papyrus-reader-star").count(), 10, "five stars for each of two dimensions, mounted once");
  assert.equal(await page.locator("#signin .papyrus-reader-handle").count(), 1);
  await context.close();
});

const SUBMIT_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Submit</title>
<link rel="stylesheet" href="/_plugins/papyrus-reader@1.css"><script src="/_plugins/papyrus-reader@1.js" defer></script></head><body>
<header><div id="signin" data-island="ReaderSignIn"></div></header>
<main><h1>Submit a link</h1><div id="submit" data-island="Submit" data-props='{"kinds":["article","tool"]}'><p class="papyrus-island-summary">Sign in to submit a link.</p></div></main></body></html>`;

const submitAnswer = (path: string, body: Record<string, unknown>) =>
  path === "/api/reader/submit"
    ? { status: 201, body: { subject: "sub-abc", url: body.url, title: body.title, kind: body.kind, state: "pending", extraction: "pending", similar: [] } }
    : { status: 200, body: {} };

async function fillSubmit(page: Page, url: string, title: string, note = "") {
  await page.getByLabel("Link").fill(url);
  await page.getByLabel("Title").fill(title);
  if (note) await page.getByLabel("Note (optional)").fill(note);
}

test("submit: while sign-in is not open the form is disabled and says so", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: unavailable }), { page: SUBMIT_PAGE });
  await page.locator("#submit").getByText("Reader sign-in is not open yet").waitFor();
  for (const control of await page.locator("#submit input, #submit textarea, #submit button").all()) assert.equal(await control.isDisabled(), true);
  assert.equal(await page.locator("#submit .papyrus-island-summary").count(), 0);
  await context.close();
});

test("submit: a signed-out visitor sees why the form is off", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake({ me: { status: 401, body: { error: "signed_out" } } }), { page: SUBMIT_PAGE });
  await page.locator("#submit").getByText("Sign in to vote and rate").waitFor();
  assert.equal(await page.getByRole("button", { name: "Submit link" }).isDisabled(), true);
  await context.close();
});

test("submit: the form posts the link, the title, the kind and the note, then says the link is pending and clears the saved draft", async () => {
  const context = await browser.newContext();
  const state = fake({ writeAnswer: (path, body) => path === "/api/reader/submit" ? { status: 201, body: { subject: "sub-abc", url: body.url, title: body.title, kind: body.kind, state: "pending", extraction: "pending", similar: [{ subject: "sub-old", url: "https://example.com/older", title: "<b>Older</b> post" }] } } : { status: 200, body: {} } });
  const page = await open(context, state, { page: SUBMIT_PAGE });
  await page.getByRole("button", { name: "Submit link" }).waitFor();
  await page.getByLabel("Link").waitFor({ state: "visible" });
  await page.waitForFunction(() => !(document.querySelector("#submit input") as HTMLInputElement).disabled);
  await fillSubmit(page, "https://example.com/post#top", "A small tool", "Worked well for me");
  await page.getByLabel("tool").check();
  await page.getByRole("button", { name: "Submit link" }).click();
  await page.locator("#submit").getByText("Pending \u2014 we\u2019re reading the link.").waitFor();
  assert.deepEqual(state.writes, [{ path: "/api/reader/submit", body: { url: "https://example.com/post#top", title: "A small tool", kind: "tool", note: "Worked well for me" } }]);
  await page.locator("#submit .papyrus-reader-similar a").getByText("<b>Older</b> post").waitFor();
  assert.equal(await page.locator("#submit .papyrus-reader-similar b").count(), 0, "titles are text, never markup");
  assert.equal(await page.getByLabel("Link").inputValue(), "");
  assert.equal(await page.evaluate(() => window.localStorage.getItem("papyrus-reader-submit-draft")), null);
  await context.close();
});

test("submit: a draft is saved locally, says so, and comes back after a reload", async () => {
  const context = await browser.newContext();
  const page = await open(context, fake(), { page: SUBMIT_PAGE });
  await page.locator("#submit").getByText(/Saved locally/).waitFor();
  await page.waitForFunction(() => !(document.querySelector("#submit input") as HTMLInputElement).disabled);
  await fillSubmit(page, "https://example.com/draft", "Half written", "Not done");
  await page.waitForFunction(() => window.localStorage.getItem("papyrus-reader-submit-draft") !== null);
  assert.deepEqual(JSON.parse((await page.evaluate(() => window.localStorage.getItem("papyrus-reader-submit-draft"))) as string), { url: "https://example.com/draft", title: "Half written", note: "Not done", kind: "article" });
  await page.reload();
  await page.waitForFunction(() => (document.querySelector("#submit input") as HTMLInputElement | null)?.value === "https://example.com/draft");
  assert.equal(await page.getByLabel("Title").inputValue(), "Half written");
  assert.equal(await page.getByLabel("Note (optional)").inputValue(), "Not done");
  await context.close();
});

test("submit: storage that throws leaves the form working", async () => {
  const context = await browser.newContext();
  await context.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
  });
  const state = fake({ writeAnswer: submitAnswer });
  const page = await open(context, state, { page: SUBMIT_PAGE });
  await page.waitForFunction(() => !(document.querySelector("#submit input") as HTMLInputElement).disabled);
  await fillSubmit(page, "https://example.com/x", "Works without storage");
  await page.getByRole("button", { name: "Submit link" }).click();
  await page.locator("#submit").getByText(/^Pending/).waitFor();
  await context.close();
});

test("submit: a link that is already listed, or a recent one from the same site, shows a warning before submitting", async () => {
  const context = await browser.newContext();
  const recent = new Date(Date.now() - 3600_000).toISOString();
  const state = fake({ submissions: [{ id: "sub-1", url: "https://example.com/listed", domain: "example.com", title: "Listed already", createdAt: recent }, { id: "sub-2", url: "https://news.example/old", domain: "news.example", title: "Old", createdAt: new Date(Date.now() - 72 * 3600_000).toISOString() }] });
  const page = await open(context, state, { page: SUBMIT_PAGE });
  await page.waitForFunction(() => !(document.querySelector("#submit input") as HTMLInputElement).disabled);
  await page.getByLabel("Link").fill("HTTPS://Example.com:443/listed#section");
  await page.locator("#submit .papyrus-reader-warning").getByText(/may already be submitted as .Listed already./).waitFor();
  await page.getByLabel("Link").fill("https://example.com/another");
  await page.locator("#submit .papyrus-reader-warning").getByText(/1 link from example.com was submitted in the last 48 hours/).waitFor();
  await page.getByLabel("Link").fill("https://news.example/new");
  assert.equal(await page.locator("#submit .papyrus-reader-warning").textContent(), "", "a link older than 48 hours is not a warning");
  assert.equal(state.writes.length, 0, "a warning never blocks or posts");
  await context.close();
});

test("submit: the server's duplicate, rate limit and handle answers are shown in words", async () => {
  const context = await browser.newContext();
  const answers: Array<{ status: number; body: Record<string, unknown> }> = [
    { status: 409, body: { error: "duplicate_submission", message: "That link was already submitted.", existing: { subject: "sub-1", url: "https://example.com/x", title: "The first one", state: "pending" } } },
    { status: 429, body: { error: "rate_limited", message: "Too many actions.", retryAfter: 7200 } },
    { status: 422, body: { error: "handle_required", message: "Choose a handle before submitting a link." } },
    { status: 422, body: { error: "invalid_url", message: "Send the link as an http or https address." } },
  ];
  const page = await open(context, fake({ writeAnswer: () => answers.shift()! }), { page: SUBMIT_PAGE });
  await page.waitForFunction(() => !(document.querySelector("#submit input") as HTMLInputElement).disabled);
  await fillSubmit(page, "https://example.com/x", "Try");
  const send = page.getByRole("button", { name: "Submit link" });
  await send.click();
  await page.locator("#submit .papyrus-reader-status").getByText(/Already submitted as .The first one. \(pending\)/).waitFor();
  await send.click();
  await page.locator("#submit .papyrus-reader-status").getByText("Too many actions. Try again in about 120 minutes.").waitFor();
  await send.click();
  await page.locator("#submit .papyrus-reader-status").getByText(/Choose a handle first/).waitFor();
  await send.click();
  await page.locator("#submit .papyrus-reader-status").getByText("Send the link as an http or https address.").waitFor();
  assert.equal(await page.getByLabel("Link").inputValue(), "https://example.com/x", "a refused submission keeps what was typed");
  await context.close();
});

const COMMENTS_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Comments</title>
<link rel="stylesheet" href="/_plugins/papyrus-reader@1.css"><script src="/_plugins/papyrus-reader@1.js" defer></script></head><body>
<header><div id="signin" data-island="ReaderSignIn"></div></header>
<main><h1>An item</h1><div id="comments" data-island="Comments" data-props='{"subject":"${SUBJECT}","count":3}'><p class="papyrus-island-summary">3 comments</p></div></main></body></html>`;

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const commentFile = (comments: Array<Record<string, unknown>>) => ({ generatedAt: new Date().toISOString(), subject: SUBJECT, comments });
const OTHER = ["00000000", "0000", "0000", "0000", "000000000009"].join("-");
const entry = (id: string, body: string, changes: Record<string, unknown> = {}) => ({ id, readerId: OTHER, handle: "loud-owl", body, createdAt: minutesAgo(120), parent: null, edited: false, ...changes });

test("comments: a thread is shown as text with handles, edited marks and removed stubs, and markup never runs", async () => {
  const context = await browser.newContext();
  const state = fake({
    comments: commentFile([
      entry("cmt-1", "<img src=x onerror=window.pwned=1> first"),
      entry("cmt-2", "A reply", { parent: "cmt-1", handle: "plain-cat", edited: true }),
      { id: "cmt-3", stub: true, parent: null, createdAt: minutesAgo(100) },
      entry("cmt-4", "Reply to a removed one", { parent: "cmt-3" }),
    ]),
  });
  const page = await open(context, state, { page: COMMENTS_PAGE });
  await page.locator("#comments .papyrus-reader-comment-count").getByText("3 comments").waitFor();
  await page.locator("#comments .papyrus-reader-comment-body").getByText("<img src=x onerror=window.pwned=1> first").waitFor();
  assert.equal(await page.locator("#comments img").count(), 0);
  assert.equal(await page.evaluate(() => (window as unknown as { pwned?: number }).pwned), undefined);
  await page.locator("#comments .papyrus-reader-replies").getByText("A reply").waitFor();
  await page.locator("#comments").getByText(/plain-cat . 2 hours ago \(edited\)/).waitFor();
  await page.locator("#comments").getByText("This comment was removed.").waitFor();
  assert.equal(await page.locator("#comments .papyrus-reader-comment-removed + .papyrus-reader-replies, #comments [data-comment-id=cmt-3] .papyrus-reader-replies").count() > 0, true, "a reply under a removed comment stays attached");
  await page.locator("#comments .papyrus-reader-comment-count").getByText("3 comments").waitFor();
  assert.equal(await page.locator("#comments .papyrus-island-summary").count(), 0);
  await context.close();
});

test("comments: while sign-in is not open, or signed out, the form is off and says why", async () => {
  for (const [me, text] of [[unavailable, "Reader sign-in is not open yet"], [{ status: 401, body: { error: "signed_out" } }, "Sign in to vote and rate"]] as const) {
    const context = await browser.newContext();
    const page = await open(context, fake({ me, comments: commentFile([entry("cmt-1", "Hello")]) }), { page: COMMENTS_PAGE });
    await page.locator("#comments .papyrus-reader-status").getByText(text).waitFor();
    assert.equal(await page.getByRole("button", { name: "Post comment" }).isDisabled(), true);
    assert.equal(await page.getByLabel("Add a comment").isDisabled(), true);
    assert.equal(await page.getByRole("button", { name: "Reply", exact: true }).count(), 0, "no Reply buttons while the controls are off");
    await context.close();
  }
});

test("comments: posting shows the comment at once, clears the box and counts the characters left", async () => {
  const context = await browser.newContext();
  const state = fake({
    comments: commentFile([entry("cmt-1", "First")]),
    writeAnswer: (path, body) => ({ status: 201, body: { id: "cmt-new", subject: body.subject, parent: body.parent ?? null, body: String(body.body).trim(), createdAt: new Date().toISOString(), ratingContext: null } }),
  });
  const page = await open(context, state, { page: COMMENTS_PAGE });
  await page.locator("#comments").getByText("First").waitFor();
  const box = page.getByLabel("Add a comment");
  await page.waitForFunction(() => !(document.querySelector("#comments textarea") as HTMLTextAreaElement).disabled);
  await page.locator("#comments").getByText("2000 characters left").waitFor();
  await box.fill("Hello there");
  await page.locator("#comments").getByText("1989 characters left").waitFor();
  assert.equal(await box.getAttribute("maxlength"), "2000");
  await page.getByRole("button", { name: "Post comment" }).click();
  await page.locator("#comments .papyrus-reader-comment-body").getByText("Hello there").waitFor();
  await page.locator("#comments").getByText(/quiet-fox . just now/).waitFor();
  assert.equal(await box.inputValue(), "");
  assert.deepEqual(state.writes, [{ path: "/api/reader/comment", body: { subject: SUBJECT, body: "Hello there" } }]);
  await page.locator("#comments .papyrus-reader-comment-count").getByText("2 comments").waitFor();
  await context.close();
});

test("comments: a reply goes under its parent, and only top-level comments can be replied to", async () => {
  const context = await browser.newContext();
  const state = fake({
    comments: commentFile([entry("cmt-1", "Top"), entry("cmt-2", "Nested", { parent: "cmt-1" })]),
    writeAnswer: (path, body) => ({ status: 201, body: { id: "cmt-new", subject: body.subject, parent: body.parent ?? null, body: body.body, createdAt: new Date().toISOString(), ratingContext: null } }),
  });
  const page = await open(context, state, { page: COMMENTS_PAGE });
  await page.locator("#comments").getByText("Nested").waitFor();
  await page.waitForFunction(() => document.querySelectorAll("#comments button").length > 0);
  assert.equal(await page.getByRole("button", { name: "Reply", exact: true }).count(), 1, "the nested comment has no Reply button");
  await page.getByRole("button", { name: "Reply", exact: true }).click();
  await page.getByLabel("Your reply").fill("My answer");
  await page.getByRole("button", { name: "Post reply" }).click();
  await page.locator("#comments .papyrus-reader-replies").getByText("My answer").waitFor();
  assert.deepEqual(state.writes, [{ path: "/api/reader/comment", body: { subject: SUBJECT, body: "My answer", parent: "cmt-1" } }]);
  await context.close();
});

test("comments: a typed reply survives the page refreshing its numbers", async () => {
  const context = await browser.newContext();
  const state = fake({ comments: commentFile([entry("cmt-1", "Top")]) });
  const page = await open(context, state, { page: COMMENTS_PAGE, clock: true });
  await page.getByRole("button", { name: "Reply", exact: true }).waitFor();
  await page.getByRole("button", { name: "Reply", exact: true }).click();
  await page.getByLabel("Your reply").fill("Half a thought");
  await page.getByRole("button", { name: "Reply", exact: true }).focus();
  await page.clock.runFor(61_000);
  assert.equal(await page.getByLabel("Your reply").inputValue(), "Half a thought");
  await context.close();
});

test("comments: the author edits within ten minutes and deletes, and both show at once", async () => {
  const context = await browser.newContext();
  const state = fake({
    comments: commentFile([
      entry("cmt-mine", "Mine, new", { readerId: READER_ID, handle: "quiet-fox", createdAt: minutesAgo(2) }),
      entry("cmt-old", "Mine, old", { readerId: READER_ID, handle: "quiet-fox", createdAt: minutesAgo(30) }),
      entry("cmt-theirs", "Theirs", { createdAt: minutesAgo(1) }),
    ]),
    writeAnswer: (path, body) => ({ status: 200, body: path === "/api/reader/comment/edit" ? { id: body.id, body: body.body } : { id: body.id, state: "deleted" } }),
  });
  const page = await open(context, state, { page: COMMENTS_PAGE });
  await page.locator('[data-comment-id="cmt-theirs"]').waitFor();
  await page.waitForFunction(() => document.querySelectorAll("#comments button").length > 3);
  assert.equal(await page.locator('[data-comment-id="cmt-mine"]').getByRole("button", { name: "Edit" }).count(), 1);
  assert.equal(await page.locator('[data-comment-id="cmt-old"]').getByRole("button", { name: "Edit" }).count(), 0, "the window is ten minutes");
  assert.equal(await page.locator('[data-comment-id="cmt-theirs"]').getByRole("button", { name: "Delete" }).count(), 0, "not the author");
  await page.locator('[data-comment-id="cmt-mine"]').getByRole("button", { name: "Edit" }).click();
  const box = page.getByLabel("Edit your comment");
  assert.equal(await box.inputValue(), "Mine, new");
  await box.fill("Mine, better");
  await page.getByRole("button", { name: "Save" }).click();
  await page.locator('[data-comment-id="cmt-mine"] .papyrus-reader-comment-body').getByText("Mine, better").waitFor();
  await page.locator('[data-comment-id="cmt-mine"]').getByText(/\(edited\)/).waitFor();
  await page.locator('[data-comment-id="cmt-old"]').getByRole("button", { name: "Delete" }).click();
  await page.locator('[data-comment-id="cmt-old"]').getByText("This comment was removed.").waitFor();
  assert.deepEqual(state.writes, [
    { path: "/api/reader/comment/edit", body: { id: "cmt-mine", body: "Mine, better" } },
    { path: "/api/reader/comment/delete", body: { id: "cmt-old" } },
  ]);
  await context.close();
});

test("comments: refusals are shown in words", async () => {
  const context = await browser.newContext();
  const answers: Array<{ status: number; body: Record<string, unknown> }> = [
    { status: 429, body: { error: "rate_limited", message: "Too many actions.", retryAfter: 600 } },
    { status: 422, body: { error: "too_many_links", message: "A comment has at most 3 links." } },
    { status: 422, body: { error: "handle_required", message: "Choose a handle before commenting." } },
  ];
  const page = await open(context, fake({ comments: commentFile([]), writeAnswer: () => answers.shift()! }), { page: COMMENTS_PAGE });
  await page.waitForFunction(() => !(document.querySelector("#comments textarea") as HTMLTextAreaElement).disabled);
  await page.getByLabel("Add a comment").fill("Try");
  const send = page.getByRole("button", { name: "Post comment" });
  await send.click();
  await page.locator("#comments .papyrus-reader-comment-main .papyrus-reader-status").getByText("Too many actions. Try again in about 10 minutes.").waitFor();
  await send.click();
  await page.locator("#comments .papyrus-reader-comment-main .papyrus-reader-status").getByText("A comment has at most 3 links.").waitFor();
  await send.click();
  await page.locator("#comments .papyrus-reader-comment-main .papyrus-reader-status").getByText("Choose a handle before commenting.").waitFor();
  assert.equal(await page.getByLabel("Add a comment").inputValue(), "Try", "a refused comment keeps what was typed");
  await context.close();
});

test("rating: after rating, a public rationale can be posted with the rating it explains", async () => {
  const context = await browser.newContext();
  const state = fake({
    writeAnswer: (path, body) => path === "/api/reader/comment" ? { status: 201, body: { id: "cmt-new", subject: body.subject, parent: null, body: body.body, createdAt: new Date().toISOString(), ratingContext: body.ratingContext } } : { status: 200, body: { subject: body.subject, dimension: body.dimension, value: body.value } },
  });
  const page = await open(context, state);
  const why = page.getByLabel("Why? (optional, public)");
  await page.waitForFunction(() => !(document.querySelector("#rating button") as HTMLButtonElement).disabled);
  assert.equal(await why.count(), 2, "one hidden prompt per dimension");
  assert.equal(await page.locator("#rating .papyrus-reader-why:visible").count(), 0, "no prompt before a rating");
  await page.getByRole("button", { name: "Rate real 4 of 5" }).click();
  await page.locator("#rating .papyrus-reader-why:visible").waitFor();
  assert.equal(await page.locator("#rating .papyrus-reader-why:visible").count(), 1);
  await page.locator("#rating .papyrus-reader-why:visible input").fill("The benchmarks held up.");
  await page.getByRole("button", { name: "Post reason" }).click();
  await page.locator("#rating").getByText("Posted. It shows in the comments with the next update.").waitFor();
  assert.deepEqual(state.writes.map((write) => [write.path, write.body]), [
    ["/api/reader/rating", { subject: SUBJECT, dimension: "real", value: 4 }],
    ["/api/reader/comment", { subject: SUBJECT, body: "The benchmarks held up.", ratingContext: { dimension: "real", value: 4 } }],
  ]);
  await page.getByRole("button", { name: "Rate real 4 of 5" }).click();
  await page.waitForFunction(() => document.querySelectorAll("#rating .papyrus-reader-why:not([hidden])").length === 0);
  await context.close();
});

test("report: another reader's comment can be reported with a reason, your own cannot", async () => {
  const context = await browser.newContext();
  const state = fake({
    comments: commentFile([entry("cmt-theirs", "Buy my thing"), entry("cmt-mine", "Mine", { readerId: READER_ID, handle: "quiet-fox", createdAt: minutesAgo(30) })]),
    writeAnswer: () => ({ status: 200, body: { reported: true } }),
  });
  const page = await open(context, state, { page: COMMENTS_PAGE });
  await page.locator('[data-comment-id="cmt-theirs"]').getByRole("button", { name: "Report" }).waitFor();
  assert.equal(await page.locator('[data-comment-id="cmt-mine"]').getByRole("button", { name: "Report" }).count(), 0);
  await page.locator('[data-comment-id="cmt-theirs"]').getByRole("button", { name: "Report" }).click();
  await page.getByLabel("Why are you reporting this?").fill("An advert");
  await page.getByRole("button", { name: "Send report" }).click();
  await page.locator('[data-comment-id="cmt-theirs"]').getByText("Reported. A moderator will look at it.").waitFor();
  assert.deepEqual(state.writes, [{ path: "/api/reader/report", body: { target: "cmt-theirs", reason: "An advert" } }]);
  await context.close();
});

test("report: the Report island reports a submission and is off while sign-in is not open", async () => {
  const page_ = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>R</title>
<link rel="stylesheet" href="/_plugins/papyrus-reader@1.css"><script src="/_plugins/papyrus-reader@1.js" defer></script></head><body>
<header><div id="signin" data-island="ReaderSignIn"></div></header><main><div id="report" data-island="Report" data-props='{"target":"sub-0123456789abcdef01234567"}'></div></main></body></html>`;
  let context = await browser.newContext();
  const state = fake({ writeAnswer: () => ({ status: 200, body: { reported: true } }) });
  let page = await open(context, state, { page: page_ });
  await page.waitForFunction(() => !(document.querySelector("#report button") as HTMLButtonElement).disabled);
  await page.getByRole("button", { name: "Report" }).click();
  await page.getByLabel("Why are you reporting this?").fill("Spam");
  await page.getByLabel("Why are you reporting this?").press("Enter");
  await page.locator("#report").getByText("Reported. A moderator will look at it.").waitFor();
  assert.deepEqual(state.writes, [{ path: "/api/reader/report", body: { target: "sub-0123456789abcdef01234567", reason: "Spam" } }]);
  await context.close();
  context = await browser.newContext();
  page = await open(context, fake({ me: unavailable }), { page: page_ });
  await page.locator("#signin").getByText("Reader sign-in is not open yet").waitFor();
  assert.equal(await page.getByRole("button", { name: "Report" }).isDisabled(), true);
  await context.close();
});

test("a held submission or comment is shown as held for review, not as public", async () => {
  const context = await browser.newContext();
  const heldSubmit = fake({ writeAnswer: (path, body) => ({ status: 201, body: { subject: "sub-abc", url: body.url, title: body.title, kind: body.kind, state: "held", extraction: "pending", similar: [] } }) });
  const page = await open(context, heldSubmit, { page: SUBMIT_PAGE });
  await page.waitForFunction(() => !(document.querySelector("#submit input") as HTMLInputElement).disabled);
  await fillSubmit(page, "https://example.com/held", "Held one");
  await page.getByRole("button", { name: "Submit link" }).click();
  await page.locator("#submit").getByText("Held for review \u2014 a moderator reads it before it is public.").waitFor();
  assert.equal(await page.locator("#submit").getByText(/Pending/).count(), 0);
  await context.close();

  const context2 = await browser.newContext();
  const heldComment = fake({
    comments: commentFile([]),
    writeAnswer: (path, body) => ({ status: 201, body: { id: "cmt-held", subject: body.subject, parent: null, body: body.body, createdAt: new Date().toISOString(), ratingContext: null, state: "held" } }),
  });
  const page2 = await open(context2, heldComment, { page: COMMENTS_PAGE });
  await page2.waitForFunction(() => !(document.querySelector("#comments textarea") as HTMLTextAreaElement).disabled);
  await page2.getByLabel("Add a comment").fill("Waiting");
  await page2.getByRole("button", { name: "Post comment" }).click();
  await page2.locator("#comments").getByText(/held for review, only you can see it/).waitFor();
  await context2.close();
});

const RANKED_PAGE = (props: Record<string, unknown>) => `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Rising</title>
<link rel="stylesheet" href="/_plugins/papyrus-reader@1.css"><script src="/_plugins/papyrus-reader@1.js" defer></script></head><body>
<main><h1>Rising</h1><div id="ranked" data-island="RankedList" data-props='${JSON.stringify(props)}'><p class="papyrus-island-summary">Prerendered</p></div></main></body></html>`;

const boardAt = (generatedAt: string, changes: Record<string, unknown> = {}) => ({
  generatedAt,
  parameters: { risingWindowHours: 6 },
  front: [{ subject: "a", score: 2.957, editor: 3, reader: 3.5, readerN: 2, ageHours: 1 }, { subject: "b", score: 1.5, editor: 2, reader: null, readerN: 0, ageHours: 4 }],
  rising: [{ subject: "b", upvotes: 3 }, { subject: "sub-1", upvotes: 1 }, { subject: "a", upvotes: 1 }, { subject: "gone", upvotes: 1 }],
  new: [{ subject: "sub-1", kind: "submission", at: minutesAgo(5) }, { subject: "a", kind: "item", at: minutesAgo(125) }],
  ...changes,
});
const subjectsAt = (generatedAt: string) => ({
  generatedAt,
  subjects: {
    a: { kind: "item", title: "Alpha tool", url: "/tools/alpha.html", section: "tools", date: "2026-10-20" },
    b: { kind: "item", title: "Beta post", url: "/news/beta.html", section: "news", date: "2026-10-21" },
    "sub-1": { kind: "submission", state: "pending", title: "Linked <b>thing</b>", url: "https://example.com/thing", domain: "example.com", section: null, date: "2026-10-22" },
  },
});
const rankedState = (board: Record<string, unknown> = {}) => fake({ board: boardAt(minutesAgo(7), board), subjects: subjectsAt(minutesAgo(7)) });

test("ranked list: rising is a real ordered list with the rank as text, the figure in words, a Pending submission and an update stamp", async () => {
  const context = await browser.newContext();
  const page = await open(context, rankedState(), { page: RANKED_PAGE({ list: "rising", empty: "Nothing is rising yet." }) });
  const rows = page.locator("#ranked ol > li");
  await rows.first().waitFor();
  assert.equal(await page.locator("#ranked ol").count(), 1);
  assert.equal(await rows.count(), 3, "a row whose subject is not in the index is left out");
  assert.match((await rows.nth(0).innerText()).replace(/\s+/g, " "), /^1\. Beta post news 3 upvotes in 6 h$/);
  assert.match((await rows.nth(1).innerText()).replace(/\s+/g, " "), /^2\. Linked <b>thing<\/b> example\.com Pending 1 upvote in 6 h$/, "titles are text, a submission says Pending and shows its domain");
  assert.equal(await rows.nth(0).getByRole("link", { name: "Beta post" }).getAttribute("href"), "/news/beta.html");
  const external = rows.nth(1).getByRole("link");
  assert.equal(await external.getAttribute("href"), "https://example.com/thing");
  assert.match((await external.getAttribute("rel")) ?? "", /nofollow/);
  assert.equal(await page.locator("#ranked b").count(), 0);
  assert.equal(await page.locator("#ranked .papyrus-island-summary").count(), 0, "the prerendered summary is replaced");
  await page.locator("#ranked").getByText("Updated 7 min ago").waitFor();
  await context.close();
});

test("ranked list: front shows the labelled score, new shows time and Pending, limit and section narrow the list", async () => {
  const context = await browser.newContext();
  const front = await open(context, rankedState(), { page: RANKED_PAGE({ list: "front", limit: 1 }) });
  await front.locator("#ranked ol > li").first().waitFor();
  assert.equal(await front.locator("#ranked ol > li").count(), 1);
  assert.match((await front.locator("#ranked ol > li").innerText()).replace(/\s+/g, " "), /^1\. Alpha tool tools Score 2\.96$/);
  await context.close();

  const context2 = await browser.newContext();
  const news = await open(context2, rankedState(), { page: RANKED_PAGE({ list: "new" }) });
  await news.locator("#ranked ol > li").first().waitFor();
  const text = (await news.locator("#ranked ol > li").allInnerTexts()).map((row) => row.replace(/\s+/g, " "));
  assert.match(text[0], /^1\. Linked <b>thing<\/b> example\.com Pending 5 min ago$/);
  assert.match(text[1], /^2\. Alpha tool tools 2 h ago$/);
  await context2.close();

  const context3 = await browser.newContext();
  const section = await open(context3, rankedState(), { page: RANKED_PAGE({ list: "rising", section: "news" }) });
  await section.locator("#ranked ol > li").first().waitFor();
  assert.deepEqual((await section.locator("#ranked ol > li .papyrus-reader-ranked-title").allInnerTexts()), ["Beta post"]);
  await context3.close();
});

test("ranked list: an empty list says the empty text at full strength, and a failed load says so", async () => {
  const context = await browser.newContext();
  const page = await open(context, rankedState({ rising: [] }), { page: RANKED_PAGE({ list: "rising", empty: "Nothing is rising yet." }) });
  const empty = page.locator("#ranked").getByText("Nothing is rising yet.");
  await empty.waitFor();
  assert.equal(await page.locator("#ranked ol").count(), 0);
  assert.equal(await empty.evaluate((node) => getComputedStyle(node).opacity), "1");
  await context.close();

  const context2 = await browser.newContext();
  const broken = await open(context2, fake(), { page: RANKED_PAGE({ list: "rising", empty: "Nothing is rising yet." }) });
  await broken.locator("#ranked").getByText("This list could not be loaded. Try again later.").waitFor();
  assert.equal(await broken.locator("#ranked").getByText("Nothing is rising yet.").count(), 0, "a failure is not shown as an empty list");
  await context2.close();
});

test("ranked list: it polls every minute while the page is visible and keeps the old rows when a poll fails", async () => {
  const context = await browser.newContext();
  const state = rankedState();
  const page = await open(context, state, { page: RANKED_PAGE({ list: "rising" }), clock: true });
  await page.locator("#ranked ol > li").first().waitFor();
  const first = state.boardRequests;
  state.board = boardAt(new Date().toISOString(), { rising: [{ subject: "a", upvotes: 9 }] });
  await page.clock.fastForward(61_000);
  await page.locator("#ranked").getByText("9 upvotes in 6 h").waitFor();
  assert.ok(state.boardRequests > first);
  state.board = null;
  await page.clock.fastForward(61_000);
  await page.locator("#ranked").getByText("9 upvotes in 6 h").waitFor();
  assert.equal(await page.locator("#ranked").getByText("could not be loaded").count(), 0);
  await context.close();
});
