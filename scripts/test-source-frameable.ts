import assert from "node:assert/strict";
import { frameableFromHeaders, isPrivateAddress, publicHttpUrl } from "../lib/source-frameable";

const headers = (entries: Record<string, string>) => new Headers(entries);

void (async () => {
  assert.equal(frameableFromHeaders(headers({})), true, "no rule: frameable");
  assert.equal(frameableFromHeaders(headers({ "x-frame-options": "DENY" })), false);
  assert.equal(frameableFromHeaders(headers({ "x-frame-options": "SAMEORIGIN" })), false);
  assert.equal(frameableFromHeaders(headers({ "content-security-policy": "default-src 'self'; frame-ancestors 'self'" })), false);
  assert.equal(frameableFromHeaders(headers({ "content-security-policy": "frame-ancestors https://partner.example" })), false, "a named origin is not us");
  assert.equal(frameableFromHeaders(headers({ "content-security-policy": "frame-ancestors *" })), true);
  assert.equal(frameableFromHeaders(headers({ "content-security-policy": "default-src 'self'" })), true, "no frame-ancestors directive");

  for (const address of ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.199", "169.254.169.254", "100.64.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1"]) {
    assert.equal(isPrivateAddress(address), true, `${address} is private`);
  }
  for (const address of ["93.184.215.14", "8.8.8.8", "2606:4700::1111"]) assert.equal(isPrivateAddress(address), false, `${address} is public`);

  for (const raw of ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "https://example.com:8443/", "ftp://example.com/", "https://user:pw@example.com/", "not a url"]) {
    assert.equal(await publicHttpUrl(raw), null, `${raw} is refused`);
  }
  console.log("source frameable check: ok");
})();
