// The board's stage columns on the head stage index (features/newsroom-board-head-index.feature). A fake index over synthetic rows follows
// DynamoDB's rules: the key condition picks the partition and the sort-key range before the read, `limit` rows are read, and the filter runs
// after the read. It counts every row read, so the tests can say how many rows a column cost.
import assert from "node:assert/strict";
import test from "node:test";
import { applyChangedVersions, type VersionBucket } from "../lib/board-refresh";
import { contentItemHeadStageKey, type ContentItemVersionRecord } from "../lib/content-item-lifecycle";
import { readStoryStageChangesSince, readStoryStagePage, type StageQueryFetch } from "../lib/story-stage-query";
import { readWithStoryStageIndex, resetHeadStageIndexMissing, storyStageIndexMode } from "../lib/story-stage-mode";

type Row = ContentItemVersionRecord;

function version(lineageId: string, versionNumber: number, stage: string, versionState: string, updatedAt: string, type = "news"): Row {
  return {
    id: `${lineageId}-v${versionNumber}`, lineageId, versionNumber, stage, type, status: stage === "published" ? "published" : "draft", slug: lineageId, updatedAt, versionState,
    headStageKey: contentItemHeadStageKey({ stage, versionState }),
  };
}

type Condition = Record<string, { ne?: unknown; eq?: unknown }> | { and: Condition[] };
function matches(row: Row, filter: Condition | undefined): boolean {
  if (!filter) return true;
  if ("and" in filter && Array.isArray(filter.and)) return filter.and.every(part => matches(row, part));
  return Object.entries(filter as Record<string, { ne?: unknown; eq?: unknown }>).every(([field, test]) => {
    const value = (row as Record<string, unknown>)[field];
    if ("ne" in test) return value !== test.ne;
    if ("eq" in test) return value === test.eq;
    return true;
  });
}

function fakeIndex(rows: Row[], options: { headIndexMissing?: boolean } = {}) {
  const meter = { requests: 0, rowsRead: 0, readIds: [] as string[], fields: new Set<string>() };
  const fetch: StageQueryFetch = async ({ query, field, variables }) => {
    meter.requests += 1;
    meter.fields.add(field);
    if (field === "listItemsByHeadStageAndUpdatedAt" && options.headIndexMissing) {
      throw new Error("Validation error of type FieldUndefined: Field 'listItemsByHeadStageAndUpdatedAt' in type 'Query' is undefined @ 'listItemsByHeadStageAndUpdatedAt'");
    }
    assert.match(query, new RegExp(field), "the query names the field it is read from");
    const partitionKey = field === "listItemsByHeadStageAndUpdatedAt" ? "headStageKey" : "stage";
    const since = (variables.updatedAt as { ge?: string } | undefined)?.ge;
    const partition = rows
      .filter(row => (row as Record<string, unknown>)[partitionKey] === variables.key)
      .filter(row => !since || String(row.updatedAt) >= since)
      .sort((left, right) => String(right.updatedAt).localeCompare(String(left.updatedAt)));
    const offset = variables.nextToken ? Number(variables.nextToken) : 0;
    const read = partition.slice(offset, offset + Number(variables.limit));
    meter.rowsRead += read.length;
    meter.readIds.push(...read.map(row => row.id));
    const next = offset + read.length;
    return { items: read.filter(row => matches(row, variables.filter as Condition)), nextToken: next < partition.length ? String(next) : null };
  };
  return { fetch, meter };
}

const minute = (n: number) => new Date(Date.UTC(2026, 10, 10, 9, 0) + n * 60_000).toISOString();

test("a story published after Copywriting shows only in Published, and Copywriting reads none of its rows", async () => {
  const rows = [
    version("story-a", 1, "copywriting", "superseded", minute(5)),   // superseding stamped it late, so it sorts first in the old stage partition
    version("story-a", 2, "published", "current", minute(4)),
    version("story-b", 1, "copywriting", "current", minute(1)),
  ];
  const { fetch, meter } = fakeIndex(rows);
  const copywriting = await readStoryStagePage(fetch, "head", "copywriting");
  const copywritingReads = [...meter.readIds];
  const published = await readStoryStagePage(fetch, "head", "published");
  assert.deepEqual(copywriting.items.map(row => row.id), ["story-b-v1"]);
  assert.deepEqual(published.items.map(row => row.id), ["story-a-v2"]);
  assert.ok(!copywritingReads.some(id => id.startsWith("story-a")), "the Copywriting column read no row of the published story");
});

test("a refresh after a new version in another stage shows the story once, in its new stage", async () => {
  const before = [version("story-a", 1, "copywriting", "current", minute(1)), version("story-b", 1, "copywriting", "current", minute(0))];
  const shown: Record<string, VersionBucket> = {
    copywriting: { versions: (await readStoryStagePage(fakeIndex(before).fetch, "head", "copywriting")).items, nextToken: null, pagesLoaded: 1 },
    illustration: { versions: [], nextToken: null, pagesLoaded: 1 },
  };
  // The editor saves version 2 in Illustration: version 1 is superseded (and loses its head key), version 2 is the head.
  const after = [version("story-a", 1, "copywriting", "superseded", minute(9)), version("story-a", 2, "illustration", "current", minute(9)), before[1]];
  const { fetch } = fakeIndex(after);
  const changed = {
    copywriting: await readStoryStageChangesSince(fetch, "head", "copywriting", minute(1)),
    illustration: await readStoryStageChangesSince(fetch, "head", "illustration", minute(0)),
  };
  assert.deepEqual(changed.copywriting, [], "the old stage has nothing new: the superseded row is in no head partition");
  const next = applyChangedVersions(shown, changed, { oneRowPerLineage: true });
  assert.deepEqual(next.illustration.versions.map(row => row.id), ["story-a-v2"]);
  assert.deepEqual(next.copywriting.versions.map(row => row.id), ["story-b-v1"], "no card of the story is left in Copywriting");
});

test("a column reads only the stories it shows: 25 rows for the first page of a Published column of stories published five times", async () => {
  const rows: Row[] = [];
  for (let story = 0; story < 30; story += 1) {
    for (let number = 1; number <= 5; number += 1) rows.push(version(`story-${story}`, number, "published", number === 5 ? "current" : "superseded", minute(story * 10 + number)));
  }
  const head = fakeIndex(rows);
  const page = await readStoryStagePage(head.fetch, "head", "published");
  assert.equal(page.items.length, 25);
  assert.equal(new Set(page.items.map(row => row.lineageId)).size, 25, "one row per story");
  assert.equal(head.meter.rowsRead, 25, "it read 25 rows");
  assert.equal(head.meter.requests, 1, "in one request");
  assert.ok(page.nextToken, "and there are more stories to load");

  const old = fakeIndex(rows);
  const oldPage = await readStoryStagePage(old.fetch, "stage", "published");
  assert.equal(oldPage.items.length, 30, "the stage index finds the same stories (and a few more in the same read)");
  assert.equal(old.meter.rowsRead, 150, "but reads every saved version to find them");
});

test("a site that has not switched keeps today's board", async () => {
  resetHeadStageIndexMissing();
  assert.equal(storyStageIndexMode({}), "stage");
  assert.equal(storyStageIndexMode({ storyHeadStageIndex: false }), "stage");
  const { fetch, meter } = fakeIndex([version("story-a", 1, "idea", "current", minute(1)), version("story-a", 2, "idea", "superseded", minute(2))]);
  const page = await readWithStoryStageIndex(mode => readStoryStagePage(fetch, mode, "idea"), {});
  assert.deepEqual([...meter.fields], ["listItemsByStageAndUpdatedAt"]);
  assert.deepEqual(page.items.map(row => row.id), ["story-a-v1"], "superseded rows are still hidden by the filter");
  const shown = { idea: { versions: page.items, nextToken: null, pagesLoaded: 1 } };
  const other = version("story-a", 3, "reporting", "draft", minute(3));
  const unchanged = applyChangedVersions(shown, { reporting: [other] });
  assert.deepEqual(unchanged.idea.versions.map(row => row.id), ["story-a-v1"], "without the head index a changed row replaces only its own id, as before");
});

test("a site whose backend has no head stage index drops back to the stage index", async () => {
  resetHeadStageIndexMissing();
  const flagged = { storyHeadStageIndex: true };
  assert.equal(storyStageIndexMode(flagged), "head");
  const { fetch, meter } = fakeIndex([version("story-a", 1, "idea", "current", minute(1))], { headIndexMissing: true });
  const page = await readWithStoryStageIndex(mode => readStoryStagePage(fetch, mode, "idea"), flagged);
  assert.deepEqual(page.items.map(row => row.id), ["story-a-v1"], "the column still shows its stories");
  assert.equal(storyStageIndexMode(flagged), "stage", "and the rest of the session reads the stage index without asking again");
  meter.fields.clear();
  await readWithStoryStageIndex(mode => readStoryStagePage(fetch, mode, "idea"), flagged);
  assert.deepEqual([...meter.fields], ["listItemsByStageAndUpdatedAt"]);
  resetHeadStageIndexMissing();
});

test("any other error is not mistaken for a missing index", async () => {
  resetHeadStageIndexMissing();
  const flagged = { storyHeadStageIndex: true };
  await assert.rejects(readWithStoryStageIndex(async () => { throw new Error("Not Authorized to access listItemsByHeadStageAndUpdatedAt on type Query"); }, flagged));
  assert.equal(storyStageIndexMode(flagged), "head");
});
