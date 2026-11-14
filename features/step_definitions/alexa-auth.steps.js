const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { When, Then } = require("@cucumber/cucumber");

// Each behaviour runs scripts/test-alexa-auth.ts, which asserts internally and prints the behaviour's name when it passes.
async function behaviour(name) {
  const result = await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-alexa-auth.ts", name], {
    cwd: path.resolve(__dirname, "../.."),
    maxBuffer: 8 * 1024 * 1024,
  });
  return JSON.parse(result.stdout.trim().split("\n").pop()).behaviour;
}

function when(text, name) {
  When(text, { timeout: 120_000 }, async function () {
    this.passed = [...(this.passed ?? []), await behaviour(name)];
  });
}

function then(text) {
  Then(text, function () {
    assert.ok(this.passed && this.passed.length > 0);
  });
}

when("a request carries a token signed by the pool's key for the skill's client", "a valid linked token is accepted");
then("the skill knows the user's identifier, username, email and groups");

when("a request carries no access token", "a request without a token is not signed in");
then("the skill treats it as signed out");

when("a request carries an expired token", "an expired token is refused");
when("a request carries a token for a different client", "a token for another client is refused");
when("a request carries a token from a different issuer", "a token from another issuer is refused");
when("a request carries an ID token instead of an access token", "an id token is refused as an access token");
when("a request carries a revoked or forged token", "a revoked or forged token is refused");

when("the Lambda environment does not name the pool and client", "without configuration every token is refused as not configured");
then("every token is refused as not configured");
when("the site turned account linking off", "the verifier exists only when account linking is on");
then("the skill has no token verifier");

when("a signed-in intent runs without a linked account", "a signed-out intent gets a link account card");
then("the response carries a link account card and tells the listener how to link");
then("a signed-in listener is not shown the card");
