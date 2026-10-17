import { readFileSync } from "node:fs";
import { join } from "node:path";

const SCHEMA_FILES = ["amplify/data/schema.ts", "amplify/data/resource.ts"];
// The deployed schema (schema.ts) and the typed schema (resource.ts) must agree
// for every model the Python authoring client reads with a fixed field list.
const MODEL_NAMES = [
  "Item", "PublishedItem", "SemanticNode", "SemanticRelation", "Reference", "Message",
  "Assignment", "KnowledgeRawPayload", "ModelAttachment",
];
const REQUIRED_FIELDS: Record<string, string[]> = {
  Item: ["bodyMarkus", "bodyIr", "aliases", "metadata"],
  PublishedItem: ["bodyMarkus", "bodyIr", "aliases", "metadata"],
};

function extractFieldNames(source: string, modelName: string): Set<string> {
  const startPattern = new RegExp(`^  ${modelName}: `, "m");
  const startMatch = startPattern.exec(source);
  if (!startMatch) {
    throw new Error(`model ${modelName} not found`);
  }
  const rest = source.slice(startMatch.index);
  const endIndex = rest.indexOf(".secondaryIndexes");
  const block = endIndex === -1 ? rest : rest.slice(0, endIndex);
  const names = new Set<string>();
  for (const match of block.matchAll(/^\s{6}(\w+): a\./gm)) {
    names.add(match[1]);
  }
  return names;
}

let failed = false;
for (const modelName of MODEL_NAMES) {
  const perFile = SCHEMA_FILES.map((file) =>
    extractFieldNames(readFileSync(join(process.cwd(), file), "utf8"), modelName),
  );
  const [first, second] = perFile;
  const onlyFirst = [...first].filter((name) => !second.has(name));
  const onlySecond = [...second].filter((name) => !first.has(name));
  if (onlyFirst.length || onlySecond.length) {
    failed = true;
    console.error(`${modelName} drift: only in ${SCHEMA_FILES[0]}: ${onlyFirst}; only in ${SCHEMA_FILES[1]}: ${onlySecond}`);
  }
  for (const field of REQUIRED_FIELDS[modelName] ?? []) {
    for (let index = 0; index < perFile.length; index += 1) {
      if (!perFile[index].has(field)) {
        failed = true;
        console.error(`${modelName} missing ${field} in ${SCHEMA_FILES[index]}`);
      }
    }
  }
  console.log(`${modelName}: ${first.size} fields in schema.ts, ${second.size} in resource.ts`);
}
if (failed) {
  process.exit(1);
}
console.log("schema parity ok");
