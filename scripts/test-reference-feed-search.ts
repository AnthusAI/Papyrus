import assert from "node:assert/strict";
import test from "node:test";
import type { ReferenceRecord } from "../lib/category-repository";
import {
  bothLanesFailed, laneNotice, matchedLabel, normalizeSearchQuery, parseSearchPage, pathWithSearch, previewSearch, searchQueryFromLocation,
} from "../lib/reference-search";

const make = (id: string, fields: Partial<ReferenceRecord> = {}): ReferenceRecord => ({
  id: `${id}-v1`, lineageId: id, versionState: "current", corpusId: "c", externalItemId: `ext-${id}`, curationStatus: "pending", title: `Title ${id}`,
  createdAt: "2026-11-01T10:00:00.000Z", ...fields,
});
const ok = { status: "ok" as const };

test("the words on a card say how it matched, never by colour alone", () => {
  assert.equal(matchedLabel(["keyword"], ["title", "authors"]), "title, author");
  assert.equal(matchedLabel(["meaning"], []), "meaning");
  assert.equal(matchedLabel(["keyword", "meaning"], ["title"]), "title and meaning");
  assert.equal(matchedLabel(["keyword", "meaning"], ["title", "authors"]), "title, author and meaning");
  assert.equal(matchedLabel(["keyword"], ["sourceUri", "externalItemId"]), "link, id");
});

test("one lane failing is a line of words, both failing is an error", () => {
  assert.equal(laneNotice({ keyword: ok, meaning: { status: "failed" } }), "Searched by words only: meaning search is unavailable");
  assert.equal(laneNotice({ keyword: { status: "failed" }, meaning: ok }), "Searched by meaning only: word search is unavailable");
  assert.equal(laneNotice({ keyword: ok, meaning: ok }), null);
  assert.equal(bothLanesFailed({ keyword: { status: "failed" }, meaning: { status: "failed" } }), true);
  assert.equal(bothLanesFailed({ keyword: ok, meaning: { status: "failed" } }), false);
});

test("the query is tidied, kept in the address and read back from it", () => {
  assert.equal(normalizeSearchQuery("  agent   memory \n"), "agent memory");
  assert.equal(normalizeSearchQuery(null), "");
  assert.equal(searchQueryFromLocation("?q=agent%20%20memory&status=x"), "agent memory");
  assert.equal(searchQueryFromLocation(""), "");
  assert.equal(pathWithSearch("/newsroom/references?status=pending", "agent memory"), "/newsroom/references?q=agent%20memory");
  assert.equal(pathWithSearch("/newsroom/references", ""), "/newsroom/references");
});

test("the site's answer is read defensively", () => {
  const page = parseSearchPage(JSON.stringify({ items: [{ reference: make("a"), matchedBy: ["keyword"], matchedFields: ["title"] }, { matchedBy: [] }], nextCursor: "c2", lanes: { keyword: ok, meaning: { status: "failed", message: "m" } } }));
  assert.equal(page.items.length, 1);
  assert.equal(page.nextCursor, "c2");
  assert.deepEqual(page.lanes.meaning, { status: "failed", message: "m" });
  assert.deepEqual(parseSearchPage({ items: [], lanes: {} }).lanes, { keyword: ok, meaning: ok });
  assert.throws(() => parseSearchPage("not json"), /unreadable/);
  assert.throws(() => parseSearchPage({ nothing: true }), /without results/);
});

test("the preview matcher finds rejected, accepted and unrated References by their words, and pages without repeating", () => {
  const records = [
    make("rej", { curationStatus: "rejected", authors: ["Marta Okafor"] }),
    make("acc", { curationStatus: "accepted", title: "Okafor on memory" }),
    make("unr", { title: "Unrelated" }),
    ...Array.from({ length: 30 }, (_, index) => make(`bulk${index}`, { title: `Shared topic ${index}`, createdAt: `2026-11-01T11:${String(index).padStart(2, "0")}:00.000Z` })),
  ];
  const all = previewSearch(records, { query: "okafor", show: "all", limit: 24, cursor: null });
  assert.deepEqual(all.items.map((item) => item.reference.lineageId).sort(), ["acc", "rej"]);
  assert.deepEqual(previewSearch(records, { query: "okafor", show: "rated", limit: 24, cursor: null }).items.length, 2);
  assert.deepEqual(previewSearch(records, { query: "okafor", show: "unrated", limit: 24, cursor: null }).items, []);
  assert.deepEqual(previewSearch(records, { query: "Marta Okafor", show: "all", limit: 24, cursor: null }).items.map((item) => [item.reference.lineageId, item.matchedFields]), [["rej", ["authors"]]]);
  const seen: string[] = [];
  let cursor: string | null = null;
  for (let pages = 0; pages < 5; pages += 1) {
    const page = previewSearch(records, { query: "shared topic", show: "all", limit: 12, cursor });
    seen.push(...page.items.map((item) => item.reference.lineageId!));
    cursor = page.nextCursor;
    if (!cursor) break;
  }
  assert.equal(seen.length, 30);
  assert.equal(new Set(seen).size, 30, "paging never repeats a card");
});

test("the preview matcher can stand in for meaning, which is listed after the word matches", () => {
  const records = [make("words", { title: "Memory chips" }), make("meaning", { title: "Recall in assistants" }), make("both", { title: "Memory and recall" })];
  const page = previewSearch(records, { query: "memory", show: "all", limit: 24, cursor: null }, { meaning: { memory: ["recall"] } });
  assert.deepEqual(page.items.map((item) => [item.reference.lineageId, item.matchedBy]), [["both", ["keyword", "meaning"]], ["words", ["keyword"]], ["meaning", ["meaning"]]]);
});

test("the preview matcher orders by newest or quality and keeps a minimum of stars, like the site's search", () => {
  const records = [
    make("a", { title: "Topic a", starRating: 5, createdAt: "2026-11-01T10:00:00.000Z" }), make("b", { title: "Topic b", starRating: 3, createdAt: "2026-11-02T10:00:00.000Z" }),
    make("c", { title: "Topic c", createdAt: "2026-11-03T10:00:00.000Z" }), make("d", { title: "Topic d", starRating: 5, createdAt: "2026-11-04T10:00:00.000Z" }),
    make("e", { title: "Topic e", starRating: 4.5, createdAt: "2026-11-05T10:00:00.000Z" }),
  ];
  const ask = (extra: Partial<Parameters<typeof previewSearch>[1]>) => previewSearch(records, { query: "topic", show: "all", limit: 24, cursor: null, ...extra }).items.map((item) => item.reference.lineageId);
  assert.deepEqual(ask({ sort: "newest" }), ["e", "d", "c", "b", "a"]);
  assert.deepEqual(ask({ sort: "quality" }), ["d", "a", "b", "e", "c"], "an unstarred match is last, never lost; 4.5 is not a rating");
  assert.deepEqual(ask({ sort: "newest", minStars: 4 }), ["d", "a"]);
  assert.deepEqual(ask({ sort: "quality", minStars: 3 }), ["d", "a", "b"]);
  assert.deepEqual(ask({ minStars: 5 }).sort(), ["a", "d"], "relevance order with a minimum");
  assert.equal(ask({ minStars: null }).length, 5);
});

test("the in-browser search takes Captured and Reviewed Accepted like the site's", () => {
  const records = [
    make("a", { title: "Topic a", curationStatus: "accepted", captureState: "none" }),
    make("b", { title: "Topic b", curationStatus: "accepted", captureState: "full" }),
    make("c", { title: "Topic c", curationStatus: "rejected", captureState: "none" }),
    make("d", { title: "Topic d", captureState: "thin" }),
    make("e", { title: "Topic e", captureState: "running" }),
  ];
  const ids = (input: Partial<Parameters<typeof previewSearch>[1]>) => previewSearch(records, { query: "topic", show: "all", limit: 24, cursor: null, ...input }).items.map((item) => item.reference.lineageId).sort();
  assert.deepEqual(ids({}), ["a", "b", "c", "d", "e"]);
  assert.deepEqual(ids({ captured: "yes" }), ["b"]);
  assert.deepEqual(ids({ captured: "no" }), ["a", "c", "d", "e"], "thin, running and empty are not captured");
  assert.deepEqual(ids({ show: "accepted" }), ["a", "b"], "Reviewed Accepted never lists the rejected");
  assert.deepEqual(ids({ show: "rated" }), ["a", "b", "c"]);
  assert.deepEqual(ids({ show: "accepted", captured: "no" }), ["a"]);
});
