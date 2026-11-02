import assert from "node:assert/strict";
import { STORY_ITEM_TYPES, isStoryItemType, storyItemTypeFilter, type ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import { projectContentItemBoard } from "../lib/newsroom-board";
import { collectFilteredPage, type FilteredPage } from "../lib/story-stage-paging";

/** A DynamoDB index partition as the board's query sees it: newest first, `limit` rows read per request, the filter applied after the read. */
function fakePartition(rows: ContentItemVersionRecord[]) {
  const requests: number[] = [];
  const fetchPage = async (nextToken: string | null, scanLimit: number): Promise<FilteredPage<ContentItemVersionRecord>> => {
    const start = nextToken ? Number(nextToken) : 0;
    const end = Math.min(start + scanLimit, rows.length);
    requests.push(end - start);
    const filter = storyItemTypeFilter() as { type?: { eq: string }; or?: Array<{ type: { eq: string } }> };
    const allowed = new Set((filter.or ?? [filter]).map(clause => clause.type!.eq));
    return { items: rows.slice(start, end).filter(row => allowed.has(row.type)), nextToken: end < rows.length ? String(end) : null };
  };
  return { fetchPage, requests };
}

const version = (id: string, type: string, stage: string, status = "draft"): ContentItemVersionRecord => (
  { id, lineageId: id, versionNumber: 1, stage, type, status, title: id, slug: id, updatedAt: "2026-11-01" }
);
const scenario = process.argv[2] ?? "all";
const runs: Record<string, () => Promise<void>> = {
  async types() {
    assert.deepEqual([...STORY_ITEM_TYPES], ["article", "post"], "articles and posts are the story types");
    assert.equal(isStoryItemType("article"), true);
    assert.equal(isStoryItemType("post"), true);
    for (const type of ["wiki_page", "doctrine", "page", "", null, undefined]) assert.equal(isStoryItemType(type as string), false, `${String(type)} is not a story`);
    assert.deepEqual(storyItemTypeFilter(), { or: [{ type: { eq: "article" } }, { type: { eq: "post" } }] }, "the query filter names the story types");
  },
  async copywriting() {
    const issues = projectContentItemBoard({ contentItemVersions: [version("wiki-1", "wiki_page", "copywriting"), version("story-1", "article", "copywriting")] });
    assert.deepEqual(issues.map(issue => issue.nativeId), ["story-1"], "an article is on the board and a wiki page in Copywriting is not");
  },
  async published() {
    const issues = projectContentItemBoard({ contentItemVersions: [
      version("wiki-1", "wiki_page", "published", "published"), version("doctrine-1", "doctrine", "published", "published"),
      version("page-1", "page", "published", "published"), version("story-1", "article", "published", "published"),
    ] });
    assert.deepEqual(issues.map(issue => issue.nativeId), ["story-1"], "only the published article is a Published story");
  },
  async counts() {
    const versions = [
      ...Array.from({ length: 40 }, (_, index) => version(`wiki-${index}`, "wiki_page", index % 2 ? "copywriting" : "published", index % 2 ? "draft" : "published")),
      version("doctrine-1", "doctrine", "copywriting"),
      ...Array.from({ length: 3 }, (_, index) => version(`story-${index}`, "article", "copywriting")),
      version("story-p", "article", "published", "published"),
    ];
    const issues = projectContentItemBoard({ contentItemVersions: versions });
    assert.equal(issues.length, 4, "the records loaded count is stories only");
    assert.equal(issues.filter(issue => issue.nativeStatus === "copywriting").length, 3);
    assert.equal(issues.filter(issue => issue.nativeStatus === "published").length, 1);
  },
  async paging() {
    // A column of 25 articles sits behind 1,362 newer wiki pages: the first requests return no matches at all but still carry a token.
    const wikiRun = Array.from({ length: 1362 }, (_, index) => version(`wiki-${index}`, "wiki_page", "copywriting"));
    const articles = Array.from({ length: 25 }, (_, index) => version(`story-${index}`, "article", "copywriting"));
    const { fetchPage, requests } = fakePartition([...wikiRun, ...articles]);
    const first = await collectFilteredPage(fetchPage, { wanted: 25 });
    assert.equal(first.items.length, 25, "all 25 articles load past 1,362 wiki pages");
    assert(first.items.every(row => row.type === "article"));
    assert.equal(first.nextToken, null, "the partition ended with the articles");
    assert(requests.length > 1, "the first requests came back empty and paging went on");
    assert.equal(requests.reduce((total, size) => total + size, 0), 1387, "every row of the partition was read once");

    // A second page picks up where the first stopped, and a short page is never mistaken for the end.
    const interleaved = Array.from({ length: 300 }, (_, index) => version(index % 100 === 99 ? `story-${index}` : `wiki-${index}`, index % 100 === 99 ? "article" : "wiki_page", "copywriting"));
    const second = fakePartition(interleaved);
    const pageOne = await collectFilteredPage(second.fetchPage, { wanted: 2 });
    assert.equal(pageOne.items.length, 2);
    assert.notEqual(pageOne.nextToken, null);
    const pageTwo = await collectFilteredPage(second.fetchPage, { wanted: 2, nextToken: pageOne.nextToken });
    assert.equal(pageTwo.items.length, 1);
    assert.equal(pageTwo.nextToken, null);
    assert.deepEqual([...pageOne.items, ...pageTwo.items].map(row => row.id), ["story-99", "story-199", "story-299"], "no article is skipped or repeated");

    // A column with no story at all ends cleanly instead of looping.
    const none = await collectFilteredPage(fakePartition(wikiRun).fetchPage, { wanted: 25 });
    assert.deepEqual(none, { items: [], nextToken: null });
  },
};

void (async () => {
  const names = scenario === "all" ? Object.keys(runs) : [scenario];
  for (const name of names) {
    assert(runs[name], `unknown scenario ${name}`);
    await runs[name]();
    console.log(`Board story types scenario passed: ${name}`);
  }
})();
