/** The "Accepted automatically" list: how a page is read, what is in it, and the address that opens it. Pure logic, no browser, no AWS. */
import assert from "node:assert/strict";
import type { ReferenceRecord } from "../lib/category-repository";
import {
  AUTO_ACCEPTED_EMPTY_TEXT,
  AUTO_ACCEPTED_PAGE_SIZE,
  autoAcceptedBy,
  autoAcceptedFromRecords,
  autoAcceptedServerFilter,
  collectAutoAcceptedPage,
  confidenceFromReason,
  laterVoteRecord,
} from "../lib/auto-accepted-references";
import { createLocalPreviewReferences } from "../lib/local-preview-seed";
import { referenceListFilterFromSearch, referenceListFilterToUrlStatus } from "../lib/newsroom-references";

const base = Date.parse("2026-11-01T00:00:00.000Z");

function reference(index: number, actor: string): ReferenceRecord {
  return {
    id: `reference-${index}`,
    lineageId: `lineage-${index}`,
    versionNumber: 1,
    versionState: "current",
    corpusId: "knowledge-corpus-test",
    externalItemId: `source-${index}`,
    title: `Reference ${index}`,
    curationStatus: "accepted",
    curationStatusUpdatedBy: actor,
    curationStatusUpdatedAt: new Date(base - index * 60_000).toISOString(),
    curationStatusReason: actor.startsWith("auto:") ? "Accepted automatically by the Cyclotron: it was 95.0% sure this is relevant." : "Primary source.",
  } as ReferenceRecord;
}

/** A database whose accepted partition holds `total` References, newest first, one in `every` accepted by the Cyclotron. It counts its reads. */
function partition(total: number, every: number, readSize = 200) {
  const rows = Array.from({ length: total }, (_, index) => reference(index, index % every === 0 ? "auto:cyclotron" : "editor@example.test"));
  const reads: Array<string | null> = [];
  let rowsLookedAt = 0;
  return {
    rows,
    reads,
    get rowsLookedAt() { return rowsLookedAt; },
    // Like DynamoDB: look at `readSize` rows, then apply the filter to them.
    read: async (token: string | null) => {
      reads.push(token);
      const start = token ? Number(token) : 0;
      const window = rows.slice(start, start + readSize);
      rowsLookedAt += window.length;
      const next = start + window.length;
      return { items: window.filter((row) => row.curationStatusUpdatedBy?.startsWith("auto:")), nextToken: next < rows.length ? String(next) : null };
    },
  };
}

const cases: Record<string, () => Promise<void> | void> = {
  "the filter names both automatic actors and only current References": () => {
    const filter = autoAcceptedServerFilter("knowledge-corpus-test") as Record<string, unknown>;
    assert.deepEqual(filter.versionState, { eq: "current" });
    assert.deepEqual(filter.or, [{ curationStatusUpdatedBy: { eq: "auto:cyclotron" } }, { curationStatusUpdatedBy: { eq: "auto:rule" } }]);
    assert.deepEqual(filter.corpusId, { eq: "knowledge-corpus-test" });
    assert.equal("corpusId" in (autoAcceptedServerFilter() as object), false);
  },

  "a page is filled from the newest end and stops there": async () => {
    const database = partition(5000, 20);   // 250 automatic, spread through 5000 accepted
    const page = await collectAutoAcceptedPage(database.read);
    // A page is whole database reads, so it can hold a few more than the size asked for; none is dropped, the cursor is after them all.
    assert.ok(page.items.length >= AUTO_ACCEPTED_PAGE_SIZE && page.items.length < AUTO_ACCEPTED_PAGE_SIZE + 10, `${page.items.length} items`);
    assert.equal(page.hasMore, true);
    assert.ok(database.rowsLookedAt <= 600, `looked at ${database.rowsLookedAt} of 5000 rows`);
    assert.deepEqual(page.items.map((item) => item.id), database.rows.filter((row) => row.curationStatusUpdatedBy === "auto:cyclotron").slice(0, page.items.length).map((row) => row.id));
    const times = page.items.map((item) => Date.parse(item.curationStatusUpdatedAt!));
    assert.deepEqual([...times].sort((a, b) => b - a), times, "newest acceptance first");
  },

  "the next page continues where the last stopped and walks to the end": async () => {
    const database = partition(2000, 10);   // 200 automatic
    const seen: string[] = [];
    let token: string | null = null;
    let pages = 0;
    do {
      const page = await collectAutoAcceptedPage(database.read, { nextToken: token });
      seen.push(...page.items.map((item) => item.id));
      token = page.nextToken;
      pages += 1;
    } while (token);
    assert.equal(new Set(seen).size, 200, "every automatic acceptance exactly once");
    assert.equal(seen.length, 200);
    assert.ok(pages >= 4 && pages <= 10, `${pages} pages`);
  },

  "a database page with no match is not the end of the list": async () => {
    const database = partition(1000, 999);   // only rows 0 and 999 are automatic
    const page = await collectAutoAcceptedPage(database.read);
    assert.deepEqual(page.items.map((item) => item.id), ["reference-0", "reference-999"]);
    assert.equal(page.hasMore, false);
  },

  "an editor's acceptance is never listed, even from an unfiltered read": async () => {
    const rows = [reference(0, "editor@example.test"), reference(1, "auto:rule"), reference(2, "auto:cyclotron"), { ...reference(3, "auto:cyclotron"), curationStatus: "rejected" }, { ...reference(4, "auto:cyclotron"), versionState: "superseded" }];
    const page = await collectAutoAcceptedPage(async () => ({ items: rows, nextToken: null }));
    assert.deepEqual(page.items.map((item) => item.id), ["reference-1", "reference-2"]);
    assert.deepEqual(autoAcceptedFromRecords(rows).map((item) => item.id), ["reference-1", "reference-2"]);
  },

  "the rule and the Cyclotron are told apart": () => {
    assert.equal(autoAcceptedBy(reference(0, "auto:rule")), "rule");
    assert.equal(autoAcceptedBy(reference(0, "auto:cyclotron")), "cyclotron");
    assert.equal(confidenceFromReason("Accepted automatically by the Cyclotron: it was 95.0% sure this is relevant, at or above the 90.0% learned."), 0.95);
    assert.equal(confidenceFromReason("Accepted automatically by the hn monitor's rule (every collected item): no relevance prediction."), null);
    assert.equal(confidenceFromReason(null), null);
  },

  "a later vote in this session replaces the copy that was read": () => {
    const read = reference(1, "auto:cyclotron");
    const rejected = { ...read, curationStatus: "rejected", curationStatusUpdatedBy: "editor@example.test", curationStatusUpdatedAt: new Date(base + 60_000).toISOString() } as ReferenceRecord;
    const older = { ...read, curationStatus: "pending", curationStatusUpdatedAt: new Date(base - 3_600_000).toISOString() } as ReferenceRecord;
    assert.equal(laterVoteRecord(read, rejected).curationStatus, "rejected");
    assert.equal(laterVoteRecord(read, older).curationStatus, "accepted", "a copy loaded before the acceptance does not hide it");
    assert.equal(laterVoteRecord(read, undefined), read);
  },

  "the address ?status=auto-accepted opens the list": () => {
    assert.equal(referenceListFilterFromSearch("?status=auto-accepted"), "auto_accepted");
    assert.equal(referenceListFilterFromSearch("?order=imported&status=Auto-Accepted"), "auto_accepted");
    assert.equal(referenceListFilterFromSearch("?status=rejected"), "rejected");
    assert.equal(referenceListFilterFromSearch("?status=exclude-pending"), null);
    assert.equal(referenceListFilterFromSearch(""), null);
    assert.equal(referenceListFilterToUrlStatus("auto_accepted"), "auto-accepted");
    assert.equal(referenceListFilterToUrlStatus("all"), "");
    assert.equal(referenceListFilterToUrlStatus("pending"), "pending");
  },

  "the empty state says in plain words what is missing": () => {
    assert.match(AUTO_ACCEPTED_EMPTY_TEXT, /Nothing has been accepted automatically yet/);
    assert.doesNotMatch(AUTO_ACCEPTED_EMPTY_TEXT, /auto-approved|desk|organization/i);
  },

  "the preview data carries both kinds of automatic acceptance and an editor's one": () => {
    const all = createLocalPreviewReferences();
    const listed = autoAcceptedFromRecords(all);
    assert.deepEqual(new Set(listed.map(autoAcceptedBy)), new Set(["rule", "cyclotron"]));
    assert.ok(all.some((item) => item.curationStatus === "accepted" && !listed.includes(item)), "an editor's accepted Reference stays out");
  },
};

const requested = process.argv.slice(2);
const names = requested.length ? requested : Object.keys(cases);
async function main() {
let failed = 0;
for (const name of names) {
  const run = cases[name];
  if (!run) { console.error(`no case named: ${name}`); process.exit(2); }
  try { await run(); console.log(`ok - ${name}`); } catch (error) { failed += 1; console.error(`not ok - ${name}\n${error instanceof Error ? error.stack : error}`); }
}
if (failed) process.exit(1);
}
void main();
