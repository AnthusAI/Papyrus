import assert from "node:assert/strict";
import { test } from "node:test";
import {
  SHARE_HEADERS,
  SHARE_TOKEN_PATTERN,
  mediaResponse,
  parseMediaAnswer,
  parseShareAnswer,
  shareResponse,
  signInPathFor,
  unavailableResponse,
} from "../lib/story-share-view";
import {
  DEFAULT_SHARE_EXPIRY_DAYS,
  SHARE_EXPIRY_DAYS,
  StoryShareFailure,
  createStoryShareClient,
  describeShown,
  describeState,
  describeViewers,
  shareUrl,
  type StoryShareTransport,
} from "../lib/story-share-client";
import { createDemoStoryShareClient } from "../lib/story-share-demo";
import { toPublicNewsroomPath } from "../lib/newsroom-base-path";

const TOKEN = "A".repeat(43);

async function snapshot(response: Response) {
  return { status: response.status, headers: Object.fromEntries([...response.headers.entries()].sort()), body: await response.text() };
}

test("a token has exactly the shape of 256 random bits", async () => {
  // The token shape: exactly what a 256-bit URL-safe token looks like, nothing else is looked up.
  assert.ok(SHARE_TOKEN_PATTERN.test(TOKEN));
  for (const bad of ["", "a", "A".repeat(42), "A".repeat(44), `${"A".repeat(42)}/`, `${"A".repeat(41)}..`, `${"A".repeat(40)}%2e%2e`, "../".repeat(20), `${"A".repeat(42)}\n`, "é".repeat(43)]) {
    assert.equal(SHARE_TOKEN_PATTERN.test(bad), false, JSON.stringify(bad));
  }

});

test("every answer of a share route carries the three headers", async () => {
  const reference = await snapshot(unavailableResponse());
  // Every response from a share route carries the three headers.
  const answers = [
    shareResponse({ state: "ok", html: "<p>draft</p>" }, { signInPath: "/x" }),
    shareResponse({ state: "unavailable" }, { signInPath: "/x" }),
    shareResponse({ state: "sign-in" }, { signInPath: "/newsroom/share/t" }),
    shareResponse({ state: "published", address: "https://example.org/a/" }, { signInPath: "/x" }),
    unavailableResponse(),
  ];
  for (const response of answers) {
    for (const [name, value] of Object.entries(SHARE_HEADERS)) assert.equal(response.headers.get(name), value, `${response.status} ${name}`);
  }
  assert.equal(SHARE_HEADERS["X-Robots-Tag"], "noindex, nofollow");
  assert.equal(SHARE_HEADERS["Cache-Control"], "no-store");
  assert.equal(SHARE_HEADERS["Referrer-Policy"], "no-referrer");

});

test("an unknown, expired, revoked or malformed link is one and the same page", async () => {
  const reference = await snapshot(unavailableResponse());
  // Unknown, expired, revoked and every malformed answer are one and the same page.
  assert.equal(reference.status, 404);
  assert.match(reference.body, /This link is not available/);
  for (const raw of [null, undefined, "", "not json", "[]", 7, { state: "unavailable" }, { state: "expired" }, { state: "revoked" }, { state: "ok" }, { state: "ok", html: "" }, { state: "ok", html: 5 }, { state: "surprise", html: "<p>x</p>" }, JSON.stringify({ state: "nope" })]) {
    assert.deepEqual(await snapshot(shareResponse(parseShareAnswer(raw), { signInPath: "/x" })), reference, JSON.stringify(raw));
  }
  assert.ok(!/revoked|expired|unknown|no such/i.test(reference.body.replace(/<style>.*<\/style>/s, "")));

});

test("a page passes through, signing in redirects, and the published notice links only to https", async () => {
  const reference = await snapshot(unavailableResponse());
  // A page is passed through untouched; sign in is a redirect that carries no page; the published notice links only to an https address.
  const page = await snapshot(shareResponse(parseShareAnswer(JSON.stringify({ state: "ok", html: "<p>draft</p>" })), { signInPath: "/x" }));
  assert.deepEqual([page.status, page.body, page.headers["content-type"]], [200, "<p>draft</p>", "text/html; charset=utf-8"]);
  const signIn = shareResponse(parseShareAnswer({ state: "sign-in" }), { signInPath: signInPathFor(TOKEN, toPublicNewsroomPath) });
  assert.equal(signIn.status, 302);
  assert.equal(signIn.headers.get("location"), `/newsroom/share/${TOKEN}`);
  assert.equal(await signIn.text(), "");
  const notice = await snapshot(shareResponse(parseShareAnswer({ state: "published", address: "https://example.org/essays/a/" }), { signInPath: "/x" }));
  assert.match(notice.body, /href="https:\/\/example\.org\/essays\/a\/"/);
  assert.match(notice.body, /DRAFT|draft/);
  for (const address of ["javascript:alert(1)", "//evil.example", 'https://x.org/"><script>', "http://x.org/", 5, null]) {
    assert.equal((parseShareAnswer({ state: "published", address }) as { address: string | null }).address, null, String(address));
  }

});

test("pictures are served only when approved, only as images, and never as something a browser could run", async () => {
  const reference = await snapshot(unavailableResponse());
  const signed: string[] = [];
  const fetched: string[] = [];
  // Media: only what the function approved, only images, nothing a browser could run.
  assert.deepEqual(parseMediaAnswer({ state: "ok", source: "media", storagePath: "media/assets/a/b.png" }), { state: "ok", source: "media", storagePath: "media/assets/a/b.png" });
  for (const raw of [{ state: "ok", source: "media", storagePath: "media/../secret.png" }, { state: "ok", source: "media", storagePath: "newsroom/payloads/x.png" }, { state: "ok", source: "media", storagePath: "corpora/x" },
    { state: "ok", source: "site", url: "http://example.org/x.png" }, { state: "ok", source: "site", url: "javascript:alert(1)" }, { state: "ok", source: "site", url: "file:///etc/passwd" }, { state: "ok", source: "other", url: "https://x.org/a.png" },
    { state: "unavailable" }, null, "x", 5]) {
    assert.deepEqual(parseMediaAnswer(raw), { state: "unavailable" }, JSON.stringify(raw));
  }
  const dependencies = (upstream: Response) => ({
    signStorageUrl: async (path: string) => { signed.push(path); return `https://bucket.example/${path}?signed`; },
    fetchUpstream: async (url: string) => { fetched.push(url); return upstream; },
  });
  const image = await mediaResponse({ state: "ok", source: "site", url: "https://example.org/assets/a.webp" }, dependencies(new Response("bytes", { headers: { "content-type": "image/webp" } })));
  assert.equal(image.status, 200);
  assert.equal(image.headers.get("content-type"), "image/webp");
  assert.equal(image.headers.get("x-content-type-options"), "nosniff");
  assert.equal(image.headers.get("content-security-policy"), "default-src 'none'; sandbox");
  for (const [name, value] of Object.entries(SHARE_HEADERS)) assert.equal(image.headers.get(name), value);
  assert.deepEqual(fetched, ["https://example.org/assets/a.webp"]);
  const original = await mediaResponse({ state: "ok", source: "media", storagePath: "media/assets/a/b.png" }, dependencies(new Response("png", { headers: { "content-type": "image/png" } })));
  assert.equal(original.status, 200);
  assert.deepEqual(signed, ["media/assets/a/b.png"]);
  for (const hostile of [new Response("<script>alert(1)</script>", { headers: { "content-type": "text/html" } }), new Response("{}", { headers: { "content-type": "application/json" } }), new Response("x"), new Response("", { status: 404, headers: { "content-type": "image/png" } })]) {
    assert.deepEqual(await snapshot(await mediaResponse({ state: "ok", source: "site", url: "https://example.org/x" }, dependencies(hostile))), reference);
  }
  assert.deepEqual(await snapshot(await mediaResponse({ state: "unavailable" }, dependencies(new Response("never")))), reference);
  assert.deepEqual(
    await snapshot(await mediaResponse({ state: "ok", source: "media", storagePath: "media/x.png" }, { signStorageUrl: async () => { throw new Error("denied"); }, fetchUpstream: async () => new Response("") })),
    reference,
  );
  const svg = await mediaResponse({ state: "ok", source: "site", url: "https://example.org/x.svg" }, dependencies(new Response("<svg/>", { headers: { "content-type": "image/svg+xml" } })));
  assert.equal(svg.headers.get("content-security-policy"), "default-src 'none'; sandbox"); // an SVG opened by itself cannot run script

});

test("the expiry is a choice of 7, 30 or 90 days and the client asks the newsroom to create, list and revoke", async () => {
  const share = { shareId: "abc", viewers: "anyone", version: "current", createdAt: "2026-11-04T12:00:00Z", createdBy: "Ed", expiresAt: "2026-12-04T12:00:00Z", state: "active", endedReason: null, lastOpenedOn: null, openCount: 0 };
  // The client: the expiry is a choice of 7, 30 or 90 with 30 the default, and "never" does not exist.
  assert.deepEqual([...SHARE_EXPIRY_DAYS], [7, 30, 90]);
  assert.equal(DEFAULT_SHARE_EXPIRY_DAYS, 30);
  const sent: Record<string, unknown>[] = [];
  const respond = (value: unknown) => async (args: { input: string }) => { sent.push(JSON.parse(args.input)); return { data: JSON.stringify(value) }; };
  const transport: StoryShareTransport = {
    mutations: { createStoryShare: respond({ ok: true, path: `/api/share/${TOKEN}`, share }), revokeStoryShare: respond({ ok: true, share: { ...share, state: "revoked" } }) },
    queries: { listStoryShares: respond({ ok: true, shares: [share] }) },
  };
  const client = createStoryShareClient(transport);
  const made = await client.create({ lineageId: "l1", viewers: "signed-in", version: 3, expiresInDays: 7 });
  assert.deepEqual(sent[0], { lineageId: "l1", viewers: "signed-in", expiresInDays: 7, version: 3 });
  assert.equal(made.path, `/api/share/${TOKEN}`);
  await client.create({ lineageId: "l1", viewers: "anyone", version: null, expiresInDays: 30 });
  assert.deepEqual(sent[1], { lineageId: "l1", viewers: "anyone", expiresInDays: 30 }); // no version: it follows the current one
  assert.equal((await client.list("l1"))[0].shareId, "abc");
  assert.equal((await client.revoke("l1", "abc")).state, "revoked");
  const refusing = createStoryShareClient({ ...transport, mutations: { ...transport.mutations, createStoryShare: respond({ ok: false, errors: [{ message: "Only editors and admins can share a draft." }] }) } });
  await assert.rejects(refusing.create({ lineageId: "l1", viewers: "anyone", expiresInDays: 30 }), (error: unknown) => error instanceof StoryShareFailure && /Only editors and admins/.test(error.message));
  assert.equal(shareUrl("https://console.example.org/", `/api/share/${TOKEN}`), `https://console.example.org/api/share/${TOKEN}`);
  assert.equal(describeViewers("anyone"), "Anyone with the link");
  assert.equal(describeShown(2), "Version 2 only");
  assert.equal(describeShown("current"), "Current version, follows new versions");
  assert.equal(describeState({ state: "ended", endedReason: "published" }), "Ended: the Story was published");

});

test("the local preview stand-in makes, lists and revokes links", async () => {
  // The demo stand-in for the local preview behaves like the real thing: a link, a list, a revoke.
  const demo = createDemoStoryShareClient(() => new Date("2026-11-04T12:00:00Z"));
  const demoMade = await demo.create({ lineageId: "l", viewers: "anyone", expiresInDays: 90 });
  assert.equal(demoMade.share.expiresAt, "2027-02-02T12:00:00Z");
  assert.equal((await demo.list("l")).length, 1);
  assert.equal((await demo.revoke("l", demoMade.share.shareId)).state, "revoked");

});

