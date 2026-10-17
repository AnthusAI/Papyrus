/**
 * Markus brands must not enumerate Next.js reader routes.
 *
 *   npx tsx scripts/test-reader-static-params.ts
 */
import {
  generateArticleStaticParams,
  generateEditionDateStaticParams,
  generateEditionItemStaticParams,
  generateEditionPageStaticParams,
  generateEditionSectionStaticParams,
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
  assert((await generateEditionItemStaticParams()).length === 0, "drafts: no item params");
  assert((await generateEditionPageStaticParams()).length === 0, "drafts: no page params");
  assert((await generateEditionSectionStaticParams()).length === 0, "drafts: no section params");
  delete process.env.PAPYRUS_CONTENT_SOURCE;

  const stubContent = (editionDate: string) => ({
    editionDate,
    items: [{ slug: "first-story" }, { slug: "page" }, { slug: "second-story" }],
    layoutPlan: { pages: [{}, {}, {}] },
    sections: [{ key: "analysis" }, { key: "briefs" }],
  });
  const stubRepository = {
    listPublishedEditions: async () => ({ editions: [{ editionDate: "2026-07-04" }, { editionDate: "2026-07-12" }], nextToken: undefined }),
    loadEditionContent: async (options?: { editionDate?: string }) => stubContent(options?.editionDate ?? "") as never,
  } as never;

  const dateParams = await generateEditionDateStaticParams(stubRepository);
  assert(dateParams.some((param) => param.day === "04" && param.month === "july"), "edition date params use the canonical zero-padded day");
  assert(!dateParams.some((param) => param.day === "4"), "no unpadded day param that only redirects");

  const itemParams = await generateEditionItemStaticParams(stubRepository);
  assert(itemParams.length === 4, "two editions times two non-reserved items");
  assert(itemParams.every((param) => param.day.length === 2), "item params use the canonical day");
  assert(!itemParams.some((param) => param.articleSlug === "page"), "reserved date child segments are not item params");

  const pageParams = await generateEditionPageStaticParams(stubRepository);
  assert(pageParams.length === 4 && pageParams.every((param) => param.pageNumber !== "1"), "pages 2..N per edition, page 1 is the edition route");

  const sectionParams = await generateEditionSectionStaticParams(stubRepository);
  assert(sectionParams.length === 4, "one param per section per edition");

  console.log("PASS: reader static params");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
