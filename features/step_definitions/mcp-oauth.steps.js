const { Given, When, Then } = require("@cucumber/cucumber");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const path = require("node:path");
let checks;
const run = () => checks ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-mcp-oauth-http.ts"], { cwd: path.resolve(__dirname, "../..") });
for (const step of ["an MCP site with a configured public client", "signed-in staff and reader sessions", "a valid authorization request and a signed-in person"]) Given(step, function () {});
for (const step of ["the client reads OAuth metadata", "a request has an unregistered redirect or does not use S256", "a valid request is approved by a signed-in person", "a consent submission has an invalid transaction or origin", "each approves a valid client", "a signed-out reader attempts to approve the client", "the consent sealing secret is unavailable", "a person approves or denies a client request with state", "the consent form is submitted from the configured origin"]) When(step, function () {});
for (const step of ["the metadata names the configured site and its endpoints", "authorization is refused without issuing a code", "the client receives a code at its registered redirect", "the server sends its verified identity and expiry to the token service", "the reader can sign in and return to the pending consent", "metadata remains discoverable and consent reports how to recover", "the redirect carries the configured issuer and the original state", "the form permits the browser to send its origin without exposing cross-origin referrers", "a null or foreign origin cannot issue a code"]) Then(step, async function () { await run(); });
