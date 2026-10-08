/**
 * Markus brands must not enumerate Next.js reader routes.
 *
 *   npx tsx scripts/test-reader-static-params.ts
 */
import {
  generateArticleStaticParams,
  generateEditionDateStaticParams,
  siteEnumeratesReaderRoutesAtBuild,
  siteServesNextReaderRoutes,
} from "../lib/reader-static-params";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

async function main() {
  assert(siteServesNextReaderRoutes("pretext"), "pretext sites serve Next reader routes");
  assert(!siteServesNextReaderRoutes("markus"), "markus sites do not serve Next reader routes");

  assert(siteServesNextReaderRoutes(), "reference brand serves Next reader routes");

  assert(siteEnumeratesReaderRoutesAtBuild(), "published content source enumerates reader routes at build");

  process.env.PAPYRUS_CONTENT_SOURCE = "drafts";
  assert(!siteEnumeratesReaderRoutesAtBuild(), "drafts content source (staging) must not enumerate routes at build, cookies() is request-only");
  assert((await generateEditionDateStaticParams()).length === 0, "drafts: no edition date params and no cookie-reading repository call at build");
  assert((await generateArticleStaticParams()).length === 0, "drafts: no article params and no cookie-reading repository call at build");
  delete process.env.PAPYRUS_CONTENT_SOURCE;

  console.log("PASS: reader static params");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
