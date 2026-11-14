import assert from "node:assert/strict";
import test from "node:test";
import { allowedOrigins, isAllowedOrigin } from "../lib/allowed-origins";

const site = "https://shipped.anth.us";
const console_ = "https://newsroom.shipped.anth.us";

test("the console origin is accepted when configured", () => {
  const environment = { PAPYRUS_CONSOLE_ORIGIN: console_ };
  assert.equal(isAllowedOrigin(console_, site, environment), true);
  assert.equal(isAllowedOrigin(site, site, environment), true);
});

test("a foreign origin is still refused", () => {
  const environment = { PAPYRUS_CONSOLE_ORIGIN: console_ };
  for (const origin of ["https://evil.example", "https://shipped.anth.us.evil.example", "https://other.shipped.anth.us", "http://newsroom.shipped.anth.us", "null", "", null]) {
    assert.equal(isAllowedOrigin(origin, site, environment), false, String(origin));
  }
  assert.equal(isAllowedOrigin("https://x.anth.us", site, { PAPYRUS_CONSOLE_ORIGIN: "https://*.anth.us" }), false);
});

test("without a console origin only the site origin is accepted", () => {
  for (const environment of [{}, { PAPYRUS_CONSOLE_ORIGIN: "" }, { PAPYRUS_CONSOLE_ORIGIN: "  " }]) {
    assert.deepEqual(allowedOrigins(site, environment), [site]);
    assert.equal(isAllowedOrigin(site, site, environment), true);
    assert.equal(isAllowedOrigin(console_, site, environment), false);
  }
});

test("a malformed console origin widens nothing", () => {
  for (const bad of ["newsroom.shipped.anth.us", "https://newsroom.shipped.anth.us/path", "http://newsroom.shipped.anth.us", "not a url"]) {
    assert.deepEqual(allowedOrigins(site, { PAPYRUS_CONSOLE_ORIGIN: bad }), [site]);
  }
});
