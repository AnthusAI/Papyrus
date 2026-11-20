import assert from "node:assert/strict";
import { SYSTEM_ITEM_TYPES, boardStoryFilter, isStoryItemType, storyItemTypeFilter, type ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import { projectContentItemBoard } from "../lib/newsroom-board";
import { collectFilteredPage, type FilteredPage } from "../lib/story-stage-paging";

/** A DynamoDB index partition as the board's query sees it: newest first, `limit` rows read per request, the filter applied after the read. */
function fakePartition(rows: ContentItemVersionRecord[]) {
  const requests: number[] = [];
  const fetchPage = async (nextToken: string | null, scanLimit: number): Promise<FilteredPage<ContentItemVersionRecord>> => {
    const start = nextToken ? Number(nextToken) : 0;
    const end = Math.min(start + scanLimit, rows.length);
    requests.push(end - start);
    // The query filter is `type ne <system type>` for every system type; the fake applies it after the read, as DynamoDB does.
    const clauses = (boardStoryFilter() as { and: Array<{ type?: { ne: string }; versionState?: { ne: string } }> }).and;
    const matches = (row: ContentItemVersionRecord) => clauses.every(clause => (!clause.type || row.type !== clause.type.ne) && (!clause.versionState || row.versionState !== clause.versionState.ne));
    return { items: rows.slice(start, end).filter(matches), nextToken: end < rows.length ? String(end) : null };
  };
  return { fetchPage, requests };
}

const version = (id: string, type: string, stage: string, status = "draft"): ContentItemVersionRecord => (
  { id, lineageId: id, versionNumber: 1, stage, type, status, title: id, slug: id, updatedAt: "2026-11-01" }
);
const scenario = process.argv[2] ?? "all";
const runs: Record<string, () => Promise<void>> = {
  async types() {
    assert.deepEqual([...SYSTEM_ITEM_TYPES], ["wiki_page", "doctrine", "page", "sub-task"], "the system set is fixed: these are not stories");
    for (const type of ["article", "post", "guide", "case_study", "untyped", "newsletter_issue"]) assert.equal(isStoryItemType(type), true, `${type} is a story type: nothing but the system set decides`);
    for (const type of ["wiki_page", "doctrine", "page", "", null, undefined]) assert.equal(isStoryItemType(type as string), false, `${String(type)} is not a story`);
    assert.deepEqual(storyItemTypeFilter(), { and: SYSTEM_ITEM_TYPES.map(type => ({ type: { ne: type } })) }, "the query filter excludes the system set and names no story type");
  },
  async new_type() {
    // A site's own type (`guide`) reaches the board with no engine change, in a stage column and in Published.
    const issues = projectContentItemBoard({ contentItemVersions: [
      version("wiki-1", "wiki_page", "copywriting"), version("guide-1", "guide", "copywriting"), version("post-1", "post", "copywriting"),
      version("guide-p", "guide", "published", "published"), version("issue-p", "newsletter_issue", "published", "published"), version("typeless-1", "untyped", "copywriting"),
    ] });
    assert.deepEqual(issues.map(issue => issue.nativeId).sort(), ["guide-1", "guide-p", "issue-p", "post-1", "typeless-1"], "a new type, a newsletter issue and a Story with no type are on the board; the wiki page is not");
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
  async superseded() {
    // Story 1 was written in Copywriting (v5), then published (v12). Superseded versions keep the stage they were saved in, and the Published column holds only
    // its newest page, so v12 may not be loaded. The board asks for rows that are not superseded, so v5 never stands in for the Story.
    assert.deepEqual(boardStoryFilter(), { and: [...SYSTEM_ITEM_TYPES.map(type => ({ type: { ne: type } })), { versionState: { ne: "superseded" } }] }, "the board filter is the story types and not superseded");
    const row = (id: string, versionNumber: number, stage: string, versionState: string): ContentItemVersionRecord => (
      { id: `${id}-v${versionNumber}`, lineageId: id, versionNumber, stage, type: "article", status: stage === "published" ? "published" : "draft", title: id, slug: id, updatedAt: "2026-11-08", versionState }
    );
    const copywriting = fakePartition([row("story-1", 5, "copywriting", "superseded"), row("story-2", 3, "copywriting", "current")]);
    const loaded = (await collectFilteredPage(copywriting.fetchPage, { wanted: 25 })).items;
    assert.deepEqual(loaded.map(entry => entry.id), ["story-2-v3"], "the superseded copy in Copywriting is not loaded");
    const issues = projectContentItemBoard({ contentItemVersions: loaded });
    assert.deepEqual(issues.map(issue => issue.nativeId), ["story-2"], "a Story whose newest version is in an unloaded Published page is not a Copywriting card");
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
