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

given("a site whose backend declared a native CLI client", "published");
given("a site whose backend declared no native CLI client", "no_client");
given("a site whose declared CLI callback is not a loopback address", "unsafe_callback");
given("a site whose public origin is not configured", "origin_missing");
given("a site that opts in to CLI login with a loopback callback", "client_shape");
given("a backend that tries to opt in with a callback that is not a fixed loopback port", "client_refuses_unsafe_callback");

When("the CLI login file is requested", { timeout: 120_000 }, async function () {
  this.cliLoginResult = await behaviour(this.cliLoginBehaviour);
});

When("the CLI login file is requested through a different host name", { timeout: 120_000 }, async function () {
  this.cliLoginResult = await behaviour("origin_is_configured_not_requested");
});

Then("it names the site's own origin, Cognito issuer, client id, hosted sign-in domain, GraphQL endpoint and loopback callback", function () {
  const body = this.cliLoginResult.body;
  assert.equal(this.cliLoginResult.status, 200);
  for (const field of ["publication", "issuer", "client_id", "oauth_domain", "graphql_endpoint", "callback_uri"]) {
    assert.ok(typeof body[field] === "string" && body[field].length > 0, `${field} missing`);
  }
});

Then("it contains only public fields", async function () {
  const result = await behaviour("only_public_fields");
  assert.deepEqual(Object.keys(result.body).sort(), [
    "callback_uri", "client_id", "graphql_endpoint", "issuer", "oauth_domain", "publication", "refresh_lifetime_seconds",
  ]);
});

Then("the published origin is still the configured site origin", function () {
  assert.equal(this.cliLoginResult.body.publication, "https://shipped.example.test");
});

Then("the answer is {string} explaining the site has no native CLI sign-in client", function (answer) {
  assert.equal(answer, "not found");
  assert.equal(this.cliLoginResult.status, 404);
  assert.equal(this.cliLoginResult.body.error, "cli_login_not_configured");
});

Then("the answer is {string}", function (answer) {
  assert.equal(answer, "service unavailable");
  assert.equal(this.cliLoginResult.status, 503);
});

Then("its Cognito client has no secret and admits only Google through the authorization code flow", { timeout: 120_000 }, async function () {
  this.cognitoClient = await behaviour("client_shape");
  assert.equal(this.cognitoClient.GenerateSecret, false);
  assert.deepEqual(this.cognitoClient.SupportedIdentityProviders, ["Google"]);
  assert.deepEqual(this.cognitoClient.AllowedOAuthFlows, ["code"]);
});

Then("it registers exactly the loopback callback and allows only refresh-token authentication", function () {
  assert.deepEqual(this.cognitoClient.CallbackURLs, ["http://localhost:5182/oauth/callback"]);
  assert.deepEqual(this.cognitoClient.ExplicitAuthFlows, ["ALLOW_REFRESH_TOKEN_AUTH"]);
});

Then("token revocation is on and the refresh session lasts 30 days by default", function () {
  assert.equal(this.cognitoClient.EnableTokenRevocation, true);
  assert.equal(this.cognitoClient.RefreshTokenValidity, 30);
});

Then("the backend refuses to build the client", { timeout: 120_000 }, async function () {
  assert.deepEqual(await behaviour("client_refuses_unsafe_callback"), { refused: true });
});
