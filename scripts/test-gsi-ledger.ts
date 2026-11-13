import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { compareLedgers, parseLedger } from "./lib/gsi-ledger";

const FIXTURES = join(process.cwd(), "features_backend/fixtures/gsi-ledger");
const fixture = (name: string) => readFileSync(join(FIXTURES, name), "utf8");

test("one new index on a table is allowed and shows in the release order", () => {
  const report = compareLedgers(parseLedger(fixture("baseline.ts")), parseLedger(fixture("one-new.ts")));
  assert.deepEqual(report.failures, []);
  assert.deepEqual(report.releaseOrder, ["release 1: Reference.referencesByTenant"]);
});

test("two new indexes on one table fail and name both", () => {
  const report = compareLedgers(parseLedger(fixture("baseline.ts")), parseLedger(fixture("two-new.ts")));
  assert.equal(report.failures.length, 1);
  assert.match(report.failures[0], /Reference/);
  assert.match(report.failures[0], /referencesByTenant/);
  assert.match(report.failures[0], /referencesByOwner/);
});

test("one new index on each of two tables is allowed", () => {
  const report = compareLedgers(parseLedger(fixture("baseline.ts")), parseLedger(fixture("one-each.ts")));
  assert.deepEqual(report.failures, []);
  assert.deepEqual(report.releaseOrder, ["release 1: Reference.referencesByTenant, Item.itemsByTenant"]);
});

test("an index that changes its keys in place fails", () => {
  const report = compareLedgers(parseLedger(fixture("baseline.ts")), parseLedger(fixture("changed-keys.ts")));
  assert.equal(report.failures.length, 1);
  assert.match(report.failures[0], /Item index itemsByStage changed its keys in place/);
});

test("a renamed index is a removal plus an addition, which is one new index", () => {
  const report = compareLedgers(parseLedger(fixture("baseline.ts")), parseLedger(fixture("renamed.ts")));
  assert.deepEqual(report.failures, []);
  assert.deepEqual(report.warnings, ["Item drops index itemsByStage."]);
});

test("a table past the DynamoDB limit fails and a changed table reports its remaining slots", () => {
  const withIndexes = (count: number) => parseLedger(
    `  Big: modelWithoutSubscriptions({ id: a.id() })\n    .secondaryIndexes((index) => [\n` +
      Array.from({ length: count }, (_, i) => `      index("k${i}").queryField("q${i}"),\n`).join("") + `    ]),\n`);
  const full = compareLedgers(withIndexes(19), withIndexes(20));
  assert.deepEqual(full.failures, []);
  assert.deepEqual(full.slots, ["Big has 20 of 20 indexes: 0 left."]);
  assert.deepEqual(compareLedgers(withIndexes(5), withIndexes(5)).slots, []);
  const over = compareLedgers(withIndexes(20), withIndexes(21));
  assert.match(over.failures[0], /Big has 21 indexes; DynamoDB allows 20/);
});
