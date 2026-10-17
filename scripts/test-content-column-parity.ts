import { readFileSync } from "node:fs";
import { join } from "node:path";

const SCHEMA_PATH = "amplify/data/schema.ts";
const REPOSITORY_PATH = "lib/graphql-content-repository.ts";

function extractModelFieldNames(schemaSource: string, modelName: string): Set<string> {
  const start = new RegExp(`^  ${modelName}: `, "m").exec(schemaSource);
  if (!start) throw new Error(`model ${modelName} not found in ${SCHEMA_PATH}`);
  const rest = schemaSource.slice(start.index);
  const end = rest.indexOf(".secondaryIndexes");
  const block = end === -1 ? rest : rest.slice(0, end);
  return new Set([...block.matchAll(/^\s{6}(\w+): a\./gm)].map((match) => match[1]));
}

function extractGraphQLItemKeys(repositorySource: string): string[] {
  const match = /type GraphQLItem = \{([\s\S]*?)\n\};/.exec(repositorySource);
  if (!match) throw new Error(`type GraphQLItem not found in ${REPOSITORY_PATH}`);
  return [...match[1].matchAll(/^\s{2}(\w+)\??:/gm)].map((entry) => entry[1]);
}

const schemaSource = readFileSync(join(process.cwd(), SCHEMA_PATH), "utf8");
const repositorySource = readFileSync(join(process.cwd(), REPOSITORY_PATH), "utf8");
const keys = extractGraphQLItemKeys(repositorySource);
if (keys.length < 10) throw new Error(`GraphQLItem parsed suspiciously few keys: ${keys.join(",")}`);

let failed = false;
for (const modelName of ["Item", "PublishedItem"]) {
  const fields = extractModelFieldNames(schemaSource, modelName);
  const missing = keys.filter((key) => !fields.has(key));
  if (missing.length) {
    failed = true;
    console.error(`${modelName} is missing GraphQLItem keys: ${missing.join(", ")}`);
  }
}
if (failed) process.exit(1);
console.log(`content column parity ok (${keys.length} GraphQLItem keys on Item and PublishedItem)`);
