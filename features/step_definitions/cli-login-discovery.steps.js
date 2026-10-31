const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-cli-login-discovery.ts, which asserts internally and prints its result.
async function behaviour(name, script = "scripts/test-cli-login-discovery.ts") {
  const result = await promisify(execFile)(process.execPath,
    ["--import", "tsx", script, name],
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
given("a site that has not moved the CLI onto its federation client", "flag_off_names_main_client");
given("a site that moved the CLI onto its federation client", "flag_on_names_federation_client");
given("a site that moved the CLI onto its federation client but publishes no federation client", "flag_on_without_federation_client");

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

Then("it names the main web client and the localhost 3001 callback exactly as before", function () {
  assert.equal(this.cliLoginResult.body.client_id, "synthetic-web-client");
  assert.equal(this.cliLoginResult.body.callback_uri, "http://localhost:3001/");
});

Then("it names the federation client, the fixed loopback callback and the remote callback", function () {
  assert.equal(this.cliLoginResult.body.client_id, "synthetic-federation-client");
  assert.equal(this.cliLoginResult.body.callback_uri, "http://127.0.0.1:38947/cli/callback");
  assert.equal(this.cliLoginResult.body.remote_callback_uri, "https://shipped.example.test/cli/callback");
});

When("the federation client is synthesized with the CLI moved onto it", { timeout: 120_000 }, async function () {
  await behaviour("callback_list_is_exact", "scripts/test-cli-federation-client.ts");
  await behaviour("federation_client_is_google_only", "scripts/test-cli-federation-client.ts");
});

Then("its callbacks are each site origin's Prospectus callback, the fixed loopback and the console's cli callback", function () {});

Then("only Google is admitted through the code flow and no password flow is reachable", function () {});

When("the federation client is synthesized with and without the CLI moved onto it", { timeout: 120_000 }, async function () {
  await behaviour("sessions_last_seven_days_only_when_moved", "scripts/test-cli-federation-client.ts");
});

Then("with the CLI moved it keeps refresh tokens for seven days and access and ID tokens for 60 minutes", function () {});

Then("without it the client keeps its 60 minute refresh tokens exactly as registered", function () {});
