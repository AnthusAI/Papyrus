/**
 * The tenant isolation case table (PPY-65e5a9) must cover every model, index, custom operation and function of the deployed schema.
 * `npm test` runs this in CI, so a model added to schema.ts without regenerating the table fails here, naming the model.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCaseTable, check, findFindings, generatedBlock, missingCases, readFunctions, readSchema, type CaseTable, type SchemaInfo,
} from "./generate-tenant-isolation-cases";

const schema = readSchema();
const functions = readFunctions();
const table = buildCaseTable(schema, functions);

test("the committed case table and feature are up to date", () => {
  assert.deepEqual(check(), [], "run: npx tsx scripts/generate-tenant-isolation-cases.ts");
});

test("a model without a case fails, naming the model", () => {
  const without: CaseTable = { ...table, cases: table.cases.filter((entry) => !(entry.kind === "model" && entry.subject === "Reference")) };
  assert.ok(missingCases(schema, functions, without).includes("model Reference has no isolation case"));
});

test("an index, an operation and a function without a case fail, naming each", () => {
  const index = schema.models.flatMap((model) => model.indexes)[0].queryField;
  const operation = schema.operations[0].name;
  const directory = functions[0].directory;
  const without: CaseTable = { ...table, cases: table.cases.filter((entry) => ![`index:${index}`, `operation:${operation}`, `function:${directory}`].includes(entry.id)) };
  const problems = missingCases(schema, functions, without);
  assert.ok(problems.includes(`index ${index} has no isolation case`), problems.join("\n"));
  assert.ok(problems.includes(`operation ${operation} has no isolation case`), problems.join("\n"));
  assert.ok(problems.includes(`function ${directory} has no isolation case`), problems.join("\n"));
});

test("a case for a removed model fails, naming the model", () => {
  const ghost = { ...table.cases[0], id: "model:Ghost:get", subject: "Ghost" };
  assert.ok(missingCases(schema, functions, { ...table, cases: [...table.cases, ghost] }).some((problem) => problem.startsWith("model Ghost has a case but no longer exists")));
});

test("every model, plugin models included, and every function has a case", () => {
  const names = new Set(table.cases.filter((entry) => entry.kind === "model").map((entry) => entry.subject));
  for (const model of ["Item", "Reference", "Message", "SignupEntry", "NewsletterSubscriber"]) {
    assert.ok(schema.models.some((entry) => entry.name === model) === names.has(model), model);
  }
  for (const model of schema.models) assert.ok(names.has(model.name), model.name);
  for (const fn of functions) assert.ok(table.cases.some((entry) => entry.id === `function:${fn.directory}`), fn.directory);
  assert.ok(functions.some((fn) => fn.directory === "knowledge-query"));
});

test("the model cases follow the operations a model exposes", () => {
  const item = table.cases.filter((entry) => entry.kind === "model" && entry.subject === "Item").map((entry) => entry.operation);
  assert.deepEqual(item.sort(), ["create-with-foreign-tenantId", "delete-foreign-row", "get", "list", "list-filtered-to-foreign-tenant", "update-foreign-row", "update-to-foreign-tenantId"]);
  const handle = table.cases.filter((entry) => entry.kind === "model" && entry.subject === "PublicHandleClaim");
  assert.ok(handle.every((entry) => entry.expect.startsWith("reviewed:")));
  assert.ok(!table.cases.some((entry) => entry.kind === "subscription" && entry.subject === "Item"));
});

test("findings name a changeable tenantId and an unprefixed index from the spikes", () => {
  const fake: SchemaInfo = {
    operations: [],
    models: [{
      name: "Thing", hasTenantId: true, global: false, operations: ["get"], subscriptions: [],
      indexes: [{ queryField: "thingsByStatus", partitionKey: "status", sortKeys: [] }, { queryField: "thingsByTenant", partitionKey: "tenantKey", sortKeys: [] }],
      rules: [{ allow: "groups", groups: ["editor"] }], tenantIdFieldRules: [],
    }],
  };
  const codes = findFindings(fake).map((finding) => `${finding.code}:${finding.subject}`);
  assert.deepEqual(codes.sort(), ["index-not-tenant-prefixed:thingsByStatus", "no-tenant-claim-rule:Thing", "tenantId-can-be-changed:Thing"]);
  const locked: SchemaInfo = { operations: [], models: [{ ...fake.models[0], rules: [{ allow: "owner", ownerField: "tenantId", identityClaim: "papyrus_tenant_editor" }], tenantIdFieldRules: [{ allow: "owner" }], indexes: [] }] };
  assert.deepEqual(findFindings(locked), []);
});

test("the generated block is a Scenario Outline with an Examples row per case and is tagged pending", () => {
  const block = generatedBlock(table.cases);
  assert.equal(block.split("Scenario Outline:").length - 1, 6);
  assert.equal(block.split("@isolation-pending").length - 1, 6);
  assert.ok(block.includes("| Item "));
});
