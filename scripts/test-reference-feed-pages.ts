/** The paging rules of the References feed, with a counting fake source standing in for the two indexes. No React, no network. */
import assert from "node:assert/strict";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import { ReferenceFeedController } from "../lib/reference-feed-controller";
import { FEED_PAGE_SIZE, compareFeedRecords, createStaticFeedSource, type FeedPageRequest, type ReferenceFeedSource } from "../lib/reference-feed-pages";
import { referenceFeedKeys } from "../lib/reference-feed-keys";

const CORPUS = "knowledge-corpus-demo";
const START = Date.parse("2026-10-20T00:00:00Z");

function reference(index: number, status: "pending" | "accepted" | "rejected" = "pending", probability: number | null = null): ReferenceRecord {
  const id = `r${String(index).padStart(5, "0")}`;
  const base: ReferenceRecord = {
    id: `${id}-v1`, lineageId: id, versionState: "current", versionNumber: 1, corpusId: CORPUS, externalItemId: id, title: `Title ${id}`,
    sourceUri: `https://${id}.example.org/story`, curationStatus: status, createdAt: new Date(START + index * 60_000).toISOString(),
    predictedAcceptProbability: probability,
  };
  return { ...base, ...referenceFeedKeys(base) };
}

/** A fake of the two indexes over a fixture: pages by offset token, sorted by the index key, counting every request. */
function fakeSource(rows: ReferenceRecord[]) {
  const counts = { pages: [] as Array<{ stream: string; sort: string; limit: number; returned: number }>, companions: [] as number[], references: 0, news: 0, rated: 0 };
  let all = rows;
  const stream = (request: FeedPageRequest) => all
    .filter((row) => (request.stream === "rated") === (row.curationStatus !== "pending"))
    .sort(compareFeedRecords(request.sort));
  const source: ReferenceFeedSource = {
    async fetchPage(request) {
      const rowsForStream = stream(request);
      const start = request.nextToken ? Number(request.nextToken) : 0;
      const items = rowsForStream.slice(start, start + request.limit);
      counts.pages.push({ stream: request.stream, sort: request.sort, limit: request.limit, returned: items.length });
      return { items, nextToken: start + request.limit < rowsForStream.length ? String(start + request.limit) : null };
    },
    async fetchCompanions(references) {
      counts.companions.push(references.length);
      const attachments: ReferenceAttachmentRecord[] = references.map((row) => ({
        id: `a-${row.id}`, referenceId: row.id, referenceLineageId: row.lineageId!, referenceVersionKey: `reference#${row.id}`, role: "preview", sortKey: "1",
      }));
      return { attachments, decisions: new Map() };
    },
    async fetchReference(id) { counts.references += 1; return all.find((row) => row.id === id || row.lineageId === id) ?? null; },
    async countNew({ since, known }) {
      counts.news += 1;
      return all.filter((row) => row.curationStatus === "pending" && row.feedArrivalAt! > since && !known.has(row.lineageId!)).length;
    },
    async hasRated() { counts.rated += 1; return all.some((row) => row.curationStatus !== "pending"); },
  };
  return { source, counts, add(row: ReferenceRecord) { all = [...all, row]; } };
}

const settle = async (controller: ReferenceFeedController, until: () => boolean) => {
  for (let tick = 0; tick < 200 && !until(); tick += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(until(), "the feed settled");
};
const ids = (records: ReferenceRecord[]) => records.map((row) => row.lineageId);

async function main() {
  // A fixture of 2,000 References: 1,700 unrated with spread predictions, 300 rated.
  const rows: ReferenceRecord[] = [];
  for (let index = 0; index < 2000; index += 1) {
    const probability = index % 11 === 0 ? null : ((index * 37) % 100) / 100;
    rows.push(reference(index, index < 1700 ? "pending" : index % 2 ? "accepted" : "rejected", probability));
  }

  // 1. The first visit reads one page of 24 and its companions, not the 2,000.
  {
    const { source, counts } = fakeSource(rows);
    const controller = new ReferenceFeedController(source);
    controller.activate("best", "unrated");
    await settle(controller, () => controller.getState().status === "ready" && !controller.getState().companionsPending);
    const state = controller.getState();
    assert.equal(state.records.length, FEED_PAGE_SIZE, "one page");
    assert.deepEqual(counts.pages, [{ stream: "unrated", sort: "best", limit: 24, returned: 24 }], "one page request of 24");
    assert.deepEqual(counts.companions, [24], "one companions request, for the 24 on the page");
    assert.equal(state.attachments.length, 24, "attachments only for the loaded page");
    assert.equal(state.hasMore, true);
    // Best bets: highest P first; ties newest first; unpredicted (0.5) between Accept and Reject.
    const keys = state.records.map((row) => row.predictionSortKey!);
    assert.deepEqual([...keys].sort().reverse(), keys, "the page is in index order");

    // 2. Scrolling reads the next page and appends it after what is there; nothing before it moves.
    const before = ids(state.records);
    await controller.loadMore();
    await settle(controller, () => !controller.getState().companionsPending);
    const next = controller.getState();
    assert.equal(next.records.length, 48);
    assert.deepEqual(ids(next.records).slice(0, 24), before, "the first page did not move");
    assert.equal(counts.pages.length, 2);
    assert.deepEqual(counts.companions, [24, 24]);
    assert.equal(counts.pages.every((page) => page.limit === 24), true, "every page asks for 24");

    // 3. Loading more while a page is in flight shares it.
    const first = controller.loadMore();
    const second = controller.loadMore();
    await Promise.all([first, second]);
    assert.equal(controller.getState().records.length, 72, "two calls, one page");
    assert.equal(counts.pages.length, 3);
  }

  // 4. Rating a card leaves it in place; it never reorders anything, and the Reference does not come back from the other stream.
  {
    const { source } = fakeSource(rows);
    const controller = new ReferenceFeedController(source);
    controller.activate("best", "all");
    await settle(controller, () => controller.getState().status === "ready");
    const before = ids(controller.getState().records);
    controller.patch(before[3]!, { curationStatus: "accepted" });
    assert.deepEqual(ids(controller.getState().records), before, "rating changes no card's place");
    assert.equal(controller.getState().records[3]!.curationStatus, "accepted");
    assert.ok(controller.getState().visitRated.has(before[3]!));
    for (let page = 0; page < 6; page += 1) await controller.loadMore();
    const all = ids(controller.getState().records);
    assert.equal(new Set(all).size, all.length, "no card appears twice");
  }

  // 5. Include rated: two cursors merged by the sort's key, each paged lazily.
  {
    const { source, counts } = fakeSource(rows);
    const controller = new ReferenceFeedController(source);
    controller.activate("newest", "all");
    await settle(controller, () => controller.getState().status === "ready");
    assert.equal(controller.getState().records.length, 24);
    assert.deepEqual(counts.pages.map((page) => page.stream).sort(), ["rated", "unrated"], "one request per stream for the first page");
    const arrivals = controller.getState().records.map((row) => row.feedArrivalAt!);
    assert.deepEqual([...arrivals].sort().reverse(), arrivals, "newest first across both streams");
    assert.ok(controller.getState().records.some((row) => row.curationStatus !== "pending"), "rated cards are in the list in their place");
    await controller.loadMore();
    assert.equal(counts.pages.length, 3, "the second page of 24 needed one more page of the stream that ran dry, and none of the other");
    const merged = controller.getState().records.map((row) => row.feedArrivalAt!);
    assert.deepEqual([...merged].sort().reverse(), merged, "still in order after the second page");
  }

  // 6. Best bets merges rated and unrated by predicted accept probability.
  {
    const mixed = [reference(1, "pending", 0.9), reference(2, "accepted", 0.95), reference(3, "pending", null), reference(4, "rejected", 0.1), reference(5, "pending", 0.2)];
    const { source } = fakeSource(mixed);
    const controller = new ReferenceFeedController(source, { pageSize: 2 });
    controller.activate("best", "all");
    await settle(controller, () => controller.getState().status === "ready");
    await controller.loadMore();
    await controller.loadMore();
    assert.deepEqual(ids(controller.getState().records), ["r00002", "r00001", "r00003", "r00005", "r00004"], "0.95, 0.9, unpredicted 0.5, 0.2, 0.1");
    assert.equal(controller.getState().hasMore, false);
  }

  // 7. The lead is fixed when the first page arrives and is never a predicted Reject.
  {
    const rejects = [reference(1, "pending", 0.1), reference(2, "pending", 0.2)];
    const { source } = fakeSource(rejects);
    const controller = new ReferenceFeedController(source);
    controller.activate("best", "unrated");
    await settle(controller, () => controller.getState().status === "ready");
    assert.equal(controller.getState().leadId, undefined, "all predicted Rejects: no lead");
    const { source: withAccept } = fakeSource([reference(1, "pending", 0.8), reference(2, "pending", 0.9)]);
    const other = new ReferenceFeedController(withAccept);
    other.activate("best", "unrated");
    await settle(other, () => other.getState().status === "ready");
    assert.equal(other.getState().leadId, "r00002");
  }

  // 8. New arrivals wait behind a count; showing them starts the visit over. Nothing on screen moves until then.
  {
    const clock = { now: Date.parse("2026-11-01T00:00:00Z") };
    const { source, counts, add } = fakeSource(rows.slice(0, 100));
    const controller = new ReferenceFeedController(source, { now: () => clock.now });
    controller.activate("newest", "unrated");
    await settle(controller, () => controller.getState().status === "ready");
    const before = ids(controller.getState().records);
    const fresh = (index: number, offset: number): ReferenceRecord => {
      const base = { ...reference(index), createdAt: new Date(clock.now + offset).toISOString() };
      return { ...base, ...referenceFeedKeys(base) };
    };
    add(fresh(6000, 60_000));
    add(fresh(6001, 61_000));
    await controller.checkNew();
    assert.equal(controller.getState().newCount, 2, "two arrived after the visit began");
    assert.deepEqual(ids(controller.getState().records), before, "the pill never moves a card");
    assert.equal(counts.news, 1);
    controller.showNew();
    await settle(controller, () => controller.getState().status === "ready");
    assert.equal(controller.getState().newCount, 0);
    assert.equal(controller.getState().records[0]!.lineageId, "r06001", "the newest arrival leads after Show");
  }

  // 9. A deep link fetches that Reference by id and its companions, and does not load the feed.
  {
    const { source, counts } = fakeSource(rows);
    const controller = new ReferenceFeedController(source);
    const found = await controller.ensureReference("r01234");
    assert.equal(found?.lineageId, "r01234");
    assert.deepEqual(counts.pages, [], "no feed page was read");
    assert.equal(counts.references, 1);
    assert.deepEqual(counts.companions, [1], "only its own attachments and decision");
    assert.equal(controller.getState().extra.length, 1);
    assert.equal(await controller.ensureReference("missing"), null);
  }

  // 10. An empty unrated stream asks once whether anything was ever rated.
  {
    const { source, counts } = fakeSource([reference(1, "accepted", 0.9)]);
    const controller = new ReferenceFeedController(source);
    controller.activate("best", "unrated");
    await settle(controller, () => controller.getState().hasRated);
    assert.equal(counts.rated, 1);
    assert.equal(controller.getState().records.length, 0);
  }

  // 11. A failed page says why and can be retried; the cards already loaded stay.
  {
    const { source } = fakeSource(rows);
    let fail = false;
    const flaky: ReferenceFeedSource = { ...source, fetchPage: (request) => (fail ? Promise.reject(new Error("The References could not be read.")) : source.fetchPage(request)) };
    const controller = new ReferenceFeedController(flaky);
    controller.activate("best", "unrated");
    await settle(controller, () => controller.getState().status === "ready");
    fail = true;
    await controller.loadMore();
    assert.equal(controller.getState().error, "The References could not be read.");
    assert.equal(controller.getState().records.length, 24, "what was loaded stays");
    fail = false;
    await controller.retry();
    assert.equal(controller.getState().records.length, 48);
    assert.equal(controller.getState().error, null);
  }

  // 12. A host holding the whole list in memory pages it the same way (the harnesses' static source).
  {
    const data = { references: rows.slice(0, 60), decisions: new Map(), attachments: [] as ReferenceAttachmentRecord[] };
    const controller = new ReferenceFeedController(createStaticFeedSource(() => data));
    controller.activate("best", "unrated");
    await settle(controller, () => controller.getState().status === "ready");
    assert.equal(controller.getState().records.length, 24);
    await controller.loadMore();
    await controller.loadMore();
    assert.equal(controller.getState().records.length, 60);
    assert.equal(controller.getState().hasMore, false);
  }

  console.log("reference feed pages ok");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
