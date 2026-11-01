import assert from "node:assert/strict";
import test from "node:test";
import type { ReferenceRecord } from "../lib/category-repository";
import {
  FEED_PAGE_SIZE,
  buildFeedItems,
  extendFeedOrderSnapshot,
  feedWindow,
  laterPageItems,
  takeFeedOrderSnapshot,
  applyFeedOrderSnapshot,
} from "../lib/reference-feed-ranking";
import { loadPredictionsForReferences, predictionsSettled, PREDICTION_READ_CONCURRENCY, type PredictionStatuses } from "../lib/reference-predictions";

const HOUR = 3_600_000;
const NOW = Date.parse("2026-11-01T12:00:00Z");

function reference(index: number, curationStatus = "pending"): ReferenceRecord {
  const id = `ref-${String(index).padStart(4, "0")}`;
  return {
    id: `${id}-v1`, lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title: id,
    sourceUri: `https://${id}.example.org/a`, curationStatus, createdAt: new Date(NOW - index * HOUR).toISOString(),
  } as ReferenceRecord;
}

test("a newsroom with far more relations than any page budget reads only the shown References, each by its own index", async () => {
  // 15,900 relations: three for each of 5,300 References, held by subject like the SemanticRelation subject index.
  const bySubject = new Map<string, string[]>();
  for (let index = 0; index < 5300; index += 1) bySubject.set(`ref-${String(index).padStart(4, "0")}`, ["classified_as", "relevance_decision_is", "cites"]);
  const touched: string[] = [];
  const read: string[] = [];
  const shown = Array.from({ length: FEED_PAGE_SIZE }, (_, index) => `ref-${String(index).padStart(4, "0")}`);
  await loadPredictionsForReferences(shown, async (id) => { touched.push(id); return bySubject.get(id)!; }, {
    ready: (id, relations) => { read.push(id); assert.equal(relations.length, 3); },
    failed: () => assert.fail("nothing fails"),
  });
  assert.deepEqual([...touched].sort(), [...shown].sort(), "one read per shown Reference");
  assert.equal(touched.length, FEED_PAGE_SIZE, "no read of the other 5,276 References and none of the whole relation feed");
  assert.equal(read.length, FEED_PAGE_SIZE);
});

test("reads are bounded in flight, and one failing read never fails the others", async () => {
  const ids = Array.from({ length: 40 }, (_, index) => `ref-${index}`);
  let inFlight = 0;
  let peak = 0;
  const ready: string[] = [];
  const failed: Array<[string, string]> = [];
  await loadPredictionsForReferences(ids, async (id) => {
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 2));
    inFlight -= 1;
    if (id === "ref-7") throw new Error("Index read refused.");
    return [id];
  }, { ready: (id) => ready.push(id), failed: (id, error) => failed.push([id, error]) });
  assert.ok(peak <= PREDICTION_READ_CONCURRENCY && peak > 1, `reads overlap but stay within ${PREDICTION_READ_CONCURRENCY}, saw ${peak}`);
  assert.equal(ready.length, 39);
  assert.deepEqual(failed, [["ref-7", "Index read refused."]]);
});

test("a Reference is settled once it has its prediction or its own failure, and not before it is asked about", () => {
  const statuses: PredictionStatuses = new Map([["a", { state: "ready" }], ["b", { state: "error", error: "x" }], ["c", { state: "loading" }]]);
  assert.equal(predictionsSettled(["a", "b"], statuses), true);
  assert.equal(predictionsSettled(["a", "c"], statuses), false);
  assert.equal(predictionsSettled(["a", "d"], statuses), false);
});

test("the feed window is the newest pages of unanswered items plus the answered ones since, and only ever grows", () => {
  const references = Array.from({ length: 200 }, (_, index) => reference(index, index % 4 === 3 ? "accepted" : "pending"));
  const items = buildFeedItems(references, undefined);
  const first = feedWindow(items, 1);
  assert.equal(first.filter((item) => !item.rated).length, FEED_PAGE_SIZE, "one page of unanswered items");
  assert.ok(first.some((item) => item.rated), "with the answered ones that arrived since the oldest of them");
  assert.deepEqual(first.map((item) => item.lineageId), items.slice(0, first.length).map((item) => item.lineageId), "the newest first");
  const second = feedWindow(items, 2);
  assert.equal(second.filter((item) => !item.rated).length, FEED_PAGE_SIZE * 2);
  assert.deepEqual(second.slice(0, first.length).map((item) => item.lineageId), first.map((item) => item.lineageId), "the next page extends the first");
  assert.equal(feedWindow(items, 1000).length, items.length, "past the last page it is everything");
  assert.equal(feedWindow([], 1).length, 0);
});

test("a later page joins after everything already placed, a new arrival does not", () => {
  const references = Array.from({ length: 100 }, (_, index) => reference(index));
  const decisions = new Map();
  const items = buildFeedItems(references, decisions);
  const firstPage = feedWindow(items, 1);
  const snapshot = takeFeedOrderSnapshot(firstPage);
  const wider = feedWindow(items, 2);
  const seen = new Set(items.map((item) => item.lineageId));
  const older = laterPageItems(snapshot, seen, wider);
  assert.equal(older.length, FEED_PAGE_SIZE, "the second page was already there, just not placed yet");
  const extended = extendFeedOrderSnapshot(snapshot, older);
  assert.deepEqual(extended.best.slice(0, snapshot.best.length), snapshot.best, "nothing above moves in Best bets");
  assert.deepEqual(extended.newest.slice(0, snapshot.newest.length), snapshot.newest, "nothing above moves in Newest");
  assert.equal(extended.known.size, FEED_PAGE_SIZE * 2);
  assert.equal(applyFeedOrderSnapshot(extended, wider, "newest", "unrated").items.length, FEED_PAGE_SIZE * 2);

  const arrival = { ...reference(0), lineageId: "just-arrived", id: "just-arrived-v1", createdAt: new Date(NOW + HOUR).toISOString() } as ReferenceRecord;
  const live = buildFeedItems([arrival, ...references.slice(0, FEED_PAGE_SIZE)], decisions);
  assert.deepEqual(laterPageItems(snapshot, seen, live), [], "an item that arrived since the order was taken is not a page, it waits behind the pill");
  assert.equal(applyFeedOrderSnapshot(snapshot, live, "newest", "unrated").newCount, 1);
});
