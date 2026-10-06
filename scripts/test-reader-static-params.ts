/**
 * Markus brands must not enumerate Next.js reader routes.
 *
 *   npx tsx scripts/test-reader-static-params.ts
 */
import {
  generateArticleStaticParams,
  generateEditionDateStaticParams,
  siteServesNextReaderRoutes,
} from "../lib/reader-static-params";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

async function main() {
  assert(siteServesNextReaderRoutes("pretext"), "pretext sites serve Next reader routes");
  assert(!siteServesNextReaderRoutes("markus"), "markus sites do not serve Next reader routes");

  assert(siteServesNextReaderRoutes(), "reference brand serves Next reader routes");

  console.log("PASS: reader static params");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
