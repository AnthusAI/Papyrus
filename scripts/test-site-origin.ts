import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { SiteOriginNotConfiguredError, publicSiteOrigin, publicSiteUrl } from "../lib/site-origin";

const at = (origin: string, headers: Record<string, string> = {}) => new NextRequest(new URL("/x", origin), { headers });
const adapter = at("https://localhost:3000");

// Configured: the public origin wins over whatever the request says.
assert.equal(publicSiteOrigin(adapter, { PAPYRUS_SITE_ORIGIN: "https://p.apyr.us", SITE_ENV: "production" }), "https://p.apyr.us");
assert.equal(publicSiteOrigin(at("http://localhost:3001"), { PAPYRUS_SITE_ORIGIN: " https://p.apyr.us " }), "https://p.apyr.us", "configuration beats the loopback fallback");
assert.equal(publicSiteOrigin(adapter, { PAPYRUS_SITE_ORIGIN: "https://staging.example.com:8443" }), "https://staging.example.com:8443");

// Request headers never supply the origin.
assert.equal(publicSiteOrigin(at("https://localhost:3000", { host: "evil.example", "x-forwarded-host": "evil.example" }), { PAPYRUS_SITE_ORIGIN: "https://p.apyr.us" }), "https://p.apyr.us");
assert.throws(() => publicSiteOrigin(at("https://p.apyr.us", { "x-forwarded-host": "p.apyr.us" }), { SITE_ENV: "production" }), SiteOriginNotConfiguredError, "a public-looking request is not trusted in production");

// Invalid configuration fails closed.
for (const bad of ["http://p.apyr.us", "https://p.apyr.us/", "https://p.apyr.us/newsroom", "https://p.apyr.us?x=1", "p.apyr.us", "https://p.apyr.us#fragment"]) {
  assert.throws(() => publicSiteOrigin(adapter, { PAPYRUS_SITE_ORIGIN: bad, SITE_ENV: "development" }), SiteOriginNotConfiguredError, `rejects ${bad}`);
}

// Unset: loopback fallback is development only.
for (const origin of ["http://localhost:3001", "https://localhost:3000", "http://127.0.0.1:3001", "http://[::1]:3001"]) {
  const requestOrigin = at(origin).nextUrl.origin; // Next normalizes 127.0.0.1 to localhost
  assert.equal(publicSiteOrigin(at(origin), {}), requestOrigin, `${origin} falls back in development`);
  assert.equal(publicSiteOrigin(at(origin), { SITE_ENV: "development" }), requestOrigin);
  for (const siteEnv of ["production", "staging"]) assert.throws(() => publicSiteOrigin(at(origin), { SITE_ENV: siteEnv }), SiteOriginNotConfiguredError, `${origin} in ${siteEnv}`);
}
assert.throws(() => publicSiteOrigin(adapter, { NODE_ENV: "production" }), SiteOriginNotConfiguredError, "a production build whose runtime never received SITE_ENV does not fall back");
assert.throws(() => publicSiteOrigin(adapter, { SITE_ENV: "production", AWS_BRANCH: "staging" }), SiteOriginNotConfiguredError, "a staging branch of a production app does not fall back");
assert.throws(() => publicSiteOrigin(adapter, { SITE_ENV: "bogus" }), SiteOriginNotConfiguredError, "an invalid SITE_ENV fails closed");
assert.throws(() => publicSiteOrigin(at("https://localhost.evil.example"), {}), SiteOriginNotConfiguredError, "only real loopback hosts fall back");
assert.throws(() => publicSiteOrigin(at("https://example.com"), {}), SiteOriginNotConfiguredError, "a non-loopback request origin is never used");

const error = (() => { try { publicSiteOrigin(adapter, { SITE_ENV: "production" }); } catch (caught) { return caught as SiteOriginNotConfiguredError; } })();
assert.equal(error?.status, 503);
assert.equal(error?.code, "site_origin_not_configured");
assert.equal(publicSiteUrl("/newsroom?x=1", adapter, { PAPYRUS_SITE_ORIGIN: "https://p.apyr.us" }).toString(), "https://p.apyr.us/newsroom?x=1", "redirect URLs are built on the public origin");
assert.throws(() => publicSiteUrl("/", adapter, { SITE_ENV: "production" }), SiteOriginNotConfiguredError);
console.log("site origin: ok");
