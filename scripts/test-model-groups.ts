import assert from "node:assert/strict";
import {
  BOOTSTRAP_DEFERRED_GROUPS,
  OPTIONAL_MODEL_GROUPS,
  assertKnownModelGroups,
  baseModelNames,
  resolveExcludedModelGroups,
} from "../amplify/data/schema";

const allModels = baseModelNames();
const groups = Object.keys(OPTIONAL_MODEL_GROUPS) as (keyof typeof OPTIONAL_MODEL_GROUPS)[];

for (const group of groups) {
  const without = baseModelNames([group]);
  for (const modelName of OPTIONAL_MODEL_GROUPS[group]) {
    assert.ok(allModels.includes(modelName), `${modelName} is in the full schema`);
    assert.ok(!without.includes(modelName), `${modelName} is left out when ${group} is excluded`);
  }
  assert.equal(allModels.length - without.length, OPTIONAL_MODEL_GROUPS[group].length, `${group} removes exactly its models`);
}
assert.ok(baseModelNames(["editions"]).includes("Item"), "Item stays");

const everythingDeferred = baseModelNames([...BOOTSTRAP_DEFERRED_GROUPS]);
for (const core of ["UserProfile", "Item", "Reference", "Message", "MessageThread", "Category", "Proposal"]) {
  assert.ok(everythingDeferred.includes(core), `${core} is created by the first deploy`);
}
assert.doesNotThrow(() => assertKnownModelGroups(["editions", "knowledge"]));
assert.throws(() => assertKnownModelGroups(["nonsense"]), /Unknown model group "nonsense"/);

// The bootstrap switch: off (unset or anything but "1") adds nothing.
assert.deepEqual(resolveExcludedModelGroups(undefined, {}), []);
assert.deepEqual(resolveExcludedModelGroups(["editions"], {}), ["editions"]);
assert.deepEqual(resolveExcludedModelGroups(undefined, { PAPYRUS_BOOTSTRAP_STAGE: "0" }), []);
assert.deepEqual(resolveExcludedModelGroups(undefined, { PAPYRUS_BOOTSTRAP_STAGE: "" }), []);
// On: every deferred group, without duplicating a configured one.
const staged = resolveExcludedModelGroups(["editions"], { PAPYRUS_BOOTSTRAP_STAGE: "1" });
assert.deepEqual([...staged].sort(), [...BOOTSTRAP_DEFERRED_GROUPS].sort());
assert.equal(new Set(staged).size, staged.length);
console.log("model group tests passed");
