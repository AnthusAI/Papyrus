import assert from "node:assert/strict";
import test from "node:test";
import { createMergedThreadStream, latestMessages, sectionOfThreadKind, threadKindsForSection, type PagedThreads } from "../lib/conversation-feed";

type Thread = { id: string; updatedAt: string };
const at = (minute: number) => `2026-10-29T10:${String(minute).padStart(2, "0")}:00Z`;
const lane = (ids: Array<[string, number]>, pageSize: number) => async (token: string | null): Promise<PagedThreads<Thread>> => {
  const start = token ? Number(token) : 0;
  const items = ids.slice(start, start + pageSize).map(([id, minute]) => ({ id, updatedAt: at(minute) }));
  return { items, nextToken: start + pageSize < ids.length ? String(start + pageSize) : null };
};

test("Sections list conversations and never machine records", () => {
  assert.deepEqual(threadKindsForSection("references"), ["reference_conversation"]);
  assert.deepEqual(threadKindsForSection("chats"), ["console"]);
  assert.deepEqual(threadKindsForSection("other"), ["conversation", "edition_forum", "section_forum"]);
  assert.equal(threadKindsForSection("all").length, 6);
  assert.equal(sectionOfThreadKind("section_forum"), "other");
  assert.equal(sectionOfThreadKind("ingestion_rationale"), null);
  assert.equal(sectionOfThreadKind("reference_curation"), null);
});

test("Streams merge newest activity first across pages, exactly", async () => {
  const lanes: Record<string, (token: string | null) => Promise<PagedThreads<Thread>>> = {
    a: lane([["a1", 50], ["a2", 30], ["a3", 10]], 2),
    b: lane([["b1", 45], ["b2", 44], ["b3", 5]], 2),
    c: lane([], 2),
  };
  const calls: string[] = [];
  const stream = createMergedThreadStream(["a", "b", "c"], async (kind, token) => { calls.push(`${kind}:${token}`); return lanes[kind](token); });
  const first = await stream.next(3);
  assert.deepEqual(first.items.map((thread) => thread.id), ["a1", "b1", "b2"]);
  assert.equal(first.hasMore, true);
  const second = await stream.next(10);
  assert.deepEqual(second.items.map((thread) => thread.id), ["a2", "a3", "b3"]);
  assert.equal(second.hasMore, false);
  assert.ok(calls.includes("a:2") && calls.includes("b:2"), "later pages are only read when needed");
});

test("A thread seen twice is listed once, and an empty page with more behind it is skipped over", async () => {
  let reads = 0;
  const stream = createMergedThreadStream(["a", "b"], async (kind, token) => {
    if (kind === "a") return { items: [{ id: "x", updatedAt: at(9) }], nextToken: null };
    reads += 1;
    return reads === 1 ? { items: [], nextToken: "more" } : { items: [{ id: "x", updatedAt: at(9) }, { id: "y", updatedAt: at(1) }], nextToken: null };
  });
  const page = await stream.next(10);
  assert.deepEqual(page.items.map((thread) => thread.id), ["x", "y"]);
});

test("The newest messages show, the rest wait behind a count", () => {
  const all = [1, 2, 3, 4, 5];
  assert.deepEqual(latestMessages(all, 3, false), { shown: [3, 4, 5], hidden: 2 });
  assert.deepEqual(latestMessages(all, 3, true), { shown: all, hidden: 0 });
  assert.deepEqual(latestMessages(all, 9, false), { shown: all, hidden: 0 });
});
