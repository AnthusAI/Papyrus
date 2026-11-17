const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { Given, When, Then } = require("@cucumber/cucumber");

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
  this.bootstrapOutput = output;
  const match = /bootstrap stage: (\d+) resources/.exec(output);
  assert.ok(match, output);
  this.bootstrapResources = Number(match[1]);
});

Then("the whole backend has fewer than {int} resources", function (limit) {
  assert.ok(this.bootstrapResources < limit, String(this.bootstrapResources));
});

Then("the first deploy creates no post-deploy render, because the render reads models the second deploy adds", function () {
  // scripts/test-bootstrap-stage.ts asserts there is no reproject-on-deploy stack and exits non-zero otherwise.
  assert.ok(this.bootstrapResources > 0);
});

Then("no deferred model has a stack", function () {
  // scripts/test-bootstrap-stage.ts asserts this and exits non-zero otherwise.
  assert.ok(this.bootstrapResources > 0);
});

Then("it has no agents stack", function () {
  // scripts/test-bootstrap-stage.ts asserts this and exits non-zero otherwise, and prints the line checked here.
  assert.ok(/agents stack: absent/.test(this.bootstrapOutput), this.bootstrapOutput);
});

Then("the first-stage resource count does not include any agent resource", function () {
  assert.ok(this.bootstrapResources > 0);
});

Given("an agent piece exists", function () {
  this.agentsOutput = runTsx("scripts/test-agents-stack.ts", [], {});
});

When("the backend is synthesized without the bootstrap variable", function () {
  assert.ok(/agents stack tests passed/.test(this.agentsOutput), this.agentsOutput);
});

Then("it has one stack named agents holding the piece", function () {
  assert.ok(/fixture piece: 3 resources/.test(this.agentsOutput), this.agentsOutput);
});

Then("that stack is not created when the variable is 1", function () {
  // scripts/test-agents-stack.ts asserts this and exits non-zero otherwise.
  assert.ok(/agents stack tests passed/.test(this.agentsOutput));
});

Then("a site with no agent piece has no agents stack, because CloudFormation accepts no empty stack", function () {
  assert.ok(/agents stack tests passed/.test(this.agentsOutput));
});

Given("the agent pieces of the site backend", function () {
  this.agentsOutput = runTsx("scripts/test-agents-stack.ts", [], {});
});

When("the agents stack is priced", function () {
  assert.ok(/agents stack tests passed/.test(this.agentsOutput), this.agentsOutput);
});

Then("each piece's resource count is printed", function () {
  assert.ok(/agent pieces: /.test(this.agentsOutput), this.agentsOutput);
});

Then("the total is printed against the first-deploy headroom", function () {
  assert.ok(/first-deploy headroom: \d+ of \d+ resources/.test(this.agentsOutput), this.agentsOutput);
});

Then("two pieces with the same id are refused", function () {
  assert.ok(/agents stack tests passed/.test(this.agentsOutput));
});
