/**
 * Newsroom path helpers on a CMS-only host (newsroomBasePath "") and on a default host.
 *
 *   PAPYRUS_SITE_BRAND=pilobol-us npx tsx scripts/test-newsroom-root-paths.ts
 *   npx tsx scripts/test-newsroom-root-paths.ts
 */
import assert from "node:assert/strict";

async function run() {
  const base = await import("../lib/newsroom-base-path");
  const nav = await import("../lib/newsroom-nav");
  const filters = await import("../lib/newsroom-index-filters");
  const forum = await import("../lib/newsroom-forum-routes");
  const drilldown = await import("../lib/newsroom-category-drilldown");
  const graph = await import("../lib/semantic-graph");
  const gate = await import("../lib/staging-gated-path");

  const atRoot = base.usesNewsroomRootPaths();
  const prefix = atRoot ? "" : "/newsroom";
  const home = atRoot ? "/" : "/newsroom";

  assert.equal(base.newsroomHref(), home);
  assert.equal(base.newsroomHref("articles"), `${prefix}/articles`);
  assert.equal(nav.getNewsroomNavHref("/newsroom/assignments", true), `${prefix}/assignments?demo=1`);
  assert.equal(nav.getNewsroomNavHref("/newsroom?item=a"), atRoot ? "/?item=a" : "/newsroom?item=a");
  assert.equal(base.toPublicNewsroomPath("/newsroom?object=x#y"), atRoot ? "/?object=x#y" : "/newsroom?object=x#y");
  assert.equal(filters.buildNewsroomIndexWebPath("references", { status: "all", processing: "all", order: "published" }).startsWith(`${prefix}/references`), true);
  assert.equal(forum.buildNewsroomInsightsIndexUrl(true), `${prefix}/insights?demo=1`);
  assert.equal(forum.buildNewsroomForumIndexUrl(true), atRoot ? "/?demo=1" : "/newsroom?demo=1");
  assert.equal(drilldown.topicHref("root"), `${prefix}/topics/root`);
  assert.equal(graph.newsDeskHrefForSemanticObject("reference", "r1"), `${prefix}/references/r1`);
  assert.equal(graph.newsDeskHrefForSemanticObject("item", "i1"), atRoot ? "/?item=i1" : "/newsroom?item=i1");

  const browserReferencePath = `${prefix}/references/ref%201`;
  assert.equal(filters.parseReferenceLineageIdFromNewsroomPathname(browserReferencePath), "ref 1");
  assert.equal(filters.parseAssignmentIdFromNewsroomPathname(`${prefix}/assignments/a1`), "a1");
  assert.equal(filters.parseInsightThreadIdFromNewsroomPathname(`${prefix}/insights/t1`), "t1");
  assert.equal(filters.parseAssignmentIdFromNewsroomPathname(`${prefix}/assignments`), null);

  assert.equal(base.browserPathToInternalNewsroomPath(atRoot ? "/" : "/newsroom"), "/newsroom");
  assert.equal(base.browserPathToInternalNewsroomPath(`${prefix}/articles`), "/newsroom/articles");

  assert.equal(gate.isStagingGatedPath("/articles", "", atRoot), !atRoot);
  assert.equal(gate.isStagingGatedPath("/", "", atRoot), !atRoot);

  console.log(`newsroom root path tests passed (${atRoot ? "root" : "default"} base path)`);
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
