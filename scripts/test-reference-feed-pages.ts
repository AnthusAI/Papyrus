import assert from "node:assert/strict";
import test from "node:test";
import { MergedFeedReader, acceptedRows, capturedRows, compareFeedRecords, feedReaderFromRecords, feedStateKeys, liveStarRows, shownInFeed, starFeedKeys, starReaderFromRecords, starsOf } from "../lib/reference-feed-pages";
import type { ReferenceRecord } from "../lib/category-repository";
import { CAPTURE_NEEDED_SHOWN, captureNeededSourceFromRecords, readCaptureNeeded } from "../lib/capture-needed";

const make = (i: number, corpusId: string, extra: Partial<ReferenceRecord> = {}): ReferenceRecord => ({
  id: `r${i}-v1`, lineageId: `r${i}`, versionState: "current", corpusId, externalItemId: `r${i}`, curationStatus: "pending",
  createdAt: new Date(Date.UTC(2026, 9, 1) + i * 60000).toISOString(), predictedAcceptProbability: ((i * 37) % 100) / 100, ...extra,
});
const records = Array.from({ length: 300 }, (_, i) => make(i, ["a", "b", "c"][i % 3] === "a" && i % 7 ? "alpha" : i % 2 ? "beta" : "gamma", i % 10 === 9 ? { curationStatus: "accepted" } : {}));

test("partitions are one per corpus and state", () => {
  assert.deepEqual(feedStateKeys(["x", "y"], "unrated"), ["x#unrated", "y#unrated"]);
  assert.deepEqual(feedStateKeys(["x", "x"], "all"), ["x#unrated", "x#rated"]);
  assert.deepEqual(feedStateKeys(["x", "y"], "rated"), ["x#rated", "y#rated"], "Rated reads the rated partitions alone");
});

for (const sort of ["best", "newest"] as const) {
  test(`pages merged across corpora keep one global order (${sort}), each record once`, async () => {
    const reads: string[] = [];
    const inner = feedReaderFromRecords(records);
    const reader = new MergedFeedReader({ keys: feedStateKeys(["alpha", "beta", "gamma"], "all"), sort, pageSize: 24, read: async (query) => { reads.push(query.feedStateKey); return inner(query); } });
    const seen: ReferenceRecord[] = [];
    while (reader.hasMore) { const placed = await reader.more(24); assert.ok(placed.length <= 24); seen.push(...placed); }
    assert.equal(new Set(seen.map((r) => r.id)).size, 300, "every record, once");
    const expected = [...records].sort((l, r) => {
      const a = sort === "best" ? `${(l.predictedAcceptProbability ?? 0.5).toFixed(6)}#${l.createdAt}` : l.createdAt!;
      const b = sort === "best" ? `${(r.predictedAcceptProbability ?? 0.5).toFixed(6)}#${r.createdAt}` : r.createdAt!;
      return a < b ? 1 : a > b ? -1 : 0;
    });
    assert.deepEqual(seen.map((r) => r.id), expected.map((r) => r.id));
  });
}

test("the first call is one round of reads, one per partition, and never walks pages to fill a target", async () => {
  let reads = 0;
  const inner = feedReaderFromRecords(records);
  const reader = new MergedFeedReader({ keys: feedStateKeys(["alpha", "beta", "gamma"], "unrated"), sort: "best", read: async (q) => { reads += 1; return inner(q); } });
  const first = await reader.more(24);
  assert.equal(reads, 3);
  assert.equal(first.length, 24);
  await reader.more(24);
  assert.ok(reads <= 6, "the second page reads at most one more round");
});

test("a refused read leaves the reader as it was, so asking again retries it", async () => {
  const inner = feedReaderFromRecords(records);
  let fail = true;
  const reader = new MergedFeedReader({ keys: feedStateKeys(["alpha"], "unrated"), sort: "newest", read: async (q) => { if (fail) throw new Error("refused"); return inner(q); } });
  await assert.rejects(reader.more(24), /refused/);
  fail = false;
  assert.equal((await reader.more(24)).length, 24);
});

// --- the star partitions: the Quality sort and the minimum of stars -----------------------------------------------------------------------

const starred = (i: number, corpusId: string, stars: number | null | undefined, extra: Partial<ReferenceRecord> = {}): ReferenceRecord =>
  make(i, corpusId, { ...(stars === undefined ? {} : { starRating: stars }), ...extra });

test("a minimum reads the star levels from that number up to 5, one partition per corpus and level", () => {
  assert.deepEqual(starFeedKeys(["x"], 5), ["x#stars#5"]);
  assert.deepEqual(starFeedKeys(["x"], 4), ["x#stars#5", "x#stars#4"]);
  assert.deepEqual(starFeedKeys(["x", "y", "x"], 3), ["x#stars#5", "x#stars#4", "x#stars#3", "y#stars#5", "y#stars#4", "y#stars#3"]);
  assert.deepEqual(starFeedKeys(["x"], 1), ["x#stars#5", "x#stars#4", "x#stars#3", "x#stars#2", "x#stars#1"], "Quality with the minimum on Any reads every level");
  assert.deepEqual(starFeedKeys(["x"], 0), starFeedKeys(["x"], 1), "no minimum is the first level, never a level 0 partition");
});

test("Quality is more stars first, then the latest arrival, then the id; a missing or odd rating counts as none", () => {
  const rows = [
    starred(1, "c", 3), starred(2, "c", 5), starred(3, "c", 5, { createdAt: "2026-11-01T00:00:00.000Z" }), starred(4, "c", null), starred(5, "c", undefined),
    starred(6, "c", 4.5 as number), starred(7, "c", Number.NaN), starred(8, "c", 4), starred(9, "c", 9),
  ];
  const ordered = [...rows].sort(compareFeedRecords("quality")).map((row) => row.lineageId);
  // r3 (5 stars, the latest arrival) then r2 (5 stars), r8 (4), r1 (3), and the five with no usable rating after them, newest arrival first.
  assert.deepEqual(ordered.slice(0, 4), ["r3", "r2", "r8", "r1"]);
  assert.deepEqual(ordered.slice(4), ["r9", "r7", "r6", "r5", "r4"]);
  assert.deepEqual(rows.map((row) => starsOf(row)), [3, 5, 5, 0, 0, 0, 0, 4, 0]);
});

test("star partitions in memory hold every starred row, state or not, newest first, and a quality merge orders by stars across them", async () => {
  const rows = [
    starred(1, "alpha", 5), starred(2, "alpha", 4), starred(3, "beta", 5), starred(4, "beta", 4), starred(5, "alpha", 3), starred(6, "alpha", null),
    starred(7, "alpha", 5, { curationStatus: "archived" }),
  ];
  const read = starReaderFromRecords(rows);
  const first = await read({ feedStateKey: "alpha#stars#5", sort: "newest", limit: 24, nextToken: null });
  assert.deepEqual(first.items.map((row) => row.lineageId), ["r7", "r1"], "an archived row is still in the star partition: the reader filters it");
  const reader = new MergedFeedReader({ keys: starFeedKeys(["alpha", "beta"], 4), sort: "quality", read: liveStarRows(read, "all") });
  const seen: string[] = [];
  while (reader.hasMore) seen.push(...(await reader.more(24)).map((row) => row.lineageId!));
  assert.deepEqual(seen, ["r3", "r1", "r4", "r2"], "5 stars newest first (the archived r7 is dropped), then 4 stars newest first");
});

test("Show is honoured on star rows by the feed state suffix, and a row with no feed state never shows", () => {
  const unrated = { feedStateKey: "c#unrated" };
  const rated = { feedStateKey: "c#rated" };
  assert.deepEqual([shownInFeed(unrated, "unrated"), shownInFeed(rated, "unrated")], [true, false]);
  assert.deepEqual([shownInFeed(unrated, "rated"), shownInFeed(rated, "rated")], [false, true]);
  assert.deepEqual([shownInFeed(unrated, "all"), shownInFeed(rated, "all"), shownInFeed({ feedStateKey: null }, "all"), shownInFeed({}, "all")], [true, true, false, false]);
});

test("a page that filters to nothing does not end the feed: the reader keeps reading and returns the later rows", async () => {
  // Sixty archived rows arrived after three live ones, so the first two pages of 24 are all dropped by the client filter.
  const ghosts = Array.from({ length: 60 }, (_, i) => starred(i, "g", 5, { curationStatus: "archived", createdAt: new Date(Date.UTC(2026, 10, 2) + i * 1000).toISOString() }));
  const live = Array.from({ length: 3 }, (_, i) => starred(100 + i, "g", 5, { createdAt: new Date(Date.UTC(2026, 10, 1) + i * 1000).toISOString() }));
  const inner = starReaderFromRecords([...ghosts, ...live]);
  let reads = 0;
  const reader = new MergedFeedReader({ keys: starFeedKeys(["g"], 5), sort: "quality", pageSize: 24, read: liveStarRows(async (query) => { reads += 1; return inner(query); }, "all") });
  const first = await reader.more(24);
  assert.deepEqual(first, [], "the first page filters to nothing");
  assert.equal(reader.hasMore, true, "but the partition is not finished, so the feed asks again (the sentinel row stays and loads the next round)");
  const placed: string[] = [];
  let calls = 1;
  while (reader.hasMore) { calls += 1; placed.push(...(await reader.more(24)).map((row) => row.lineageId!)); assert.ok(calls < 10); }
  assert.deepEqual(placed.sort(), ["r100", "r101", "r102"]);
  assert.equal(reads, 3, "three pages of 24 cover the 63 rows");
});

const held = (i: number, fields: Partial<ReferenceRecord> = {}): ReferenceRecord => ({
  ...make(i, "g"), curationStatus: "accepted", feedStateKey: "g#rated", feedArrivalAt: new Date(Date.UTC(2026, 10, 1) + i * 1000).toISOString(), ...fields,
});

test("Reviewed Accepted reads the rated partition and keeps only the accepted", async () => {
  assert.deepEqual(feedStateKeys(["x"], "accepted"), ["x#rated"]);
  const rows = [held(1), held(2, { curationStatus: "rejected" }), held(3), held(4, { curationStatus: "pending", feedStateKey: "g#unrated" })];
  assert.deepEqual([shownInFeed(rows[0], "accepted"), shownInFeed(rows[1], "accepted"), shownInFeed(rows[3], "accepted")], [true, false, false]);
  const reader = new MergedFeedReader({ keys: feedStateKeys(["g"], "accepted"), sort: "newest", read: acceptedRows(feedReaderFromRecords(rows), "accepted") });
  assert.deepEqual((await reader.more(24)).map((row) => row.lineageId), ["r3", "r1"]);
  assert.equal(acceptedRows(feedReaderFromRecords(rows), "all") !== undefined, true);
});

test("Captured keeps full (Yes) or everything else (No), and a long run of filtered rows does not end the list", async () => {
  // Sixty captured rows arrive after three uncaptured ones: every page of the first rounds filters to nothing for Captured No.
  const captured = Array.from({ length: 60 }, (_, i) => held(200 + i, { captureState: "full", feedArrivalAt: new Date(Date.UTC(2026, 11, 2) + i * 1000).toISOString() }));
  const missing = [held(1, { captureState: "thin" }), held(2, { captureState: "none" }), held(3, { captureState: "running" }), held(4, { captureState: null })];
  const inner = feedReaderFromRecords([...captured, ...missing]);
  let reads = 0;
  const reader = new MergedFeedReader({ keys: feedStateKeys(["g"], "rated"), sort: "newest", pageSize: 24, read: capturedRows(async (query) => { reads += 1; return inner(query); }, "no") });
  const first = await reader.more(24);
  assert.deepEqual(first, [], "the first page of 24 filters to nothing");
  assert.equal(reader.hasMore, true, "but the partition is not finished");
  const placed: string[] = [];
  let calls = 1;
  while (reader.hasMore) { calls += 1; placed.push(...(await reader.more(24)).map((row) => row.lineageId!)); assert.ok(calls < 10); }
  assert.deepEqual(placed.sort(), ["r1", "r2", "r3", "r4"], "thin, none, running and empty are all not captured");
  const yes = new MergedFeedReader({ keys: feedStateKeys(["g"], "rated"), sort: "newest", pageSize: 100, read: capturedRows(inner, "yes") });
  assert.equal((await yes.more(100)).length, 60);
  assert.equal(capturedRows(inner, "any"), inner, "Any reads the pages as they are");
});

test("the home list: accepted, not captured, not running; stars first then newest; unstarred after; stops when it has enough", async () => {
  const rows: ReferenceRecord[] = [
    held(1, { starRating: 3, starFeedKey: "g#stars#3", captureState: "none" }),
    held(2, { starRating: 5, starFeedKey: "g#stars#5", captureState: "thin" }),
    held(3, { starRating: 5, starFeedKey: "g#stars#5", captureState: "full" }),
    held(4, { starRating: 5, starFeedKey: "g#stars#5", captureState: "running" }),
    held(5, { starRating: 5, starFeedKey: "g#stars#5", captureState: "none", curationStatus: "rejected" }),
    held(6, { starRating: 5, starFeedKey: "g#stars#5", captureState: "none", versionState: "superseded" }),
    held(7, { starRating: 5, starFeedKey: "g#stars#5" }),
    ...Array.from({ length: 80 }, (_, i) => held(100 + i, { captureState: i % 2 ? "full" : "none" })),
  ];
  let reads = 0;
  const source = captureNeededSourceFromRecords(rows);
  const counted = { ...source, readStarStream: async (q: Parameters<typeof source.readStarStream>[0]) => { reads += 1; return source.readStarStream(q); }, readStream: async (q: Parameters<typeof source.readStream>[0]) => { reads += 1; return source.readStream(q); } };
  const found = await readCaptureNeeded(counted);
  assert.equal(CAPTURE_NEEDED_SHOWN, 3);
  assert.deepEqual(found.map((row) => row.lineageId), ["r7", "r2", "r1"], "5 stars newest first, then 5 stars older, then 3 stars; running, captured, rejected and superseded left out");
  const more = await readCaptureNeeded(source, 6);
  assert.deepEqual(more.map((row) => row.lineageId), ["r7", "r2", "r1", "r178", "r176", "r174"], "the unstarred follow every starred one, newest first");
  assert.ok(reads <= 12, `it stops once it has enough (${reads} reads)`);
  // A site without the star index still lists the unstarred; one that fails both lists none and does not throw.
  const noStars = await readCaptureNeeded({ ...source, readStarStream: async () => { throw new Error("no index"); } });
  assert.deepEqual(noStars.map((row) => row.lineageId), ["r178", "r176", "r174"]);
  const none = await readCaptureNeeded({ ...source, readStarStream: async () => { throw new Error("x"); }, readStream: async () => { throw new Error("y"); } });
  assert.deepEqual(none, []);
});
