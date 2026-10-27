const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-cli-login-discovery.ts, which asserts internally and prints its result.
async function behaviour(name) {
  const result = await promisify(execFile)(process.execPath,
    ["--import", "tsx", "scripts/test-cli-login-discovery.ts", name],
    { cwd: path.resolve(__dirname, "../.."), maxBuffer: 8 * 1024 * 1024 });
  return JSON.parse(result.stdout);
}

function given(text, name) {
  Given(text, function () { this.cliLoginBehaviour = name; });
}

given("a site whose web client registers the localhost 3001 callback", "published");
given("a site whose web client does not register the localhost 3001 callback", "callback_not_registered");
given("a site whose Amplify outputs have no sign-in section", "no_oauth_outputs");
given("a site whose public origin is not configured", "origin_missing");

When("the CLI login file is requested", { timeout: 120_000 }, async function () {
  this.cliLoginResult = await behaviour(this.cliLoginBehaviour);
});

When("the CLI login file is requested through a different host name", { timeout: 120_000 }, async function () {
  this.cliLoginResult = await behaviour("origin_is_configured_not_requested");
});

Then("it names the site's own origin, Cognito issuer, web client id, hosted sign-in domain, GraphQL endpoint and the localhost 3001 callback", function () {
  const body = this.cliLoginResult.body;
  assert.equal(this.cliLoginResult.status, 200);
  for (const field of ["publication", "issuer", "client_id", "oauth_domain", "graphql_endpoint", "callback_uri"]) {
    assert.ok(typeof body[field] === "string" && body[field].length > 0, `${field} missing`);
  }
  assert.equal(body.callback_uri, "http://localhost:3001/");
});

Then("it contains only public fields", async function () {
  const result = await behaviour("only_public_fields");
  assert.deepEqual(Object.keys(result.body).sort(), [
    "callback_uri", "client_id", "graphql_endpoint", "issuer", "oauth_domain", "publication",
  ]);
});

Then("the published origin is still the configured site origin", function () {
  assert.equal(this.cliLoginResult.body.publication, "https://shipped.example.test");
});

Then("the answer is {string} explaining the site does not register the CLI callback", function (answer) {
  assert.equal(answer, "not found");
  assert.equal(this.cliLoginResult.status, 404);
  assert.equal(this.cliLoginResult.body.error, "cli_login_not_configured");
});

Then("the answer is {string}", function (answer) {
  assert.equal(answer, "service unavailable");
  assert.equal(this.cliLoginResult.status, 503);
});
