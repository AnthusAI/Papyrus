const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-skill-sync.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-skill-sync.ts", name], {
      cwd: path.resolve(__dirname, "../.."),
      maxBuffer: 8 * 1024 * 1024,
    });
    passed.push(JSON.parse(result.stdout.trim().split("\n").pop()).behaviour);
  }
  return passed;
}

function step(text, ...names) {
  When(text, { timeout: 120_000 }, async function () {
    this.passed = [...(this.passed ?? []), ...(await behaviours(...names))];
  });
}

function pass(text) {
  Then(text, function () {
    assert.ok(this.passed && this.passed.length > 0);
  });
}

step("the skill package is generated for a site that sets an origin", "manifest is complete");
pass("the manifest has the name, summary, description, example phrase, keywords, News category and both icons");
pass("it names the privacy and terms pages under the site origin unless the settings override them");
pass("it declares the APL interface, the endpoint and every configured locale");

step("the skill package is generated twice from the same settings", "package matches the snapshot and is deterministic");
pass("the bytes are identical and match the committed snapshot");

step("the sync runs and the developer credentials are not in SSM", "sync skips without credentials");
pass("it logs one line and makes no call to Amazon");
pass("nothing is written to SSM, so the site deploy carries on");

step("the sync runs for a site that has no skill yet", "first sync creates the skill");
pass("Amazon is asked to create the skill and the interaction model is uploaded");
pass("the skill ID is stored in SSM before the upload");
pass("only that skill may invoke the function afterwards");

step("the sync runs again with the same generated content", "unchanged sync makes no Amazon call");
pass("it makes no call to Amazon");
pass("a restored unconditional invoke permission is scoped to the skill again");

step("the generated content changes", "changed content updates the skill");
pass("the manifest and the model are updated and no second skill is created");

step("a site turns account linking on", "account linking is pushed");
pass("the sync pushes an authorization code grant against the hosted UI of the site's Cognito pool");
pass("the client secret is read from Cognito at sync time");
pass("linking is skipped when the site does not turn it on");

step("the skill function starts and the skill ID parameter is missing", "skill ID is read from SSM and fails closed");
pass("it serves no request");
pass("once the parameter exists it serves that skill and remembers the ID");

step("the production build spec of a site is generated", "site build runs the sync after the backend deploy");
pass("the sync runs after the backend deploy");
pass("a failed sync never fails the build");
