/**
 * CloudFormation creates at most 2,500 resources in one stack operation, nested stacks included. The full backend
 * is more than that, so a brand-new site's first `ampx pipeline-deploy` runs with `PAPYRUS_BOOTSTRAP_STAGE=1`.
 * This synthesizes the real backend (in a child process, because Amplify allows one backend per process) with the
 * switch on and counts every resource across the root and nested templates.
 */
import assert from "node:assert/strict";
import { OPTIONAL_MODEL_GROUPS } from "../amplify/data/schema";
import { AGENTS_STACK_NAME } from "../amplify/agents/stack";
import { BOOTSTRAP_BUDGET, CLOUDFORMATION_OPERATION_LIMIT, measureBootstrapStage } from "./bootstrap-stage-measure";

const { resources, modelStacks, templates } = measureBootstrapStage();

assert.ok(resources < BOOTSTRAP_BUDGET, `bootstrap stage has ${resources} resources; keep it under ${BOOTSTRAP_BUDGET} (CloudFormation fails at ${CLOUDFORMATION_OPERATION_LIMIT})`);
for (const modelName of Object.values(OPTIONAL_MODEL_GROUPS).flat()) {
  assert.ok(!modelStacks.includes(modelName), `${modelName} is deferred to the second deploy`);
}
for (const core of ["UserProfile", "Item", "Reference", "Message"]) {
  assert.ok(modelStacks.includes(core), `${core} is created by the first deploy`);
}
assert.ok(!templates.some((name) => /reprojectondeploy/i.test(name)), "the bootstrap stage creates no post-deploy render");
assert.ok(
  !templates.some((name) => name.toLowerCase().includes(AGENTS_STACK_NAME)),
  "the bootstrap stage creates no agents stack: every agent resource is deferred to the second deploy",
);
console.log(`bootstrap stage: ${resources} resources, ${modelStacks.length} model stacks`);
console.log(`agents stack: absent from the bootstrap stage; first-deploy headroom: ${BOOTSTRAP_BUDGET - resources} of ${BOOTSTRAP_BUDGET} resources`);
console.log("bootstrap stage tests passed");
