import { readFileSync } from "node:fs";
import { join } from "node:path";

const MODELS_WITHOUT_IDENTITY_POOL_ACCESS = ["Assignment", "MessageThread"];

function extractModelBlock(source: string, modelName: string): string {
  const start = new RegExp(`^  ${modelName}: `, "m").exec(source);
  if (!start) throw new Error(`model ${modelName} not found`);
  const rest = source.slice(start.index + 1);
  const nextModel = /^  \w+: /m.exec(rest.slice(modelName.length + 2));
  return nextModel ? rest.slice(0, nextModel.index + modelName.length + 2) : rest;
}

const schemaSource = readFileSync(join(process.cwd(), "amplify/data/schema.ts"), "utf8");
let failed = false;
for (const modelName of MODELS_WITHOUT_IDENTITY_POOL_ACCESS) {
  const block = extractModelBlock(schemaSource, modelName);
  if (!block.includes(".authorization(")) throw new Error(`${modelName} has no authorization block`);
  if (/identityPool/.test(block)) {
    console.error(`${modelName} must not grant identity-pool access`);
    failed = true;
  }
}
if (failed) process.exit(1);
console.log("test-identity-pool-model-access: ok");
