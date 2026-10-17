/**
 * Staging gate paths and site locations with a reader base path.
 *
 *   npx tsx scripts/test-staging-gated-path.ts
 */
import { isStagingGatedPath } from "../lib/staging-gated-path";
import { webPathToPapyrusLocation, papyrusUriToWebPath } from "../lib/papyrus-web-locations";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) throw new Error(`FAIL: ${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

for (const [path, gated] of [
  ["/", true],
  ["/archive", true],
  ["/2026/october/07", true],
  ["/pricing", true],
  ["/newsroom", false],
  ["/newsroom/assignments", false],
  ["/api/revalidate", false],
  ["/robots.txt", false],
  ["/_next/static/x.js", false],
  ["/favicon.ico", false],
] as const) {
  assertEqual(isStagingGatedPath(path), gated, `default gate for ${path}`);
  assertEqual(isStagingGatedPath(path, ""), gated, `empty base gate for ${path}`);
}

for (const [path, gated] of [
  ["/", false],
  ["/pricing", false],
  ["/information", true],
  ["/information/", true],
  ["/information/archive", true],
  ["/information/2026/october/07", true],
  ["/informationx", false],
  ["/newsroom", false],
  ["/newsroom/sections", false],
  ["/api/revalidate", false],
  ["/robots.txt", false],
] as const) {
  assertEqual(isStagingGatedPath(path, "/information"), gated, `/information gate for ${path}`);
}
assertEqual(isStagingGatedPath("/information/x", "information/"), true, "base path is normalized");

assertEqual(webPathToPapyrusLocation("/pricing").papyrusLocationUri, "papyrus://site/path/pricing", "site path location");
assertEqual(papyrusUriToWebPath("papyrus://site/path/pricing").webPath, "/pricing", "site path web path is unprefixed");
assertEqual(
  papyrusUriToWebPath("papyrus://site/path/newsroom%2Fassignments").webPath,
  "/newsroom/assignments",
  "newsroom path locations stay unprefixed",
);

console.log("staging gated path tests passed");
