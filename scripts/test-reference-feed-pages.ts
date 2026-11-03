import assert from "node:assert/strict";
import test from "node:test";
import { MergedFeedReader, feedReaderFromRecords, feedStateKeys } from "../lib/reference-feed-pages";
import type { ReferenceRecord } from "../lib/category-repository";

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
