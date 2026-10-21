import assert from "node:assert/strict";
import { OPTIONAL_MODEL_GROUPS, assertKnownModelGroups, baseModelNames } from "../amplify/data/schema";

const allModels = baseModelNames();
const withoutEditions = baseModelNames(["editions"]);

for (const modelName of OPTIONAL_MODEL_GROUPS.editions) {
  assert.ok(allModels.includes(modelName), `${modelName} is in the full schema`);
  assert.ok(!withoutEditions.includes(modelName), `${modelName} is left out when editions are excluded`);
}
assert.equal(allModels.length - withoutEditions.length, OPTIONAL_MODEL_GROUPS.editions.length);
assert.ok(withoutEditions.includes("Item"), "Item stays");
assert.doesNotThrow(() => assertKnownModelGroups(["editions"]));
assert.throws(() => assertKnownModelGroups(["nonsense"]), /Unknown model group "nonsense"/);
console.log("model group tests passed");
