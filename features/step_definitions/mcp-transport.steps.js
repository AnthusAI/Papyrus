const { Given, When, Then } = require("@cucumber/cucumber");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const path = require("node:path");

// The seeded protocol harness makes real Request/Response exchanges without AWS.
let checks;
const run = () => checks ??= promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-mcp-transport.ts"], { cwd: path.resolve(__dirname, "../..") });
for (const step of [
  "a seeded publication with reader and staff tools", "a verified reader and a verified staff member",
  "a verified reader", "a seeded publication with MCP enabled", "MCP is disabled",
]) Given(step, function () {});
for (const step of [
  "an anonymous client lists or calls tools, even with a session identifier",
  "each lists tools and the reader calls a staff tool", "the client initializes and calls a permitted tool",
  "a client sends an untrusted Origin or unsupported protocol version", "a client attempts discovery",
]) When(step, function () {});
for (const step of [
  "the server challenges the client and reveals no tools or results",
  "each sees only their permitted tools and the reader's call is rejected",
  "the response contains the negotiated protocol version", "the result contains text and structured data",
  "the server rejects the request without invoking a tool", "accepted notifications have no response body",
  "a client cannot open an unsupported server event stream", "no tools are exposed",
]) Then(step, async function () { await run(); });
