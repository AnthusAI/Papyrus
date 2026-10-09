/**
 * Newsroom sign-in return URLs: backend expansion and client ordering.
 *
 *   npx tsx scripts/test-oauth-redirect-urls.ts
 */
import assert from "node:assert/strict";
import { expandNewsroomRedirectUrls } from "../amplify/auth/redirect-urls";
import { prioritizeRedirectUrlsForOrigin } from "../lib/oauth-redirect-priority";

assert.deepEqual(
  expandNewsroomRedirectUrls(["http://localhost:3001/", "https://threat-intelligence.anth.us/", "https://threat-intelligence-staging.anth.us/"]),
  [
    "http://localhost:3001/newsroom",
    "http://localhost:3001/",
    "https://threat-intelligence.anth.us/newsroom",
    "https://threat-intelligence.anth.us/",
    "https://threat-intelligence-staging.anth.us/newsroom",
    "https://threat-intelligence-staging.anth.us/",
  ],
  "root-only origins gain a leading /newsroom variant",
);

assert.deepEqual(
  expandNewsroomRedirectUrls(["https://a.example.test"]),
  ["https://a.example.test/newsroom", "https://a.example.test/"],
  "an origin without a path counts as the root",
);

assert.deepEqual(
  expandNewsroomRedirectUrls(["https://a.example.test/", "https://a.example.test/newsroom", "https://b.example.test/newsroom"]),
  ["https://a.example.test/newsroom", "https://a.example.test/", "https://b.example.test/newsroom", "https://b.example.test/"],
  "explicit entries are kept, newsroom variant first, no duplicates",
);

assert.deepEqual(
  expandNewsroomRedirectUrls(["https://a.example.test/", "https://a.example.test/other"]),
  ["https://a.example.test/newsroom", "https://a.example.test/", "https://a.example.test/other"],
  "other explicit paths stay after the two standard variants",
);

assert.deepEqual(
  expandNewsroomRedirectUrls(["https://a.example.test/", "https://a.example.test/"]),
  ["https://a.example.test/newsroom", "https://a.example.test/"],
  "repeated entries are deduplicated",
);

assert.deepEqual(
  expandNewsroomRedirectUrls(["https://newsroom.example.test/", "http://localhost:3001/"], ""),
  ["https://newsroom.example.test/", "http://localhost:3001/"],
  "a root-mounted newsroom host gets no /newsroom variant",
);

assert.deepEqual(
  expandNewsroomRedirectUrls(["https://a.example.test/"], "/desk"),
  ["https://a.example.test/desk", "https://a.example.test/"],
  "a custom newsroom base path is honored",
);

assert.deepEqual(expandNewsroomRedirectUrls(["not a url"]), ["not a url"], "unparseable entries pass through");
assert.deepEqual(expandNewsroomRedirectUrls([]), []);

const registered = ["https://a.example.test/", "https://b.example.test/", "https://b.example.test/newsroom"];
assert.deepEqual(
  prioritizeRedirectUrlsForOrigin(registered, "https://b.example.test", "/newsroom"),
  ["https://b.example.test/newsroom", "https://b.example.test/", "https://a.example.test/"],
  "the current origin leads and its newsroom variant is first",
);
assert.deepEqual(
  prioritizeRedirectUrlsForOrigin(registered, "https://b.example.test", ""),
  ["https://b.example.test/", "https://b.example.test/newsroom", "https://a.example.test/"],
  "a root-mounted newsroom keeps the configured order",
);
assert.deepEqual(
  prioritizeRedirectUrlsForOrigin(["http://localhost:3001/", "http://localhost:3001/newsroom"], "http://127.0.0.1:3001", "/newsroom"),
  ["http://localhost:3001/newsroom", "http://localhost:3001/"],
  "loopback addresses match localhost",
);
assert.deepEqual(prioritizeRedirectUrlsForOrigin(registered, "https://c.example.test", "/newsroom"), registered, "an unlisted origin changes nothing");

console.log("oauth redirect url tests passed");
