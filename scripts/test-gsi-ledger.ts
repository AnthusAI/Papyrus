import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
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

test("a table near the DynamoDB limit warns, and one past 18 fails", () => {
  const withIndexes = (count: number) => parseLedger(
    `  Big: modelWithoutSubscriptions({ id: a.id() })\n    .secondaryIndexes((index) => [\n` +
      Array.from({ length: count }, (_, i) => `      index("k${i}").queryField("q${i}"),\n`).join("") + `    ]),\n`);
  assert.deepEqual(compareLedgers(withIndexes(15), withIndexes(15)).warnings, []);
  const near = compareLedgers(withIndexes(15), withIndexes(16));
  assert.deepEqual(near.failures, []);
  assert.match(near.warnings[0], /Big has 16 of the 20/);
  const over = compareLedgers(withIndexes(18), withIndexes(19));
  assert.match(over.failures[0], /Big has 19 indexes/);
  assert.deepEqual(compareLedgers(undefined, withIndexes(18)).failures, []);
});

test("the schema on this branch passes against the last release", (context) => {
  const base = process.env.GSI_LEDGER_BASE;
  let baseline: string | undefined;
  try {
    const ref = base ?? execFileSync("git", ["tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname"], { encoding: "utf8" })
      .split("\n").find((tag) => /^v\d+\.\d+\.\d+$/.test(tag));
    if (ref) baseline = execFileSync("git", ["show", `${ref}:amplify/data/schema.ts`], { encoding: "utf8", maxBuffer: 1 << 26 });
  } catch {
    baseline = undefined;
  }
  const current = parseLedger(readFileSync(join(process.cwd(), "amplify/data/schema.ts"), "utf8"));
  if (!baseline) context.diagnostic("no release tag is available locally; only the table-size limits were checked");
  const report = compareLedgers(baseline ? parseLedger(baseline) : undefined, current);
  for (const warning of report.warnings) context.diagnostic(`warning: ${warning}`);
  for (const line of report.releaseOrder) context.diagnostic(line);
  assert.deepEqual(report.failures, []);
});
