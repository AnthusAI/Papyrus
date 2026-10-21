/**
 * Middleware behavior on a CMS-only host: newsroom at "/", legacy /newsroom redirects, staging never gates.
 *
 *   PAPYRUS_SITE_BRAND=pilobol-us SITE_ENV=staging npx tsx scripts/test-newsroom-root-middleware.ts
 */
import assert from "node:assert/strict";
process.env.PAPYRUS_SITE_BRAND = "pilobol-us";
process.env.SITE_ENV = "staging";
process.env.PAPYRUS_SITE_ORIGIN = "https://newsroom.example.test";
import { NextRequest } from "next/server";

async function run() {
  const { middleware } = await import("../middleware");
  const origin = "https://newsroom.example.test";

  const rewritten = await middleware(new NextRequest(`${origin}/articles?code=abc&state=xyz`));
  assert.equal(rewritten.headers.get("x-middleware-rewrite"), `${origin}/newsroom/articles?code=abc&state=xyz`);
  assert.equal(rewritten.headers.get("location"), null);

  const home = await middleware(new NextRequest(`${origin}/?code=abc&state=xyz`));
  assert.equal(home.headers.get("location"), null);
  assert.equal(home.headers.get("x-middleware-rewrite"), null);

  const legacyHome = await middleware(new NextRequest(`${origin}/newsroom`));
  assert.equal(legacyHome.headers.get("location"), `${origin}/`);

  const legacyHomeWithOAuthReturn = await middleware(new NextRequest(`${origin}/newsroom?code=abc&state=xyz`));
  assert.equal(legacyHomeWithOAuthReturn.headers.get("location"), `${origin}/?code=abc&state=xyz`);

  const legacyDeep = await middleware(new NextRequest(`${origin}/newsroom/references/r1?code=abc&state=xyz`));
  assert.equal(legacyDeep.headers.get("location"), `${origin}/references/r1?code=abc&state=xyz`);

  const staged = await middleware(new NextRequest(`${origin}/references`));
  assert.equal(staged.status, 200);
  assert.equal(staged.headers.get("location"), null, "anonymous staging requests must not bounce on a CMS-only host");
  assert.equal(staged.headers.get("x-robots-tag"), "noindex, nofollow");

  // Amplify SSR: the request URL is the compute adapter's localhost; redirects land on the public host.
  const adapter = "https://localhost:3000";
  const behindAdapter = await middleware(new NextRequest(`${adapter}/newsroom/references/r1?code=abc`));
  assert.equal(behindAdapter.headers.get("location"), `${origin}/references/r1?code=abc`, "legacy redirect uses the public origin");
  assert.equal((await middleware(new NextRequest(`${adapter}/newsroom`))).headers.get("location"), `${origin}/`);

  // Fails closed without a public origin instead of redirecting to localhost.
  delete process.env.PAPYRUS_SITE_ORIGIN;
  const closed = await middleware(new NextRequest(`${adapter}/newsroom/references`));
  assert.equal(closed.status, 503);
  assert.equal(closed.headers.get("location"), null);
  assert.equal((await closed.json()).error, "site_origin_not_configured");
  // Requests that never redirect are unaffected.
  assert.equal((await middleware(new NextRequest(`${adapter}/references`))).status, 200);

  process.env.PAPYRUS_SITE_ORIGIN = origin;
  console.log("newsroom root middleware tests passed");
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
