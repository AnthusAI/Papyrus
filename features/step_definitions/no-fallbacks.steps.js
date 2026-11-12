const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-no-fallbacks.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};

Given("the console chat client source", function () {});
for (const when of [
  "it is read for schema probing and reduced-field queries",
  "it is read for how it authorizes a request",
  "it is read for how it handles a failed thread or message operation",
]) When(when, function () {});

// Each outcome is one test in scripts/test-no-fallbacks.ts.
const outcomes = [
  ["it runs no introspection query, keeps no legacy field set, and names every field of the message and thread queries once", /✔ console chat client: no schema probing/],
  ["every request uses the signed-in editor's credential and there is no retry under the public key", /✔ console chat client: one credential/],
  ["a failed create, update or list raises the backend's error and no thread is made up from messages or from the input", /✔ console chat client: failures are raised/],
];
for (const [then, pattern] of outcomes) Then(then, async function () { assert.match(await run(), pattern); });
