import assert from "node:assert/strict";
import { fetchSourceIcon, iconCandidates, isHostName } from "../lib/source-icon";

void (async () => {
  const html = `<head>
    <link rel="shortcut icon" href="/favicon.ico">
    <link rel="icon" type="image/png" sizes="32x32" href="/icons/32.png">
    <link rel='icon' sizes=192x192 href='https://cdn.example.org/icons/192.png'>
    <link rel="mask-icon" href="/pinned.svg" color="#000">
    <link rel="apple-touch-icon" href="touch.png">
    <link rel="stylesheet" href="/site.css">
  </head>`;
  assert.deepEqual(iconCandidates(html, "https://www.example.org/en/"), [
    "https://www.example.org/en/touch.png",
    "https://cdn.example.org/icons/192.png",
    "https://www.example.org/icons/32.png",
    "https://www.example.org/favicon.ico",
  ], "touch icon first, then the largest declared size; mask icons and stylesheets are skipped; relative links resolve against the page");
  assert.deepEqual(iconCandidates("<p>no icons</p>", "https://example.org/"), []);

  for (const host of ["www.brookings.edu", "arxiv.org", "unit42.paloaltonetworks.com"]) assert.equal(isHostName(host), true, `${host} is a host`);
  for (const host of ["localhost", "127.0.0.1", "169.254.169.254", "example.org/path", "user@example.org", "example.org:8443", "", "a..b"]) {
    assert.equal(isHostName(host), false, `${host} is refused`);
    assert.equal(await fetchSourceIcon(host), null, `${host} is never fetched`);
  }

  // With no declared icon, the guessed /favicon.ico is used only when it is bigger than an empty 16x16 placeholder.
  const realFetch = globalThis.fetch;
  for (const [bytes, expected] of [[198, false], [1200, true]] as const) {
    globalThis.fetch = (async (input: URL | RequestInfo) => {
      const url = new URL(String(input));
      return url.pathname === "/favicon.ico"
        ? new Response(new Uint8Array(bytes), { headers: { "content-type": "image/x-icon" } })
        : new Response("<html><head><title>No icons</title></head></html>", { headers: { "content-type": "text/html" } });
    }) as typeof fetch;
    const icon = await fetchSourceIcon("example.com");
    assert.equal(icon !== null, expected, `a ${bytes}-byte /favicon.ico is ${expected ? "used" : "skipped"}`);
  }
  globalThis.fetch = realFetch;
  console.log("source icon check: ok");
})();
