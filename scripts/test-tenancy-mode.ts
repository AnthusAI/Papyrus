import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  TENANCY_MODE_ENVIRONMENT_VARIABLE,
  resolveTenancyMode,
  tenancyFunctionEnvironment,
  validateTenancyConfig,
} from "../amplify/site-backend-config";
import { rulesForTenancyMode } from "../amplify/data/schema";
import { isSharedStack } from "../lib/tenant-keys";

assert.equal(resolveTenancyMode(undefined), "dedicated");
assert.equal(resolveTenancyMode({}), "dedicated");
assert.equal(resolveTenancyMode({ mode: "shared" }), "shared");
assert.deepEqual(tenancyFunctionEnvironment("dedicated"), {});
assert.deepEqual(tenancyFunctionEnvironment("shared"), { [TENANCY_MODE_ENVIRONMENT_VARIABLE]: "shared" });
assert.deepEqual(validateTenancyConfig(undefined), []);
assert.deepEqual(validateTenancyConfig({ mode: "dedicated" }), []);
assert.equal(validateTenancyConfig({ mode: "pooled" }).length, 1);
assert.equal(validateTenancyConfig("shared").length, 1);

assert.equal(isSharedStack({}), false);
assert.equal(isSharedStack({ PAPYRUS_TENANCY_MODE: "dedicated" }), false);
assert.equal(isSharedStack({ PAPYRUS_TENANCY_MODE: "shared" }), true);

assert.equal(rulesForTenancyMode("dedicated", { dedicated: "a", shared: "b" }), "a");
assert.equal(rulesForTenancyMode("shared", { dedicated: "a", shared: "b" }), "b");

// One reader: only the helpers (and the synth-time config that sets it) may name the variable.
const root = process.cwd();
const allowed = new Set([
  "amplify/site-backend-config.ts",
  "lib/tenant-keys.ts",
  "src/papyrus_content/tenancy.py",
  "src/papyrus_content/tenancy_test.py",
  "scripts/test-tenancy-mode.ts",
  "features_backend/steps/tenancy_mode_steps.py",
  "features_backend/steps/shared_stack_steps.py",
  "features_backend/tenancy-mode.feature",
  "docs/multi-tenancy.md",
]);
const hits = execFileSync("git", ["grep", "-l", "PAPYRUS_TENANCY_MODE", "--", "*.ts", "*.tsx", "*.mts", "*.mjs", "*.cjs", "*.py"], { cwd: root, encoding: "utf8" })
  .split("\n").filter(Boolean).filter((file) => !allowed.has(file));
assert.deepEqual(hits, [], `PAPYRUS_TENANCY_MODE is read through the tenancy helpers only; found in ${hits.join(", ")}`);
console.log("tenancy mode ok");
