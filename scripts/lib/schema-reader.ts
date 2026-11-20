/**
 * The one reader of the deployed schema, shared by the generators under scripts/ (the tenant isolation case table and the tenant key inventory).
 *
 * The source of truth is the GraphQL Amplify generates from `amplify/data/schema.ts` plus every plugin's definitions
 * (`schema.transform().schema`), so what is read is what AppSync serves. Nothing here calls AWS.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse, print, type DirectiveNode, type FieldDefinitionNode, type ObjectTypeDefinitionNode, type ValueNode } from "graphql";
import { schemaWithPlugins } from "../../amplify/data/schema";
import { KNOWN_PLUGINS } from "../../amplify/plugins/registry";

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** Models that belong to no single tenant (people, sign-in identities, public handles). They carry no tenantId by design. */
export const GLOBAL_MODELS = ["UserProfile", "UserIdentity", "PublicHandleClaim"];

export type ModelInfo = {
  name: string;
  hasTenantId: boolean;
  /** Every field of the model, mapped to whether the schema requires it (a non-null type). A DynamoDB index holds only the rows that have its key fields. */
  fields: Record<string, { required: boolean }>;
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
        fields: Object.fromEntries(fields.map((field) => [field.name.value, { required: field.type.kind === "NonNullType" }])),
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
