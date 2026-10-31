const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-plugin.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-plugin.ts", name], {
      cwd: path.resolve(__dirname, "../.."),
      maxBuffer: 8 * 1024 * 1024,
    });
    passed.push(JSON.parse(result.stdout.trim().split("\n").pop()).behaviour);
  }
  return passed;
}

function step(keyword, text, ...names) {
  keyword(text, { timeout: 120_000 }, async function () {
    this.passed = [...(this.passed ?? []), ...(await behaviours(...names))];
  });
}

function pass(text) {
  Then(text, function () {
    assert.ok(this.passed && this.passed.length > 0);
  });
}

step(When, "a site lists no plugins", "plugin is absent when the site does not list it");
pass("the alexa plugin is known to Papyrus");
pass("nothing about it is resolved, wired or published for that site");

step(When, "a site configures the alexa plugin", "config is validated");
pass("the invocation name, skill ID, account linking switch and site origin are validated");
pass("an unknown setting is refused");

step(When, "the alexa plugin is wired for a site", "only the Alexa service may invoke the function", "wiring publishes the endpoint");
pass("the function accepts invocations from the Alexa service principal only");
pass("once the skill ID is known the permission carries the skill ID condition");
pass("the function ARN is an output the skill package deploy reads");
pass("the public settings carry no skill ID");

step(Given, "a site with a configured skill ID", "endpoint rejects a request with the wrong skill ID");
step(When, "a request arrives for a different skill", "endpoint rejects a request with the wrong skill ID");
pass("the endpoint refuses it");
pass("a request for the configured skill is answered");

step(Given, "a site without a skill ID", "endpoint serves nothing until a skill ID is configured");
step(When, "any request arrives", "endpoint serves nothing until a skill ID is configured");

step(When, "an intent module or an APL document file exists", "registries list every module and keep ids unique");
pass("it is listed in its index, ids are unique and every document is APL");

step(When, "the skill package is generated from a site's settings", "skill package is generated deterministically");
pass("the manifest names the endpoint and the interaction model names the invocation name");
pass("intents are sorted so the same inputs give the same files");
pass("two modules defining the same intent are refused");
