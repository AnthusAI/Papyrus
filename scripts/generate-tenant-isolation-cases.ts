/**
 * Generates the cross-tenant case table from the deployed schema and the function list (PPY-65e5a9, part of the
 * adversarial suite PPY-29f730; spike findings in docs/plans/tenant-claims-spike-1.md and tenant-claims-spike-2-findings.md).
 *
 *   npx tsx scripts/generate-tenant-isolation-cases.ts            write the case table and the feature's generated block
 *   npx tsx scripts/generate-tenant-isolation-cases.ts --check    fail (naming the model, index, operation or function) when a
 *                                                                 case is missing, stale, or the written files are out of date
 *   npx tsx scripts/generate-tenant-isolation-cases.ts --report   print the known gaps found in the schema, never fails
 *
 * The source of truth is the GraphQL Amplify generates from `amplify/data/schema.ts` plus every plugin's definitions
 * (`schema.transform().schema`), so what is tested is what AppSync serves. The function list is the directories under
 * `amplify/functions` and each plugin's function directory. Nothing here calls AWS.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse, print, type DirectiveNode, type FieldDefinitionNode, type ObjectTypeDefinitionNode, type ValueNode } from "graphql";
import { schemaWithPlugins } from "../amplify/data/schema";
import { KNOWN_PLUGINS } from "../amplify/plugins/registry";

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const CASES_PATH = "features_backend/fixtures/tenant-isolation/cases.json";
export const FEATURE_PATH = "features_backend/tenant-isolation-adversarial.feature";
export const BEGIN_MARKER = "  # BEGIN GENERATED CASES (scripts/generate-tenant-isolation-cases.ts; do not edit by hand)";
export const END_MARKER = "  # END GENERATED CASES";
export const PENDING_TAG = "@isolation-pending";

/** Models that belong to no single tenant (people, sign-in identities, public handles). They carry no tenantId by design. */
export const GLOBAL_MODELS = ["UserProfile", "UserIdentity", "PublicHandleClaim"];

/** Directories under amplify/functions that are not functions. */
const NOT_FUNCTIONS = ["shared"];

export type CaseKind = "model" | "index" | "subscription" | "operation" | "function" | "surface";

export type IsolationCase = {
  id: string;
  kind: CaseKind;
  /** The model, index query field, operation, function directory or surface the case is about. */
  subject: string;
  operation: string;
  /** What the attacker does, in words a person can run by hand. */
  probe: string;
  /** What must be true afterwards. */
  expect: string;
};

export type Finding = { code: string; subject: string; note: string };

export type CaseTable = {
  generatedBy: string;
  summary: Record<string, number>;
  cases: IsolationCase[];
  findings: Finding[];
};

export type ModelInfo = {
  name: string;
  hasTenantId: boolean;
  global: boolean;
  operations: string[];
  subscriptions: string[];
  indexes: { queryField: string; partitionKey: string; sortKeys: string[] }[];
  rules: Rule[];
  tenantIdFieldRules: Rule[];
};

export type Rule = { allow: string; provider?: string; groups?: string[]; ownerField?: string; identityClaim?: string; operations?: string[] };

export type OperationInfo = { name: string; type: "Query" | "Mutation"; args: string[]; idArgs: string[]; handler: string | null; rules: Rule[] };

export type SchemaInfo = { models: ModelInfo[]; operations: OperationInfo[] };

// ---------------------------------------------------------------------------------------------------------------------
// Reading the schema

function plain(value: ValueNode): unknown {
  switch (value.kind) {
    case "StringValue": return value.value;
    case "EnumValue": return value.value;
    case "IntValue": return Number(value.value);
    case "FloatValue": return Number(value.value);
    case "BooleanValue": return value.value;
    case "NullValue": return null;
    case "ListValue": return value.values.map(plain);
    case "ObjectValue": return Object.fromEntries(value.fields.map((field) => [field.name.value, plain(field.value)]));
    default: return print(value);
  }
}

function directiveArguments(directive: DirectiveNode): Record<string, unknown> {
  return Object.fromEntries((directive.arguments ?? []).map((argument) => [argument.name.value, plain(argument.value)]));
}

function rulesOf(directives: readonly DirectiveNode[] | undefined): Rule[] {
  const auth = directives?.find((directive) => directive.name.value === "auth");
  if (!auth) return [];
  return ((directiveArguments(auth).rules as Rule[] | undefined) ?? []).map((rule) => ({ ...rule }));
}

function typeName(field: FieldDefinitionNode["type"]): string {
  return field.kind === "NamedType" ? field.name.value : typeName(field.type);
}

const MODEL_OPERATIONS: Record<string, string[]> = {
  queries: ["get", "list"],
  mutations: ["create", "update", "delete"],
  subscriptions: ["onCreate", "onUpdate", "onDelete"],
};

/** Which operations a model exposes, from its `@model(queries:, mutations:, subscriptions:)` arguments. */
function enabledOperations(model: Record<string, unknown>): { operations: string[]; subscriptions: string[] } {
  const enabled = new Set<string>();
  for (const [group, names] of Object.entries(MODEL_OPERATIONS)) {
    const setting = model[group];
    if (setting === null) continue;
    for (const name of names) {
      const individual = setting && typeof setting === "object" ? (setting as Record<string, unknown>)[name] : undefined;
      if (individual !== null) enabled.add(name);
    }
  }
  return {
    operations: [...MODEL_OPERATIONS.queries, ...MODEL_OPERATIONS.mutations].filter((name) => enabled.has(name)),
    subscriptions: MODEL_OPERATIONS.subscriptions.filter((name) => enabled.has(name)),
  };
}

/** The SDL of the deployed schema with every plugin enabled. */
export function deployedSchemaSdl(): string {
  const definitions = Object.assign({}, ...Object.values(KNOWN_PLUGINS).map((plugin) => plugin.schemaDefinitions()));
  return (schemaWithPlugins(definitions) as unknown as { transform(): { schema: string } }).transform().schema;
}

export function readSchema(sdl: string = deployedSchemaSdl()): SchemaInfo {
  const document = parse(sdl);
  const models: ModelInfo[] = [];
  const operations: OperationInfo[] = [];
  for (const definition of document.definitions) {
    if (definition.kind !== "ObjectTypeDefinition") continue;
    const type = definition as ObjectTypeDefinitionNode;
    const modelDirective = type.directives?.find((directive) => directive.name.value === "model");
    if (modelDirective) {
      const fields = type.fields ?? [];
      const indexes: ModelInfo["indexes"] = [];
      for (const field of fields) {
        for (const directive of field.directives ?? []) {
          if (directive.name.value !== "index") continue;
          const args = directiveArguments(directive);
          if (typeof args.queryField !== "string") continue;
          indexes.push({ queryField: args.queryField, partitionKey: field.name.value, sortKeys: (args.sortKeyFields as string[] | undefined) ?? [] });
        }
      }
      const tenantField = fields.find((field) => field.name.value === "tenantId");
      models.push({
        name: type.name.value,
        hasTenantId: tenantField !== undefined,
        global: GLOBAL_MODELS.includes(type.name.value),
        ...enabledOperations(directiveArguments(modelDirective)),
        indexes,
        rules: rulesOf(type.directives),
        tenantIdFieldRules: rulesOf(tenantField?.directives),
      });
    } else if (type.name.value === "Query" || type.name.value === "Mutation") {
      for (const field of type.fields ?? []) {
        const fn = field.directives?.find((directive) => directive.name.value === "function");
        const args = (field.arguments ?? []).map((argument) => ({ name: argument.name.value, type: typeName(argument.type) }));
        operations.push({
          name: field.name.value,
          type: type.name.value as "Query" | "Mutation",
          args: args.map((argument) => argument.name),
          idArgs: args.filter((argument) => argument.type === "ID" || /(^id$|Id$|Ids$|Key$)/.test(argument.name)).map((argument) => argument.name),
          handler: fn ? String(directiveArguments(fn).name) : null,
          rules: rulesOf(field.directives),
        });
      }
    }
  }
  models.sort((left, right) => left.name.localeCompare(right.name));
  operations.sort((left, right) => left.name.localeCompare(right.name));
  return { models, operations };
}

// ---------------------------------------------------------------------------------------------------------------------
// The function list

export type FunctionInfo = { directory: string; relativePath: string; appsyncName: string };

const pascal = (kebab: string) => kebab.split("-").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join("");

/** `amplify/functions/<dir>` and each plugin's `function` or `ops` directory that holds a resource or a handler. */
export function readFunctions(root: string = REPO_ROOT): FunctionInfo[] {
  const found: FunctionInfo[] = [];
  const functionsRoot = path.join(root, "amplify/functions");
  for (const entry of readdirSync(functionsRoot, { withFileTypes: true })) {
    if (!entry.isDirectory() || NOT_FUNCTIONS.includes(entry.name)) continue;
    found.push({ directory: entry.name, relativePath: `amplify/functions/${entry.name}`, appsyncName: `Fn${pascal(entry.name)}` });
  }
  const pluginsRoot = path.join(root, "amplify/plugins");
  for (const plugin of readdirSync(pluginsRoot, { withFileTypes: true })) {
    if (!plugin.isDirectory()) continue;
    for (const sub of ["function", "ops"]) {
      const directory = path.join(pluginsRoot, plugin.name, sub);
      if (!existsSync(directory)) continue;
      found.push({ directory: `${plugin.name}/${sub}`, relativePath: `amplify/plugins/${plugin.name}/${sub}`, appsyncName: `Fn${pascal(plugin.name)}` });
    }
  }
  return found.sort((left, right) => left.directory.localeCompare(right.directory));
}

// ---------------------------------------------------------------------------------------------------------------------
// Cases

const FOREIGN = "beta";
const DENIED = `denied, or returns nothing of "${FOREIGN}"`;

function modelCases(model: ModelInfo): IsolationCase[] {
  const subject = model.name;
  const has = (operation: string) => model.operations.includes(operation);
  const make = (operation: string, probe: string, expect: string = DENIED): IsolationCase => ({
    id: `model:${subject}:${operation}`, kind: "model", subject, operation, probe, expect,
  });
  const cases: IsolationCase[] = [];
  if (model.global) {
    // People, identities and handles are not tenant data. The case records the decision so a change to the model is noticed.
    if (has("get")) cases.push(make("get", `alpha gets a ${subject} row`, `reviewed: ${subject} is global and holds no tenant data`));
    if (has("list")) cases.push(make("list", `alpha lists ${subject} rows`, `reviewed: ${subject} is global and holds no tenant data`));
    for (const operation of ["create", "update", "delete"]) {
      if (has(operation)) cases.push(make(operation, `alpha ${operation}s a ${subject} row it does not own`, `reviewed: only the rule's own principals may ${operation} ${subject}`));
    }
    return cases;
  }
  if (has("get")) cases.push(make("get", `alpha gets "${FOREIGN}"'s ${subject} by id`));
  if (has("list")) {
    cases.push(make("list", `alpha lists ${subject} rows`, `no row of "${FOREIGN}" is returned and pages are not short`));
    cases.push(make("list-filtered-to-foreign-tenant", `alpha lists ${subject} rows with filter tenantId eq "${FOREIGN}"`));
  }
  if (has("create")) cases.push(make("create-with-foreign-tenantId", `alpha creates a ${subject} with tenantId "${FOREIGN}"`));
  if (has("update")) {
    cases.push(make("update-to-foreign-tenantId", `alpha updates its own ${subject} setting tenantId to "${FOREIGN}" (tenantId must be immutable)`));
    cases.push(make("update-foreign-row", `alpha updates "${FOREIGN}"'s ${subject}`));
  }
  if (has("delete")) cases.push(make("delete-foreign-row", `alpha deletes "${FOREIGN}"'s ${subject}`));
  return cases;
}

function indexCases(model: ModelInfo): IsolationCase[] {
  return model.indexes.map((index) => ({
    id: `index:${index.queryField}`,
    kind: "index" as const,
    subject: index.queryField,
    operation: "list-by-index-at-foreign-key",
    probe: `alpha calls ${index.queryField} on ${model.name} with ${index.partitionKey} at one of "${FOREIGN}"'s keys`,
    expect: model.global ? `reviewed: ${model.name} is global` : `returns nothing of "${FOREIGN}"`,
  }));
}

function subscriptionCases(model: ModelInfo): IsolationCase[] {
  return model.subscriptions.map((operation) => ({
    id: `subscription:${model.name}:${operation}`,
    kind: "subscription" as const,
    subject: model.name,
    operation,
    probe: `alpha subscribes to ${operation} on ${model.name} while "${FOREIGN}" writes`,
    expect: `alpha receives no event of "${FOREIGN}"`,
  }));
}

function operationCases(operation: OperationInfo): IsolationCase {
  const probe = operation.idArgs.length > 0
    ? `alpha calls ${operation.name} with "${FOREIGN}"'s ids for ${operation.idArgs.join(", ")}`
    : `alpha calls ${operation.name}${operation.args.length ? ` with ${operation.args.join(", ")} chosen to reach "${FOREIGN}"` : ""}`;
  return {
    id: `operation:${operation.name}`,
    kind: "operation",
    subject: operation.name,
    operation: operation.idArgs.length > 0 ? "call-with-foreign-ids" : "call-scope",
    probe,
    expect: DENIED,
  };
}

function functionCase(info: FunctionInfo): IsolationCase {
  return {
    id: `function:${info.directory}`,
    kind: "function",
    subject: info.directory,
    operation: "invoke-with-foreign-tenant-input",
    probe: `alpha reaches ${info.relativePath} (directly or through an operation) with an event naming "${FOREIGN}"`,
    expect: `reads and writes nothing of "${FOREIGN}"`,
  };
}

/** Surfaces outside the GraphQL schema, from the parent task PPY-29f730. Listed by hand: they have no schema to generate from. */
export const SURFACES: { id: string; operation: string; probe: string; expect: string }[] = [
  { id: "s3-presign-foreign-key", operation: "presign-foreign-key", probe: "alpha asks a presign function for a key under beta's prefix", expect: "refused" },
  { id: "s3-identity-pool-direct", operation: "direct-identity-pool-access", probe: "alpha's identity-pool credentials read and list beta's prefix directly", expect: "denied" },
  { id: "s3-rendition-paths", operation: "rendition-path-traversal", probe: "alpha requests a rendition path that resolves under beta's prefix", expect: "refused" },
  { id: "knowledge-search", operation: "search-foreign-corpus", probe: "alpha searches knowledge-query, the S3 Vectors index and the title-word table for beta's text", expect: "no hit of beta" },
  { id: "projection-outputs", operation: "inspect-tenant-files", probe: "alpha's snapshot and projection output files are scanned for beta's rows", expect: "no foreign rows" },
  { id: "edge-host-spoofing", operation: "spoof-host-header", probe: "alpha sends a beta Host header, an unknown host, and a path that climbs into another prefix", expect: "never beta's content" },
  { id: "reader-api", operation: "forge-origin-and-subject", probe: "alpha calls the reader API with a forged Origin and beta's subject ids", expect: "refused or empty" },
  { id: "exports", operation: "export-contents", probe: "alpha runs an export and the archive is searched for beta's rows", expect: "nothing of beta" },
  { id: "cli-foreign-tenant", operation: "token-for-alpha-tenant-beta", probe: "the CLI runs with a token for alpha and --tenant beta", expect: "refused" },
];

function surfaceCases(): IsolationCase[] {
  return SURFACES.map((surface) => ({
    id: `surface:${surface.id}`, kind: "surface" as const, subject: surface.id, operation: surface.operation, probe: surface.probe, expect: surface.expect,
  }));
}

// ---------------------------------------------------------------------------------------------------------------------
// Findings: gaps visible in the schema today (report-only; the suite turns them into failures later)

const CLAIM_BASED = (rule: Rule) => rule.allow === "owner" && typeof rule.identityClaim === "string" && /^papyrus_tenant_/.test(rule.identityClaim);
const hasTenantPrefix = (partitionKey: string) => partitionKey === "tenantId" || /^tenant/i.test(partitionKey);

export function findFindings(schema: SchemaInfo): Finding[] {
  const findings: Finding[] = [];
  for (const model of schema.models) {
    if (model.global) continue;
    if (!model.hasTenantId) {
      findings.push({ code: "model-without-tenantId", subject: model.name, note: "tenant-owned model has no tenantId field and is not in GLOBAL_MODELS" });
      continue;
    }
    if (model.tenantIdFieldRules.length === 0) {
      findings.push({ code: "tenantId-can-be-changed", subject: model.name, note: "no field-level rule on tenantId: with model-level rules an editor can update a row into another tenant (spike PPY-867f76)" });
    }
    if (model.rules.length > 0 && !model.rules.some(CLAIM_BASED)) {
      const kinds = [...new Set(model.rules.map((rule) => rule.allow === "groups" ? "group" : rule.allow))].sort().join(", ");
      findings.push({ code: "no-tenant-claim-rule", subject: model.name, note: `access rests on ${kinds} rules, none compares tenantId with a token claim` });
    }
    for (const index of model.indexes) {
      if (!hasTenantPrefix(index.partitionKey)) {
        findings.push({ code: "index-not-tenant-prefixed", subject: index.queryField, note: `partition key ${index.partitionKey} on ${model.name} is shared across tenants: lists post-filter and pages come back short (spike PPY-f4d892)` });
      }
    }
    if (model.subscriptions.length > 0) {
      findings.push({ code: "subscriptions-enabled", subject: model.name, note: "realtime subscriptions are not covered by an offline check; run them against the shared stack" });
    }
  }
  for (const operation of schema.operations) {
    const open = operation.rules.filter((rule) => rule.allow === "public" || rule.allow === "private" || (rule.allow === "guest"));
    if (open.length > 0) {
      findings.push({ code: "open-operation", subject: operation.name, note: `callable by ${[...new Set(open.map((rule) => rule.provider === "identityPool" ? `${rule.allow} (identity pool)` : rule.allow))].join(", ")} callers, so the handler must scope by the caller's tenant itself` });
    }
    if (operation.handler === null) {
      findings.push({ code: "operation-without-function", subject: operation.name, note: "not backed by a function: its resolver must scope by the caller's tenant" });
    }
  }
  return findings.sort((left, right) => `${left.code} ${left.subject}`.localeCompare(`${right.code} ${right.subject}`));
}

// ---------------------------------------------------------------------------------------------------------------------
// The table

export function buildCaseTable(schema: SchemaInfo = readSchema(), functions: FunctionInfo[] = readFunctions()): CaseTable {
  const cases: IsolationCase[] = [
    ...schema.models.flatMap(modelCases),
    ...schema.models.flatMap(indexCases),
    ...schema.models.flatMap(subscriptionCases),
    ...schema.operations.map(operationCases),
    ...functions.map(functionCase),
    ...surfaceCases(),
  ];
  const count = (kind: CaseKind) => cases.filter((entry) => entry.kind === kind).length;
  return {
    generatedBy: "scripts/generate-tenant-isolation-cases.ts",
    summary: {
      models: schema.models.length,
      globalModels: schema.models.filter((model) => model.global).length,
      modelCases: count("model"),
      indexCases: count("index"),
      subscriptionCases: count("subscription"),
      operationCases: count("operation"),
      functionCases: count("function"),
      surfaceCases: count("surface"),
    },
    cases,
    findings: findFindings(schema),
  };
}

export const serializeTable = (table: CaseTable) => `${JSON.stringify(table, null, 2)}\n`;

// ---------------------------------------------------------------------------------------------------------------------
// The feature's generated block

type Field = "subject" | "operation" | "expect";
type Outline = { kind: CaseKind; title: string; when: string; columns: [heading: string, field: Field][] };

const EDITORS = 'editor sessions for "alpha" and "beta" on the shared stack';
const KIND_OUTLINES: Outline[] = [
  { kind: "model", title: "Tenant A cannot reach tenant B through any model operation", when: 'the "alpha" session performs <operation> on a "beta" <model>', columns: [["model", "subject"], ["operation", "operation"], ["outcome", "expect"]] },
  { kind: "index", title: "Tenant A cannot read tenant B through any index", when: 'the "alpha" session calls <query> at one of "beta"\'s keys', columns: [["query", "subject"], ["outcome", "expect"]] },
  { kind: "subscription", title: "Tenant A receives no event of tenant B", when: 'the "alpha" session subscribes to <event> on <model> while "beta" writes', columns: [["model", "subject"], ["event", "operation"], ["outcome", "expect"]] },
  { kind: "operation", title: "Tenant A cannot use a custom query or mutation on tenant B", when: 'the "alpha" session calls <operation> with "beta"\'s ids', columns: [["operation", "subject"], ["outcome", "expect"]] },
  { kind: "function", title: "Tenant A cannot reach tenant B through any function", when: 'the "alpha" session reaches the <function> function with an event naming "beta"', columns: [["function", "subject"], ["outcome", "expect"]] },
  { kind: "surface", title: "Tenant A cannot reach tenant B outside the data API", when: 'the "alpha" session tries <surface>', columns: [["surface", "subject"], ["outcome", "expect"]] },
];

const cell = (value: string) => value.replace(/\|/g, "\\|");

function table(rows: string[][]): string[] {
  const widths = rows[0].map((_, column) => Math.max(...rows.map((row) => cell(row[column]).length)));
  return rows.map((row) => `      | ${row.map((value, column) => cell(value).padEnd(widths[column])).join(" | ")} |`);
}

export function generatedBlock(cases: IsolationCase[]): string {
  const blocks: string[] = [];
  for (const outline of KIND_OUTLINES) {
    const subset = cases.filter((entry) => entry.kind === outline.kind);
    if (subset.length === 0) continue;
    const rows = [outline.columns.map(([heading]) => heading), ...subset.map((entry) => outline.columns.map(([, field]) => entry[field]))];
    blocks.push([
      `  ${PENDING_TAG}`,
      `  Scenario Outline: ${outline.title}`,
      `    Given ${EDITORS}`,
      `    When ${outline.when}`,
      `    Then it is denied or returns nothing of "beta"`,
      "",
      "    Examples: generated from the schema",
      ...table(rows),
    ].join("\n"));
  }
  return blocks.join("\n\n");
}

export function applyGeneratedBlock(feature: string, cases: IsolationCase[]): string {
  const begin = feature.indexOf(BEGIN_MARKER);
  const end = feature.indexOf(END_MARKER);
  if (begin === -1 || end === -1 || end < begin) {
    throw new Error(`${FEATURE_PATH} must contain the lines "${BEGIN_MARKER.trim()}" and "${END_MARKER.trim()}"`);
  }
  return `${feature.slice(0, begin)}${BEGIN_MARKER}\n${generatedBlock(cases)}\n${feature.slice(end)}`;
}

// ---------------------------------------------------------------------------------------------------------------------
// Checking

/** Every model, index, subscription, operation and function the schema and function list have must have a case in `committed`. */
export function missingCases(schema: SchemaInfo, functions: FunctionInfo[], committed: CaseTable): string[] {
  const expected = buildCaseTable(schema, functions);
  const have = new Set(committed.cases.map((entry) => entry.id));
  const want = new Set(expected.cases.map((entry) => entry.id));
  const problems: string[] = [];
  for (const model of schema.models) {
    if (!committed.cases.some((entry) => entry.kind === "model" && entry.subject === model.name)) problems.push(`model ${model.name} has no isolation case`);
  }
  for (const entry of expected.cases) {
    if (have.has(entry.id)) continue;
    if (entry.kind === "model" && !committed.cases.some((c) => c.kind === "model" && c.subject === entry.subject)) continue;
    problems.push(`${entry.kind} ${entry.subject} has no isolation case${entry.kind === "model" ? ` for ${entry.operation}` : ""}`);
  }
  for (const entry of committed.cases) {
    if (!want.has(entry.id)) problems.push(`${entry.kind} ${entry.subject} has a case but no longer exists (${entry.id})`);
  }
  return problems;
}

export type CheckOptions = { casesPath?: string; featurePath?: string };

export function check(options: CheckOptions = {}): string[] {
  const casesPath = options.casesPath ?? path.join(REPO_ROOT, CASES_PATH);
  const featurePath = options.featurePath ?? path.join(REPO_ROOT, FEATURE_PATH);
  const schema = readSchema();
  const functions = readFunctions();
  const problems: string[] = [];
  let committed: CaseTable | null = null;
  try {
    committed = JSON.parse(readFileSync(casesPath, "utf8")) as CaseTable;
  } catch {
    problems.push(`${path.relative(REPO_ROOT, casesPath)} is missing or unreadable`);
  }
  if (committed) {
    problems.push(...missingCases(schema, functions, committed));
    if (problems.length === 0 && serializeTable(buildCaseTable(schema, functions)) !== serializeTable(committed)) {
      problems.push(`${path.relative(REPO_ROOT, casesPath)} is out of date (same subjects, different content)`);
    }
  }
  if (problems.length === 0) {
    const feature = readFileSync(featurePath, "utf8");
    if (applyGeneratedBlock(feature, committed!.cases) !== feature) problems.push(`${path.relative(REPO_ROOT, featurePath)} generated block is out of date`);
  }
  return problems;
}

export function write(): CaseTable {
  const tablePath = path.join(REPO_ROOT, CASES_PATH);
  const featurePath = path.join(REPO_ROOT, FEATURE_PATH);
  const built = buildCaseTable();
  writeFileSync(tablePath, serializeTable(built));
  writeFileSync(featurePath, applyGeneratedBlock(readFileSync(featurePath, "utf8"), built.cases));
  return built;
}

export function report(table: CaseTable = buildCaseTable()): string {
  const byCode = new Map<string, Finding[]>();
  for (const finding of table.findings) byCode.set(finding.code, [...(byCode.get(finding.code) ?? []), finding]);
  const lines = [`Cases: ${table.cases.length} (${Object.entries(table.summary).map(([name, value]) => `${name} ${value}`).join(", ")})`, `Known gaps: ${table.findings.length}`];
  for (const [code, list] of [...byCode].sort(([a], [b]) => a.localeCompare(b))) {
    lines.push("", `${code} (${list.length})`, ...list.map((finding) => `  ${finding.subject}: ${finding.note}`));
  }
  return lines.join("\n");
}

function main(argv: string[]): number {
  const argument = (name: string) => { const at = argv.indexOf(name); return at === -1 ? undefined : argv[at + 1]; };
  if (argv.includes("--report")) {
    console.log(report());
    return 0;
  }
  if (argv.includes("--check")) {
    const problems = check({ casesPath: argument("--cases"), featurePath: argument("--feature") });
    if (problems.length > 0) {
      console.error(["Tenant isolation cases are incomplete:", ...problems.map((problem) => `  - ${problem}`), "", "Run: npx tsx scripts/generate-tenant-isolation-cases.ts"].join("\n"));
      return 1;
    }
    console.log("Tenant isolation cases cover every model, index, operation and function.");
    return 0;
  }
  const built = write();
  console.log(`Wrote ${built.cases.length} cases to ${CASES_PATH} and ${FEATURE_PATH}.`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
