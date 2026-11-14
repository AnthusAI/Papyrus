/**
 * The tenant key inventory (PPY-cd5926): docs/tenant-key-inventory.md must be current, every index partition field must be classified, and the
 * declared classes must agree with what the key builders in src/papyrus_content/tenancy.py write. `npm test` runs this in CI.
 */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { buildInventory, check, parentProblems, render, staleClassProblems, unclassifiedProblems, type Classes } from "./generate-tenant-key-inventory";
import { REPO_ROOT, readSchema, type SchemaInfo } from "./lib/schema-reader";
import { KEY_CLASSES, PARTITION_FIELD_CLASSES } from "./lib/tenant-key-classes";

const schema = readSchema();

const fake = (indexes: SchemaInfo["models"][number]["indexes"], fields: Record<string, { required: boolean }>, extra: Partial<SchemaInfo["models"][number]> = {}): SchemaInfo => ({
  operations: [],
  models: [{ name: "Thing", hasTenantId: true, global: false, fields, operations: [], subscriptions: [], indexes, rules: [], tenantIdFieldRules: [], ...extra }],
});

test("the committed inventory is current", () => {
  assert.deepEqual(check(), [], "run: npx tsx scripts/generate-tenant-key-inventory.ts");
});

test("every index partition field of the deployed schema is classified, and no class is left over", () => {
  assert.deepEqual(unclassifiedProblems(schema, PARTITION_FIELD_CLASSES), []);
  assert.deepEqual(staleClassProblems(schema, PARTITION_FIELD_CLASSES), []);
});

test("a new index whose partition field is not classified fails, naming the model and index", () => {
  const added = fake([{ queryField: "listThingsByMood", partitionKey: "mood", sortKeys: [] }], { mood: { required: true } });
  assert.deepEqual(check({ schema: added, classes: PARTITION_FIELD_CLASSES }).slice(0, 1), [
    "Thing index listThingsByMood: partition field mood is not classified (add it to scripts/lib/tenant-key-classes.ts)",
  ]);
  assert.throws(() => buildInventory(added), /Thing index listThingsByMood/);
});

test("a class for a field no index partitions on fails, naming the field", () => {
  const classes: Classes = { ...PARTITION_FIELD_CLASSES, retiredField: { class: "global", spread: "open" } };
  assert.ok(staleClassProblems(schema, classes).some((problem) => problem.includes("retiredField")));
});

test("a changed index fails until the document is regenerated, naming the model and index", () => {
  const committed = readFileSync(path.join(REPO_ROOT, "docs/tenant-key-inventory.md"), "utf8");
  const changed = structuredClone(schema);
  const index = changed.models.find((model) => model.name === "Assignment")!.indexes.find((entry) => entry.queryField === "listAssignmentsByStatusAndUpdatedAt")!;
  index.sortKeys = ["createdAt"];
  const problems = check({ schema: changed, docPath: writeTemp(committed) });
  assert.ok(problems.includes("Assignment index listAssignmentsByStatusAndUpdatedAt is missing or different in docs/tenant-key-inventory.md"), problems.join("\n"));
});

test("a removed index fails, naming it", () => {
  const committed = readFileSync(path.join(REPO_ROOT, "docs/tenant-key-inventory.md"), "utf8");
  const fewer = structuredClone(schema);
  const model = fewer.models.find((entry) => entry.name === "Message")!;
  model.indexes = model.indexes.filter((entry) => entry.queryField !== "listMessagesByStatusAndCreatedAt");
  const problems = check({ schema: fewer, docPath: writeTemp(committed) });
  assert.ok(problems.some((problem) => problem.startsWith("Message index listMessagesByStatusAndCreatedAt is in docs/tenant-key-inventory.md")), problems.join("\n"));
});

test("an index lists a tenant only when it is dense, tenant-safe to prefix and spread over a closed set", () => {
  const required = { status: { required: true }, createdAt: { required: true }, slug: { required: true }, lineageId: { required: true }, mood: { required: false } };
  const inventory = buildInventory(fake([
    { queryField: "byStatus", partitionKey: "status", sortKeys: ["createdAt"] },
    { queryField: "bySlug", partitionKey: "slug", sortKeys: [] },
    { queryField: "byLineage", partitionKey: "lineageId", sortKeys: [] },
    { queryField: "byStatusSparse", partitionKey: "status", sortKeys: ["mood"] },
  ], required));
  const listed = Object.fromEntries(inventory.indexes.map((row) => [row.queryField, row.listsTenant]));
  assert.deepEqual(listed, { byStatus: true, bySlug: false, byLineage: false, byStatusSparse: false });
  assert.equal(inventory.models[0].status, "lists-tenant");
  const none = buildInventory(fake([{ queryField: "bySlug", partitionKey: "slug", sortKeys: [] }], required));
  assert.equal(none.models[0].status, "cannot-list-tenant");
  assert.equal(buildInventory(fake([], required)).models[0].status, "no-index");
  assert.equal(buildInventory(fake([], required, { global: true })).models[0].status, "global");
  assert.equal(buildInventory(fake([], required, { hasTenantId: false })).models[0].status, "no-tenantId");
});

test("an index on tenantId lists a tenant though tenantId is optional, as long as its sort fields are required", () => {
  const fields = { tenantId: { required: false }, id: { required: true }, mood: { required: false } };
  const inventory = buildInventory(fake([
    { queryField: "byTenant", partitionKey: "tenantId", sortKeys: ["id"] },
    { queryField: "byTenantAndMood", partitionKey: "tenantId", sortKeys: ["mood"] },
  ], fields));
  const rows = Object.fromEntries(inventory.indexes.map((row) => [row.queryField, [row.dense, row.listsTenant]]));
  assert.deepEqual(rows, { byTenant: [false, true], byTenantAndMood: [false, false] });
  assert.equal(inventory.models[0].status, "lists-tenant");
});

test("an index spread over a parent model lists a tenant only when the parent model does", () => {
  const classes: Classes = { ...PARTITION_FIELD_CLASSES, shelfId: { class: "record-id", spread: "parent", parent: "Shelf" } };
  const shelf = (indexes: SchemaInfo["models"][number]["indexes"]) => ({
    name: "Shelf", hasTenantId: true, global: false, fields: { status: { required: true } }, operations: [], subscriptions: [], indexes, rules: [], tenantIdFieldRules: [],
  });
  const book = { name: "Book", hasTenantId: true, global: false, fields: { shelfId: { required: true }, title: { required: false } }, operations: [], subscriptions: [],
    indexes: [{ queryField: "byShelf", partitionKey: "shelfId", sortKeys: [] }, { queryField: "byShelfAndTitle", partitionKey: "shelfId", sortKeys: ["title"] }], rules: [], tenantIdFieldRules: [] };
  const listable = buildInventory({ operations: [], models: [book, shelf([{ queryField: "byStatus", partitionKey: "status", sortKeys: [] }])] }, classes);
  assert.deepEqual(listable.models.find((row) => row.model === "Book")?.listedBy, ["byShelf"]);
  const unlistable = buildInventory({ operations: [], models: [book, shelf([])] }, classes);
  assert.equal(unlistable.models.find((row) => row.model === "Book")?.status, "cannot-list-tenant");
  const orphan: Classes = { ...PARTITION_FIELD_CLASSES, shelfId: { class: "record-id", spread: "parent", parent: "Cupboard" } };
  assert.match(parentProblems({ operations: [], models: [book, shelf([])] }, orphan).join("\n"), /shelfId/);
  assert.deepEqual(parentProblems(schema, PARTITION_FIELD_CLASSES), []);
});

test("References are listed by tenant through their corpora, never through a new index", () => {
  const inventory = buildInventory(schema);
  assert.equal(PARTITION_FIELD_CLASSES.corpusId.parent, "KnowledgeCorpus");
  assert.equal(inventory.models.find((row) => row.model === "KnowledgeCorpus")?.status, "lists-tenant");
  assert.deepEqual(inventory.models.find((row) => row.model === "Reference")?.listedBy, ["listReferencesByCorpusAndExternalItem"]);
  assert.ok(!schema.models.find((model) => model.name === "Reference")!.indexes.some((index) => index.partitionKey === "tenantId"));
});

test("the five tenant models and the global models are classified as the tenancy code writes them", () => {
  const python = readFileSync(path.join(REPO_ROOT, "src/papyrus_content/tenancy.py"), "utf8");
  const scoped = /TENANT_SCOPED_INDEX_FIELDS = \(([^)]*)\)/.exec(python)?.[1].match(/"([A-Za-z]+)"/g)?.map((name) => name.replace(/"/g, ""));
  const slug = /TENANT_SLUG_FIELD = "([A-Za-z]+)"/.exec(python)?.[1];
  assert.ok(scoped && scoped.length > 0 && slug, "tenancy.py no longer declares the tenant-prefixed fields where this test reads them");
  for (const field of [...scoped!, slug!]) assert.equal(PARTITION_FIELD_CLASSES[field]?.class, "tenant-prefixed", field);
  const prefixed = Object.entries(PARTITION_FIELD_CLASSES).filter(([, value]) => value.class === "tenant-prefixed").map(([name]) => name);
  assert.deepEqual(prefixed.sort(), [...scoped!, slug!, "tenantId"].sort());
  const inventory = buildInventory(schema);
  for (const name of ["UserProfile", "UserIdentity", "PublicHandleClaim"]) assert.equal(inventory.models.find((row) => row.model === name)?.status, "global", name);
  for (const field of ["feedStateKey", "starFeedKey", "mediumFeedKey", "contentNeededKey"]) assert.equal(PARTITION_FIELD_CLASSES[field].class, "corpus-prefixed", field);
  assert.equal(PARTITION_FIELD_CLASSES.newsroomFeedKey.class, "global");
  for (const field of ["assignmentId", "lineageId", "itemId", "importRunId", "editionId"]) assert.equal(PARTITION_FIELD_CLASSES[field].class, "record-id", field);
});

test("every model of the schema is in the inventory and the document counts add up", () => {
  const inventory = buildInventory(schema);
  assert.equal(inventory.models.length, schema.models.length);
  assert.equal(inventory.indexes.length, schema.models.reduce((total, model) => total + model.indexes.length, 0));
  const byClass = KEY_CLASSES.reduce((total, name) => total + inventory.indexes.filter((row) => row.classification.class === name).length, 0);
  assert.equal(byClass, inventory.indexes.length);
  assert.ok(render(inventory).includes(`${inventory.models.length} models, ${inventory.indexes.length} indexes.`));
});

function writeTemp(content: string): string {
  const file = path.join(mkdtempSync(path.join(tmpdir(), "tenant-key-inventory-")), "inventory.md");
  writeFileSync(file, content);
  return file;
}
