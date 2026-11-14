import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { compareLedgers, parseLedger, parseLedgers, SCHEMA_SOURCE } from "./lib/gsi-ledger";
import { RESERVED_MINUTES } from "../packages/papyrus/src/backend-deploy.mjs";
import { chunkReleases, dataStackSeconds, parseMeasurementFile, releaseBudget, secondsPerCreation } from "./lib/gsi-release-budget";
import { readSchema } from "./lib/schema-reader";

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

const PLUGIN_STYLE = `export function pluginSchemaDefinitions() {
  return {
    Vote: a
      .model({
        id: a.id().required(),
        tenantId: a.string(),
      })
      .disableOperations(["subscriptions"])
      .secondaryIndexes((index) => [index("tenantId").sortKeys(["id"]).name("votesByTenant").queryField("listVotesByTenant")])
      .authorization(staffOnly),
    Flag: a
      .model({
        id: a.id().required(),
      })
      .authorization(staffOnly),
    castVote: a
      .mutation()
      .arguments({ id: a.string().required() }),
  };
}
`;

test("a plugin's schema, whose models break the line before .model, is read like the core schema", () => {
  const ledger = parseLedger(PLUGIN_STYLE);
  assert.deepEqual([...ledger.keys()], ["Vote", "Flag"]);
  assert.deepEqual(ledger.get("Vote"), [{ id: "votesByTenant", keys: "tenantId|id" }]);
  assert.deepEqual(ledger.get("Flag"), []);
});

test("one model declared in two schema files fails", () => {
  assert.throws(() => parseLedgers([{ path: "a.ts", source: PLUGIN_STYLE }, { path: "b.ts", source: PLUGIN_STYLE }]), /Vote is declared in both a.ts and b.ts/);
});

test("the schema sources hold every deployed model and every index of it", () => {
  const paths = execFileSync("git", ["ls-files", "--", "amplify"], { encoding: "utf8" }).split("\n").filter((path) => SCHEMA_SOURCE.test(path));
  const ledger = parseLedgers(paths.map((path) => ({ path, source: readFileSync(path, "utf8") })));
  for (const model of readSchema().models) {
    assert.ok(ledger.has(model.name), `${model.name} is in no schema source the ledger reads`);
    assert.equal(ledger.get(model.name)!.length, model.indexes.length, `${model.name} index count`);
  }
});

// The release budget: index creations that fit the build timeout, from the measured seconds per creation.
const measurementFile = () => parseMeasurementFile(JSON.parse(readFileSync(join(process.cwd(), "scripts/data/gsi-deploy-measurements.json"), "utf8")));
const withTables = (count: number, indexed: boolean) =>
  new Map(Array.from({ length: count }, (_, i): [string, { id: string; keys: string }[]] => [`Table${i}`, indexed ? [{ id: `table${i}ByTenant`, keys: "tenantId|id" }] : []]));

test("the budget comes from the measurement: job 107 took 3250 s for 23 index creations", () => {
  const file = measurementFile();
  assert.equal(file.measurements[0].date, "2026-11-14");
  assert.equal(Math.round(secondsPerCreation(file.measurements[0])), 141);
  // (120 - 10 minutes) * 60 * (1 - 0.25) / 141.3 s = 35.0
  const budget = releaseBudget(file, 120);
  assert.equal(budget.limit, 35);
  // At Amplify's own default of 30 minutes the same release fits 6 creations; the measurement says job 107's 23 never fitted.
  assert.equal(releaseBudget(file, 30).limit, 6);
  assert.ok(releaseBudget(file, 30).limit < file.measurements[0].indexCreations);
});

test("the slowest measurement holds, so a later fast release never loosens the budget", () => {
  const file = measurementFile();
  const faster = { ...file, measurements: [...file.measurements, { date: "2026-12-01", label: "later", indexCreations: 20, deploySeconds: 400 }] };
  assert.equal(releaseBudget(faster, 120).limit, 35);
  const slower = { ...file, measurements: [...file.measurements, { date: "2026-12-01", label: "later", indexCreations: 10, deploySeconds: 3000 }] };
  assert.equal(releaseBudget(slower, 120).limit, 16);
});

test("the budget reserves what the backend deploy command reserves, and an empty or invalid file is refused", () => {
  assert.equal(measurementFile().reservedMinutes, RESERVED_MINUTES);
  assert.throws(() => parseMeasurementFile({ reservedMinutes: 10, safetyMargin: 0.25, measurements: [] }), /holds no measurement/);
  assert.throws(() => parseMeasurementFile({ reservedMinutes: 10, safetyMargin: 1, measurements: [] }), /safetyMargin/);
  assert.throws(() => parseMeasurementFile({ reservedMinutes: 10, safetyMargin: 0.25, measurements: [{ date: "x", indexCreations: 0, deploySeconds: 5 }] }), /needs a date/);
});

test("a release that adds one index to each of 40 tables fails, naming the tables, the limit and releases 1 and 2", () => {
  const budget = releaseBudget(measurementFile(), 120);
  const report = compareLedgers(withTables(40, false), withTables(40, true), budget);
  assert.equal(report.creations, 40);
  assert.equal(report.failures.length, 1);
  assert.match(report.failures[0], /creates 40 indexes on existing tables \(Table0\.table0ByTenant, Table1\./);
  assert.match(report.failures[0], /only 35 fit one release/);
  assert.match(report.failures[0], /141 s per creation \(measured 2026-11-14\)/);
  assert.equal(report.releaseOrder.length, 2);
  assert.match(report.releaseOrder[0], /^release 1: Table0\.table0ByTenant, .*Table34\.table34ByTenant$/);
  assert.equal(report.releaseOrder[1], "release 2: Table35.table35ByTenant, Table36.table36ByTenant, Table37.table37ByTenant, Table38.table38ByTenant, Table39.table39ByTenant");
});

test("with a 60 minute build timeout the same release is listed as releases 1, 2 and 3", () => {
  const budget = releaseBudget(measurementFile(), 60);
  assert.equal(budget.limit, 15);
  const report = compareLedgers(withTables(40, false), withTables(40, true), budget);
  assert.equal(report.releaseOrder.length, 3);
  assert.deepEqual(report.releaseOrder.map((line) => line.split(": ")[1].split(", ").length), [15, 15, 10]);
});

test("a release that adds one index to each of 5 tables passes and prints its estimated deploy minutes", () => {
  const report = compareLedgers(withTables(5, false), withTables(5, true), releaseBudget(measurementFile(), 120));
  assert.deepEqual(report.failures, []);
  assert.match(report.estimate!, /^5 index creations on existing tables: about 12 minutes of deploy; 35 index creations fit one release/);
  assert.equal(report.releaseOrder.length, 1);
});

test("a release exactly at the limit passes and one more fails; indexes of a new table do not count", () => {
  const budget = releaseBudget(measurementFile(), 120);
  assert.deepEqual(compareLedgers(withTables(35, false), withTables(35, true), budget).failures, []);
  assert.equal(compareLedgers(withTables(36, false), withTables(36, true), budget).failures.length, 1);
  const created = compareLedgers(new Map(), withTables(100, true), budget);
  assert.equal(created.creations, 0);
  assert.deepEqual(created.failures, []);
});

test("a table's second pending index waits for the next release even inside the budget split", () => {
  const groups: [string, string][][] = [[["A", "a1"], ["B", "b1"], ["C", "c1"]], [["A", "a2"]]];
  assert.deepEqual(chunkReleases(groups, 2).map((release) => release.map(([table, id]) => `${table}.${id}`)), [["A.a1", "B.b1"], ["C.c1"], ["A.a2"]]);
});

test("the data stack duration comes from the root stack's events, and an unfinished update is refused", () => {
  const event = (status: string, time: string) => ({ LogicalResourceId: "data7552DF31", ResourceType: "AWS::CloudFormation::Stack", ResourceStatus: status, Timestamp: time });
  const events = [event("UPDATE_COMPLETE", "2026-11-10T10:00:00Z"), event("UPDATE_IN_PROGRESS", "2026-11-14T17:59:16Z"), event("UPDATE_COMPLETE", "2026-11-14T18:53:26Z"), event("UPDATE_IN_PROGRESS", "2026-11-09T10:00:00Z")];
  assert.equal(dataStackSeconds(events), 3250);
  assert.throws(() => dataStackSeconds([event("UPDATE_IN_PROGRESS", "2026-11-14T17:59:16Z")]), /has not finished/);
  assert.throws(() => dataStackSeconds([]), /no data stack update/);
});
