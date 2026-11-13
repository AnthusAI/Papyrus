/**
 * Generates docs/tenant-key-inventory.md from the deployed schema (PPY-cd5926; the multi-tenant plan is docs/plans/multi-tenant-architecture.md).
 *
 *   npx tsx scripts/generate-tenant-key-inventory.ts            write docs/tenant-key-inventory.md
 *   npx tsx scripts/generate-tenant-key-inventory.ts --check    fail (naming the model and index) when the written file is out of date or an
 *                                                               index partition field is not classified in scripts/lib/tenant-key-classes.ts
 *
 * The schema is read by scripts/lib/schema-reader.ts, the same reader the tenant isolation case table uses. Nothing here calls AWS.
 */
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { REPO_ROOT, readSchema, type ModelInfo, type SchemaInfo } from "./lib/schema-reader";
import { KEY_CLASSES, PARTITION_FIELD_CLASSES, type FieldClass, type KeyClass } from "./lib/tenant-key-classes";

export const DOC_PATH = "docs/tenant-key-inventory.md";

export type Classes = Record<string, FieldClass>;

export type IndexRow = {
  model: string;
  queryField: string;
  partitionKey: string;
  sortKeys: string[];
  classification: FieldClass;
  /** The partition field and every sort field are required in the schema, so every row of the model is in the index. */
  dense: boolean;
  /** Its keys cover every row of a tenant, and its class and spread let one or a few queries list a whole tenant once the value carries the tenant prefix. */
  listsTenant: boolean;
};

export type ModelStatus = "global" | "no-tenantId" | "no-index" | "lists-tenant" | "cannot-list-tenant";

export type ModelRow = { model: string; status: ModelStatus; indexes: number; listedBy: string[] };

export type Inventory = { indexes: IndexRow[]; models: ModelRow[] };

/** Every index whose partition field has no class: it stops an inventory being built. */
export function unclassifiedProblems(schema: SchemaInfo, classes: Classes): string[] {
  return schema.models.flatMap((model) => model.indexes
    .filter((index) => !classes[index.partitionKey])
    .map((index) => `${model.name} index ${index.queryField}: partition field ${index.partitionKey} is not classified (add it to scripts/lib/tenant-key-classes.ts)`));
}

/** Every class declared for a field that no index partitions on (any more). */
export function staleClassProblems(schema: SchemaInfo, classes: Classes): string[] {
  const used = new Set(schema.models.flatMap((model) => model.indexes.map((index) => index.partitionKey)));
  return Object.keys(classes).filter((field) => !used.has(field)).map((field) => `scripts/lib/tenant-key-classes.ts classifies ${field}, which no index partitions on any more`);
}

const isRequired = (model: ModelInfo, field: string) => model.fields[field]?.required === true;

const isDense = (model: ModelInfo, index: ModelInfo["indexes"][number]) => [index.partitionKey, ...index.sortKeys].every((field) => isRequired(model, field));

/** The tenant field: optional in the schema until the shared stack requires it, yet carried by every row of a tenant once the backfill has run. */
export const TENANT_FIELD = "tenantId";

/** Every partition field whose spread is `parent` must name a model of the schema as its parent, and only those may name one. */
export function parentProblems(schema: SchemaInfo, classes: Classes): string[] {
  const names = new Set(schema.models.map((model) => model.name));
  const used = new Set(schema.models.flatMap((model) => model.indexes.map((index) => index.partitionKey)));
  return Object.entries(classes).filter(([field]) => used.has(field)).flatMap(([field, value]) => {
    if (value.spread === "parent") return value.parent && names.has(value.parent) ? [] : [`scripts/lib/tenant-key-classes.ts gives ${field} the spread parent but no model of the schema as its parent`];
    return value.parent ? [`scripts/lib/tenant-key-classes.ts names a parent for ${field}, whose spread is not parent`] : [];
  });
}

/**
 * Whether an index can list every row of one tenant (once its value is prefixed, for a global value):
 * - its sort fields are required, and so is its partition field, except `tenantId`: a row without it belongs to no tenant yet, so an index on
 *   `tenantId` holds every row of every tenant once the tenantId backfill (PPY-8f9462) has stamped them;
 * - and its class is tenant-prefixed or global with spread one or closed, or its spread is `parent` and the parent model itself lists a tenant.
 */
function covers(model: ModelInfo, index: ModelInfo["indexes"][number]): boolean {
  return index.sortKeys.every((field) => isRequired(model, field)) && (index.partitionKey === TENANT_FIELD || isRequired(model, index.partitionKey));
}

export function buildInventory(schema: SchemaInfo, classes: Classes = PARTITION_FIELD_CLASSES): Inventory {
  const problems = [...unclassifiedProblems(schema, classes), ...parentProblems(schema, classes)];
  if (problems.length > 0) throw new Error(problems.join("\n"));
  const rowsByModel = new Map<string, IndexRow[]>(schema.models.map((model) => [model.name, model.indexes.map((index): IndexRow => {
    const classification = classes[index.partitionKey];
    const listable = (classification.class === "tenant-prefixed" || classification.class === "global") && (classification.spread === "one" || classification.spread === "closed");
    return {
      model: model.name, queryField: index.queryField, partitionKey: index.partitionKey, sortKeys: index.sortKeys, classification,
      dense: isDense(model, index), listsTenant: listable && covers(model, index),
    };
  })]));
  // A `parent` index lists a tenant once its parent model does; repeat until nothing changes, so a chain of parents resolves in any order.
  const listing = () => new Set([...rowsByModel].filter(([, rows]) => rows.some((row) => row.listsTenant)).map(([name]) => name));
  for (let changed = true; changed;) {
    changed = false;
    const listed = listing();
    for (const model of schema.models) {
      for (const [position, row] of rowsByModel.get(model.name)!.entries()) {
        if (row.listsTenant || row.classification.spread !== "parent" || !listed.has(row.classification.parent!)) continue;
        if (!covers(model, model.indexes[position])) continue;
        row.listsTenant = true;
        changed = true;
      }
    }
  }
  const indexes: IndexRow[] = [];
  const models: ModelRow[] = [];
  for (const model of schema.models) {
    const rows = rowsByModel.get(model.name)!;
    indexes.push(...rows);
    const listedBy = rows.filter((row) => row.listsTenant).map((row) => row.queryField);
    const status: ModelStatus = model.global ? "global"
      : !model.hasTenantId ? "no-tenantId"
      : rows.length === 0 ? "no-index"
      : listedBy.length > 0 ? "lists-tenant" : "cannot-list-tenant";
    models.push({ model: model.name, status, indexes: rows.length, listedBy });
  }
  return { indexes, models };
}

// ---------------------------------------------------------------------------------------------------------------------
// The document

const STATUS_TEXT: Record<ModelStatus, string> = {
  "global": "global by design",
  "no-tenantId": "no tenantId field",
  "no-index": "no index, needs a tenantId index",
  "lists-tenant": "yes",
  "cannot-list-tenant": "no, needs a tenantId index",
};

const sortText = (sortKeys: string[]) => (sortKeys.length ? sortKeys.map((key) => `\`${key}\``).join(", ") : "none");
const indexLine = (row: IndexRow) =>
  `| \`${row.model}\` | \`${row.queryField}\` | \`${row.partitionKey}\` | ${sortText(row.sortKeys)} | ${row.classification.class} | ${row.classification.spread} | ${row.dense ? "yes" : "no"} | ${row.listsTenant ? "yes" : "no"} |`;
const modelLine = (row: ModelRow) =>
  `| \`${row.model}\` | ${row.indexes} | ${STATUS_TEXT[row.status]} | ${row.listedBy.map((name) => `\`${name}\``).join(", ")} |`;

export function render(inventory: Inventory, classes: Classes = PARTITION_FIELD_CLASSES): string {
  const count = (predicate: (row: IndexRow) => boolean) => inventory.indexes.filter(predicate).length;
  const models = (status: ModelStatus) => inventory.models.filter((row) => row.status === status);
  const needIndex = [...models("no-index"), ...models("cannot-list-tenant")];
  const lines: string[] = [
    "# Tenant key inventory",
    "",
    "<!-- Generated by scripts/generate-tenant-key-inventory.ts from the deployed schema. Do not edit by hand; run `npx tsx scripts/generate-tenant-key-inventory.ts`. CI runs it with --check. -->",
    "",
    "Every model, every index on it, and what its partition value is, for the multi-tenant work ([multi-tenancy](multi-tenancy.md), plan in `docs/plans/multi-tenant-architecture.md`, task PPY-cd5926). The schema is read from the GraphQL Amplify generates from `amplify/data/schema.ts` and every plugin's models, by the same reader the tenant isolation case table uses. How each partition field is classified is declared in `scripts/lib/tenant-key-classes.ts`; an index whose partition field is not declared there fails the check.",
    "",
    "## Classes",
    "",
    "- `tenant-prefixed`: the stored value already starts with `<tenant>#` (or is the tenant id). Only Item, PublishedItem, MediaAsset, PublishedMediaAsset and NewsroomSection are written this way, plus `tenantId` on the tenancy records.",
    "- `corpus-prefixed`: the value is a corpus id or starts with `<corpusId>#`. Tenant-safe once corpus ids are unique across tenants. A partition holds one corpus, so an index on a composite of the corpus id cannot list a tenant; an index on `corpusId` itself can, through the tenant's corpora (spread `parent`).",
    "- `record-id`: the value is, or is built from, another record's id. Tenant-safe because ids are unique, but a partition holds the rows of one record, so it cannot list a tenant.",
    "- `global`: any value shared across tenants (a constant, an enum, a slug, a person, a free-form key). Prefixing it with the tenant is what makes it tenant-safe.",
    "",
    "Spread is how many partitions one tenant's rows fall into: `one` (a constant or the tenant id), `closed` (a fixed set the caller can name, such as a status), `parent` (one partition per record of a parent model the tenant owns: `corpusId` has one per KnowledgeCorpus) or `open` (a value per record, slug, person or key). An index is dense when its partition field and every sort field are required in the schema, so every row of the model is in it (DynamoDB leaves a row out of an index when a key attribute is absent). The density rule reads the schema only: a field the schema leaves optional counts as absent even where the writers usually set it.",
    "",
    "An index lists a tenant when its keys cover every row of the tenant and one or a few queries return them all. Its keys cover the tenant when it is dense, or when its partition is `tenantId` and its sort fields are required: `tenantId` stays optional in the schema until the shared stack requires it, but every row of a tenant carries it once the tenantId backfill (PPY-8f9462) has run, so a `tenantId` index is complete for a tenant only after that backfill. Its queries suffice when its class is `tenant-prefixed` or `global` and its spread is `one` or `closed` (with the tenant prefix on the value, one query, or one per value of the closed set), or when its spread is `parent` and the parent model lists a tenant (list the tenant's parents, then one query per parent: a tenant's References are its corpora's References).",
    "",
    "## Counts",
    "",
    `- ${inventory.models.length} models, ${inventory.indexes.length} indexes.`,
    `- Indexes by class: ${KEY_CLASSES.map((name: KeyClass) => `${name} ${count((row) => row.classification.class === name)}`).join(", ")}.`,
    `- Indexes that list a tenant once prefixed: ${count((row) => row.listsTenant)}; dense indexes: ${count((row) => row.dense)}.`,
    `- Models: ${models("lists-tenant").length} with an index that lists a tenant, ${needIndex.length} that need a tenantId index (the list for PPY-1ce06f), ${models("global").length} global by design, ${models("no-tenantId").length} with no tenantId field.`,
    "",
    "## Models",
    "",
    "| Model | Indexes | Can list one tenant's rows | Indexes that do |",
    "| --- | --- | --- | --- |",
    ...inventory.models.map(modelLine),
    "",
    "## Models that need a tenantId index",
    "",
    ...(needIndex.length ? needIndex.map((row) => `- \`${row.model}\` (${row.indexes === 0 ? "no index at all" : row.indexes === 1 ? "1 index, it does not list a tenant" : `${row.indexes} indexes, none lists a tenant`})`) : ["None."]),
    "",
    "## Partition fields",
    "",
    "| Partition field | Class | Spread | Used by |",
    "| --- | --- | --- | --- |",
    ...Object.keys(classes).sort().map((field) => {
      const users = [...new Set(inventory.indexes.filter((row) => row.partitionKey === field).map((row) => row.model))];
      const spread = classes[field].parent ? `${classes[field].spread} (\`${classes[field].parent}\`)` : classes[field].spread;
      return `| \`${field}\` | ${classes[field].class} | ${spread} | ${users.map((name) => `\`${name}\``).join(", ")} |`;
    }),
    "",
    "## Indexes",
    "",
    "| Model | Index | Partition | Sort | Class | Spread | Dense | Lists a tenant |",
    "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ...inventory.indexes.map(indexLine),
    "",
  ];
  return lines.join("\n");
}

// ---------------------------------------------------------------------------------------------------------------------
// Checking

/** The rows whose text differs between the committed document and the expected one, named by model and index. */
function staleRows(committed: string, expected: string, inventory: Inventory): string[] {
  const have = new Set(committed.split("\n"));
  const want = new Set(expected.split("\n"));
  const problems: string[] = [];
  for (const row of inventory.indexes) {
    if (!have.has(indexLine(row))) problems.push(`${row.model} index ${row.queryField} is missing or different in ${DOC_PATH}`);
  }
  for (const row of inventory.models) {
    if (!have.has(modelLine(row))) problems.push(`${row.model} is missing or different in ${DOC_PATH}`);
  }
  for (const line of committed.split("\n")) {
    const match = /^\| `([A-Za-z0-9]+)` \| `([A-Za-z0-9]+)` \| `/.exec(line);
    if (match && !want.has(line)) problems.push(`${match[1]} index ${match[2]} is in ${DOC_PATH} but not in the schema (or its row changed)`);
  }
  return [...new Set(problems)];
}

export type CheckOptions = { docPath?: string; schema?: SchemaInfo; classes?: Classes };

export function check(options: CheckOptions = {}): string[] {
  const docPath = options.docPath ?? path.join(REPO_ROOT, DOC_PATH);
  const schema = options.schema ?? readSchema();
  const classes = options.classes ?? PARTITION_FIELD_CLASSES;
  const problems = [...unclassifiedProblems(schema, classes), ...staleClassProblems(schema, classes), ...parentProblems(schema, classes)];
  if (problems.length > 0) return problems;
  const inventory = buildInventory(schema, classes);
  const expected = render(inventory, classes);
  let committed: string;
  try {
    committed = readFileSync(docPath, "utf8");
  } catch {
    return [`${path.relative(REPO_ROOT, docPath)} is missing or unreadable`];
  }
  if (committed === expected) return [];
  const named = staleRows(committed, expected, inventory);
  return named.length > 0 ? named : [`${path.relative(REPO_ROOT, docPath)} is out of date`];
}

export function write(): Inventory {
  const inventory = buildInventory(readSchema());
  writeFileSync(path.join(REPO_ROOT, DOC_PATH), render(inventory));
  return inventory;
}

function main(argv: string[]): number {
  const argument = (name: string) => { const at = argv.indexOf(name); return at === -1 ? undefined : argv[at + 1]; };
  if (argv.includes("--check")) {
    const classesPath = argument("--classes");
    const problems = check({
      docPath: argument("--doc"),
      classes: classesPath ? (JSON.parse(readFileSync(classesPath, "utf8")) as Classes) : undefined,
    });
    if (problems.length > 0) {
      console.error(["The tenant key inventory is not current:", ...problems.map((problem) => `  - ${problem}`), "", "Run: npx tsx scripts/generate-tenant-key-inventory.ts"].join("\n"));
      return 1;
    }
    console.log("The tenant key inventory is current and every index partition field is classified.");
    return 0;
  }
  const inventory = write();
  console.log(`Wrote ${inventory.indexes.length} indexes of ${inventory.models.length} models to ${DOC_PATH}.`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
