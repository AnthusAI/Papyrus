/**
 * Reader base path: default output is unchanged, `/information` prefixes every reader path.
 *
 *   npx tsx scripts/test-reader-base-path.ts
 */
import { readFileSync } from "node:fs";
import {
  getEditionArticlePath,
  getEditionDatePath,
  getEditionPagePath,
  getEditionSectionPath,
  parseEditionArticleRoute,
  parseEditionDateRoute,
  parseEditionPageRoute,
  parseEditionSectionRoute,
} from "../lib/edition-routes";
import { PRESENTATION_FOOTER_UTILITIES } from "../lib/presentation-footer";
import {
  getReaderBasePath,
  normalizeReaderBasePath,
  toInternalReaderPath,
  toPublicReaderPath,
} from "../lib/reader-base-path";
import { papyrusUriToWebPath, webPathToPapyrusLocation } from "../lib/papyrus-web-locations";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

function assertEqual(actual: unknown, expected: unknown, message: string) {
  assert(actual === expected, `${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

const INFO = "/information";

assertEqual(getReaderBasePath(), "", "default brand has no reader base path");
assertEqual(normalizeReaderBasePath(undefined), "", "undefined normalizes to empty");
assertEqual(normalizeReaderBasePath("information/"), "/information", "leading slash added, trailing removed");
assertEqual(normalizeReaderBasePath("/"), "", "root normalizes to empty");

assertEqual(toPublicReaderPath("/archive"), "/archive", "default public path unchanged");
assertEqual(toPublicReaderPath("/"), "/", "default home unchanged");
assertEqual(toPublicReaderPath("/archive", INFO), "/information/archive", "prefixed archive");
assertEqual(toPublicReaderPath("/", INFO), "/information", "prefixed home");
assertEqual(toInternalReaderPath("/information/archive", INFO), "/archive", "strip prefix");
assertEqual(toInternalReaderPath("/information", INFO), "/", "strip prefix home");
assertEqual(toInternalReaderPath("/newsroom/x", INFO), "/newsroom/x", "newsroom path untouched");

assertEqual(getEditionDatePath("2026-10-07"), "/2026/october/07", "default edition date path");
assertEqual(getEditionDatePath("bad"), "/", "default invalid date path");
assertEqual(getEditionPagePath("2026-10-07", 1), "/2026/october/07", "default page 1");
assertEqual(getEditionPagePath("2026-10-07", 3), "/2026/october/07/page/3", "default page 3");
assertEqual(getEditionSectionPath("2026-10-07", "a b"), "/2026/october/07/section/a%20b", "default section");
assertEqual(getEditionArticlePath("2026-10-07", "slug"), "/2026/october/07/slug", "default article");
const defaultRoute = parseEditionArticleRoute({ year: "2026", month: "October", day: "7", articleSlug: "slug" });
assert(defaultRoute && !defaultRoute.isCanonical && defaultRoute.canonicalPath === "/2026/october/07/slug", "default non-canonical route");

assertEqual(getEditionDatePath("2026-10-07", INFO), "/information/2026/october/07", "prefixed edition date path");
assertEqual(getEditionDatePath("bad", INFO), "/information", "prefixed invalid date path");
assertEqual(getEditionPagePath("2026-10-07", 1, INFO), "/information/2026/october/07", "prefixed page 1");
assertEqual(getEditionPagePath("2026-10-07", 3, INFO), "/information/2026/october/07/page/3", "prefixed page 3");
assertEqual(getEditionSectionPath("2026-10-07", "a b", INFO), "/information/2026/october/07/section/a%20b", "prefixed section");
assertEqual(getEditionArticlePath("2026-10-07", "slug", INFO), "/information/2026/october/07/slug", "prefixed article");

const dateRoute = parseEditionDateRoute({ year: "2026", month: "October", day: "7" }, INFO);
assert(dateRoute && !dateRoute.isCanonical && dateRoute.canonicalPath === "/information/2026/october/07", "prefixed non-canonical date route");
const canonicalDate = parseEditionDateRoute({ year: "2026", month: "october", day: "07" }, INFO);
assert(canonicalDate && canonicalDate.isCanonical, "prefixed canonical date route");
const pageRoute = parseEditionPageRoute({ year: "2026", month: "october", day: "07", pageNumber: "2" }, INFO);
assert(pageRoute && pageRoute.isCanonical && pageRoute.canonicalPath === "/information/2026/october/07/page/2", "prefixed page route");
const articleRoute = parseEditionArticleRoute({ year: "2026", month: "october", day: "07", articleSlug: "slug" }, INFO);
assert(articleRoute && articleRoute.isCanonical && articleRoute.canonicalPath === "/information/2026/october/07/slug", "prefixed article route");
const sectionRoute = parseEditionSectionRoute({ year: "2026", month: "October", day: "07", sectionKey: "world" }, INFO);
assert(sectionRoute && !sectionRoute.isCanonical && sectionRoute.canonicalPath === "/information/2026/october/07/section/world", "prefixed section route");

const footerHrefs = PRESENTATION_FOOTER_UTILITIES.map((entry) => ("href" in entry ? entry.href : ""));
assert(footerHrefs.includes("/archive") && footerHrefs.includes("/settings") && footerHrefs.includes("/newsroom"), "default footer hrefs unchanged");

assertEqual(papyrusUriToWebPath("papyrus://site/archive").webPath, "/archive", "default archive web path");
assertEqual(papyrusUriToWebPath("papyrus://site/home").webPath, "/", "default home web path");
assertEqual(papyrusUriToWebPath("papyrus://item/slug").webPath, "/articles/slug", "default item web path");
assertEqual(webPathToPapyrusLocation("/archive").papyrusLocationUri, "papyrus://site/archive", "default archive location");

const revalidateSource = readFileSync(new URL("../app/api/revalidate/route.ts", import.meta.url), "utf8");
assert(!/revalidatePath\("\/archive"\)/.test(revalidateSource), "revalidate archive path goes through the helper");
assert(revalidateSource.includes('toPublicReaderPath("/archive")'), "revalidate uses toPublicReaderPath for archive");
assert(revalidateSource.includes("toPublicReaderPath(`/articles/"), "revalidate uses toPublicReaderPath for articles");
assert(readFileSync(new URL("../components/settings-page.tsx", import.meta.url), "utf8").includes('toPublicReaderPath("/")'), "settings home link uses helper");

console.log("reader base path tests passed");
