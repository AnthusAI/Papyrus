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
Given("the content repository source", function () {});
Given("the news desk client source", function () {});
Given("the steering workspace source", function () {});
for (const when of [
  "it is read for schema probing and reduced-field queries",
  "it is read for how it authorizes a request",
  "it is read for how it handles a failed thread or message operation",
  "it is read for how it finds the newest published editions",
  "it is read for how it treats a layout block whose item did not load",
  "it is read for how it loads a page of References",
  "it is read for how it names a section and where its sections and proposals come from",
]) When(when, function () {});

// Each outcome is one test in scripts/test-no-fallbacks.ts.
const outcomes = [
  ["it runs no introspection query, keeps no legacy field set, and names every field of the message and thread queries once", /✔ console chat client: no schema probing/],
  ["every request uses the signed-in editor's credential and there is no retry under the public key", /✔ console chat client: one credential/],
  ["a failed create, update or list raises the backend's error and no thread is made up from messages or from the input", /✔ console chat client: failures are raised/],
  ["it asks the published-at index directly and never checks whether the index exists or falls back to the edition-date index", /✔ content repository: one edition index/],
  ["the plan is validated as written, no block is dropped with a warning, and no invented fallback image exists", /✔ content repository: a layout plan is validated as written/],
  ["each ordering and status filter reads its own index, an empty page is an empty page, and no table scan or older feed query takes over", /✔ news desk client: References come from their indexes/],
  ["a section shows its stored short title or its title, no table of section names is written into the engine, and the page does not borrow a second snapshot when the first is empty", /✔ newsroom sections: one source/],
];
for (const [then, pattern] of outcomes) Then(then, async function () { assert.match(await run(), pattern); });
