import { readFileSync } from "node:fs";
import { join } from "node:path";

const SCHEMA_FILES = ["amplify/data/schema.ts", "amplify/data/resource.ts"];
// The deployed schema (schema.ts) and the typed schema (resource.ts) must agree
// for every model the Python authoring client reads with a fixed field list.
const MODEL_NAMES = [
  "Item", "PublishedItem", "SemanticNode", "SemanticRelation", "Reference", "Message",
  "Assignment", "KnowledgeRawPayload", "ModelAttachment", "MediaAsset", "PublishedMediaAsset", "NewsroomSection", "Automation", "ProcedureRun", "ReviewRequest", "ReviewReadMark", "ReviewRecipientRule",
];
const REQUIRED_FIELDS: Record<string, string[]> = {
  Item: ["bodyMarkus", "bodyIr", "aliases", "metadata", "tenantId", "tenantSlug"],
  PublishedItem: ["bodyMarkus", "bodyIr", "aliases", "metadata", "tenantId", "tenantSlug"],
  Message: ["editedAt", "deletedAt", "deletedBySub"],
  MediaAsset: ["tenantId"],
  PublishedMediaAsset: ["tenantId"],
  NewsroomSection: ["tenantId"],
};

// Indexes the References page reads through (features_backend/reference-feed-keys.feature): each must exist, with its sort key, in both files.
const REQUIRED_INDEXES = [
  'index("feedStateKey").sortKeys(["predictionSortKey"]).queryField("listReferencesByFeedStateAndPrediction")',
  'index("feedStateKey").sortKeys(["feedArrivalAt"]).queryField("listReferencesByFeedStateAndArrival")',
];

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
  for (const match of block.matchAll(/^\s{6}(?:\.\.\.\(\w+ \? \{ )?(\w+): a\./gm)) {
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
for (const file of SCHEMA_FILES) {
  const source = readFileSync(join(process.cwd(), file), "utf8");
  for (const declaration of REQUIRED_INDEXES) {
    if (!source.includes(declaration)) {
      failed = true;
      console.error(`Reference is missing ${declaration} in ${file}`);
    }
  }
}
// Custom queries and mutations: the deployed schema (schema.ts) must carry every one the typed schema (resource.ts) declares, or the client
// calls a field the site's API does not have (createReferenceLink and three more shipped only in resource.ts in 5.69.0). The four below
// were already only in resource.ts before this check existed; deciding whether to deploy or delete them is its own change.
const KNOWN_TYPED_ONLY_OPERATIONS = new Set(["createReferenceNote", "getReferenceCurationStatus", "moveReferenceCorpus", "startReferenceCuration"]);
function operationNames(source: string): Set<string> {
  return new Set([...source.matchAll(/^  (\w+): a\s*\n\s*\.(?:mutation|query)\(\)/gm)].map((match) => match[1]));
}
const [deployedOperations, typedOperations] = SCHEMA_FILES.map((file) => operationNames(readFileSync(join(process.cwd(), file), "utf8")));
const missingOperations = [...typedOperations].filter((name) => !deployedOperations.has(name) && !KNOWN_TYPED_ONLY_OPERATIONS.has(name));
if (missingOperations.length) {
  failed = true;
  console.error(`operations declared in ${SCHEMA_FILES[1]} but not deployed by ${SCHEMA_FILES[0]}: ${missingOperations.join(", ")}`);
}
console.log(`operations: ${deployedOperations.size} in schema.ts, ${typedOperations.size} in resource.ts`);
if (failed) {
  process.exit(1);
}
console.log("schema parity ok");
