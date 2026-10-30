const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
let report;
const run = async () => {
  report ??= (await promisify(execFile)(process.execPath, ["--import", "tsx", "--test", "scripts/test-message-owner-schema.ts"], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;
  return report;
};

Given("the data API schema", function () {});
for (const when of ["the rules on Message are read", "the fields of Message are read", "the function grants and the other models are read"]) When(when, function () {});

// Each outcome is one test in scripts/test-message-owner-schema.ts, which reads the schema's transformed output.
const outcomes = [
  ["the author, matched on the sub claim in the authorSub field, can read, update and delete their own Messages", /✔ a Message's author can read/],
  ["no group can update a Message", /✔ editors and admins read and create; only an admin deletes/],
  ["editors and admins can read and create Messages", /✔ editors and admins read and create/],
  ["only admins can delete a Message they did not write", /✔ editors and admins read and create/],
  ["Message has editedAt, deletedAt and deletedBySub", /✔ a Message can record that it was edited/],
  ["the functions keep their grants and the assignment function can still create and update Messages", /✔ the owner rule is the only addition/],
  ["MessageThread has no owner rule", /✔ the owner rule is the only addition/],
  ["the typed schema carries the same rule and fields", /✔ the typed schema \(resource\.ts\) carries the same rule/],
];
for (const [then, pattern] of outcomes) Then(then, async function () { assert.match(await run(), pattern); });
