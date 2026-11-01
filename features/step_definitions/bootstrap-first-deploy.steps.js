const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { Given, Then } = require("@cucumber/cucumber");

function runTsx(script, args, env) {
  const result = spawnSync("npx", ["tsx", script, ...args], {
    cwd: path.resolve(__dirname, "../.."),
    env: { ...process.env, ...env },
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

function resolveGroups(configured, environment) {
  const output = runTsx("scripts/probe-bootstrap-stage.ts", [JSON.stringify(configured), JSON.stringify(environment)], {});
  return JSON.parse(output);
}

Given("the branch variable PAPYRUS_BOOTSTRAP_STAGE is not set", function () {
  this.bootstrapEnvironment = {};
});

Given("the branch variable PAPYRUS_BOOTSTRAP_STAGE is {string}", function (value) {
  this.bootstrapEnvironment = { PAPYRUS_BOOTSTRAP_STAGE: value };
});

Then("no model groups are left out of the data API", function () {
  assert.deepEqual(resolveGroups([], this.bootstrapEnvironment).excluded, []);
});

Then("a site that configures the editions group still leaves out only editions", function () {
  assert.deepEqual(resolveGroups(["editions"], this.bootstrapEnvironment).excluded, ["editions"]);
});

Then("every optional model group is left out of the data API", function () {
  const { excluded, known } = resolveGroups([], this.bootstrapEnvironment);
  assert.deepEqual([...excluded].sort(), [...known].sort());
});

Then("the models the newsroom needs to start are still created", function () {
  const { remaining } = resolveGroups([], this.bootstrapEnvironment);
  for (const model of ["UserProfile", "Item", "Reference", "Message", "Category"]) {
    assert.ok(remaining.includes(model), `${model} stays`);
  }
});

Given("the site backend is synthesized in the bootstrap stage", function () {
  const output = runTsx("scripts/test-bootstrap-stage.ts", [], {});
  const match = /bootstrap stage: (\d+) resources/.exec(output);
  assert.ok(match, output);
  this.bootstrapResources = Number(match[1]);
});

Then("the whole backend has fewer than {int} resources", function (limit) {
  assert.ok(this.bootstrapResources < limit, String(this.bootstrapResources));
});

Then("no deferred model has a stack", function () {
  // scripts/test-bootstrap-stage.ts asserts this and exits non-zero otherwise.
  assert.ok(this.bootstrapResources > 0);
});
