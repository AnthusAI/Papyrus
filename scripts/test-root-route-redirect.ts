/**
 * Unit tests for the root-route redirect target and the root page wiring.
 *
 *   npx tsx scripts/test-root-route-redirect.ts
 */
import { readFileSync } from "node:fs";
import { buildRootRedirectTarget } from "../lib/root-route-redirect";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

assert(buildRootRedirectTarget("/newsroom", undefined) === "/newsroom", "no query leaves destination unchanged");
assert(buildRootRedirectTarget("/newsroom", {}) === "/newsroom", "empty query leaves destination unchanged");
assert(
  buildRootRedirectTarget("/newsroom", { code: "abc", state: "xyz" }) === "/newsroom?code=abc&state=xyz",
  "OAuth code and state are preserved",
);
assert(
  buildRootRedirectTarget("/newsroom", { error: "access_denied", error_description: "a b" })
    === "/newsroom?error=access_denied&error_description=a+b",
  "OAuth error params are preserved and encoded",
);
assert(
  buildRootRedirectTarget("/newsroom", { tag: ["a", "b"] }) === "/newsroom?tag=a&tag=b",
  "repeated params are preserved",
);
assert(
  buildRootRedirectTarget("/newsroom?x=1", { code: "abc" }) === "/newsroom?x=1&code=abc",
  "destination that already has a query is extended",
);

const pageSource = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
assert(
  !/rootRoute\.kind === "redirect"[^\n]*(scenarioId|hasOAuthRedirectParams)/.test(pageSource),
  "redirect root is unconditional, including OAuth callbacks",
);
assert(
  pageSource.indexOf("notFound()") !== -1
    && pageSource.indexOf("notFound()") < pageSource.indexOf("getSiteRenderer()"),
  "Markus brands reach notFound before the Pretext renderer is resolved",
);

console.log("PASS: root-route redirect tests");
