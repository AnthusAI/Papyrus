const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-cognito-client.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviours(...names) {
  const passed = [];
  for (const name of names) {
    const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-cognito-client.ts", name], {
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

step("the alexa plugin is wired for a site with account linking off", "the client exists only when account linking is on");
pass("the user pool gets no Alexa client, no environment variables and no linking outputs");
pass("with account linking on the pool gets exactly one Alexa client");

step("a site turns account linking on without a vendor ID or with a malformed one", "the vendor ID is required and checked");
pass("the settings are refused before anything deploys");

step(
  "the alexa plugin is wired for a site with account linking on",
  "the client admits only Google and the code flow",
  "the client has a secret and long-lived refresh tokens",
  "the callbacks are Amazon's redirect URLs for the vendor ID",
  "the function learns the pool and the client",
  "the outputs carry the linking settings beside the endpoint",
);
pass("the client allows the Google provider, the code flow and nothing else");
pass("password, SRP and custom authentication are left off");
pass("the client is created after the Google provider");
pass("the client has a generated secret that the template stores nowhere");
pass("refresh tokens last a year while access and ID tokens last an hour");
pass("the client's callback URLs are Amazon's three regional redirects for the vendor ID");
pass("the function receives the user pool ID and the client ID");
pass("the outputs carry the pool, the client and the hosted sign-in domain beside the function ARN");

step("account linking is on but the site has no Google identity provider", "linking without Google is refused");
pass("the deploy is refused with a clear reason");
