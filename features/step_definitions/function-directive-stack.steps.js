const assert = require("node:assert/strict");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { Given, Then } = require("@cucumber/cucumber");

Given("the site backend is synthesized with every plugin enabled", function () {
  const result = spawnSync("npx", ["tsx", "scripts/test-function-directive-stack.ts"], {
    cwd: path.resolve(__dirname, "../.."),
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const match = /FunctionDirectiveStack: (\d+) resources, (\d+) resolvers, (\d+) data sources/.exec(result.stdout);
  assert.ok(match, `no stack summary in the output: ${result.stdout}`);
  this.functionDirectiveStack = { resources: Number(match[1]), resolvers: Number(match[2]), dataSources: Number(match[3]) };
});

Then("the Lambda resolver stack has fewer than {int} resources", function (limit) {
  assert.ok(this.functionDirectiveStack.resources < limit, JSON.stringify(this.functionDirectiveStack));
});

Then("fields that call the same Lambda share one data source", function () {
  const { resolvers, dataSources } = this.functionDirectiveStack;
  assert.ok(dataSources < resolvers / 2, JSON.stringify(this.functionDirectiveStack));
});
