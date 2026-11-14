/** The Medium filter's pure parts: the address, the partitions a Reviewed choice reads, and the in-memory medium index. */
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReferenceRecord } from "../lib/category-repository";
import { feedMediumFromSearch, mediumFeedKeys, mediumReaderFromRecords, mediumRows, searchWithMedium } from "../lib/reference-medium-feed";

const record = (id: string, fields: Partial<ReferenceRecord> = {}) => ({ id, lineageId: id, corpusId: "c", versionState: "current", curationStatus: "pending", createdAt: "2026-11-01T00:00:00.000Z", ...fields }) as ReferenceRecord;

test("the address names the medium and an unknown value is All", () => {
  assert.equal(feedMediumFromSearch("?medium=video"), "video");
  assert.equal(feedMediumFromSearch("?reviewed=no&medium=video&sort=newest"), "video");
  assert.equal(feedMediumFromSearch("?medium=podcast"), "any");
  assert.equal(feedMediumFromSearch(""), "any");
  assert.equal(searchWithMedium("?sort=newest", "video"), "?sort=newest&medium=video");
  assert.equal(searchWithMedium("?sort=newest&medium=video", "any"), "?sort=newest");
  assert.equal(searchWithMedium("?medium=video", "any"), "");
});

test("Reviewed picks the vote partitions of the medium index, per corpus", () => {
  assert.deepEqual(mediumFeedKeys(["a", "b"], "video", "unrated"), ["a#video#pending", "b#video#pending"]);
  assert.deepEqual(mediumFeedKeys(["a"], "video", "accepted"), ["a#video#accepted"]);
  assert.deepEqual(mediumFeedKeys(["a"], "video", "rated"), ["a#video#accepted", "a#video#rejected"]);
  assert.deepEqual(mediumFeedKeys(["a", "a"], "video", "all"), ["a#video#pending", "a#video#accepted", "a#video#rejected"]);
});

test("the in-memory medium index lists a partition newest first and leaves out rows with no medium, archived and superseded rows", async () => {
  const read = mediumReaderFromRecords([
    record("old", { medium: "video", createdAt: "2026-10-01T00:00:00.000Z" }),
    record("new", { medium: "video" }),
    record("article"),
    record("archived", { medium: "video", curationStatus: "archived" }),
    record("superseded", { medium: "video", versionState: "superseded" }),
    record("accepted", { medium: "video", curationStatus: "accepted" }),
    record("other-corpus", { medium: "video", corpusId: "d" }),
  ]);
  const page = await read({ feedStateKey: "c#video#pending", sort: "newest", limit: 1, nextToken: null });
  assert.deepEqual(page.items.map((item) => item.id), ["new"]);
  assert.equal(page.nextToken, "1");
  const rest = await read({ feedStateKey: "c#video#pending", sort: "newest", limit: 5, nextToken: page.nextToken });
  assert.deepEqual(rest.items.map((item) => item.id), ["old"]);
  assert.equal(rest.nextToken, null);
});

test("rows read from the star partitions are kept for one medium", async () => {
  const rows = [record("v", { medium: "video" }), record("a")];
  const read = async () => ({ items: rows, nextToken: null });
  assert.deepEqual((await mediumRows(read, "video")({ feedStateKey: "k", sort: "newest", limit: 5, nextToken: null })).items.map((item) => item.id), ["v"]);
  assert.deepEqual((await mediumRows(read, "any")({ feedStateKey: "k", sort: "newest", limit: 5, nextToken: null })).items.map((item) => item.id), ["v", "a"]);
});
