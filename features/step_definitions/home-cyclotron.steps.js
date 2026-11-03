const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-home-cyclotron.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

Given("a newsroom home page with synthetic classifier snapshots at 375 and 1440 pixels", function () { this.result = ""; });

// Each scenario's browser and unit checks live in scripts/test-home-cyclotron.ts; a Then step passes when its scenario's checks did.
When("the editor opens the home page and the classifier has retrained twice with 41 reviewed labels", { timeout: 240_000 }, async function () { this.result = (await run("words")) + (await run("states")) + (await run("snapshot")); this.scenario = "snapshot"; });
When("the editor opens the home page and the snapshot has no retraining, no last change and no reviewed labels", { timeout: 240_000 }, async function () { this.result = await run("never"); this.scenario = "never"; });
When("the editor opens the home page and the Cyclotron has not reported on this site's classifier yet", { timeout: 240_000 }, async function () { this.result = await run("sentences"); this.scenario = "sentences"; });
When("the editor opens a home page that has no classifier status source", { timeout: 240_000 }, async function () { this.result = await run("absent"); this.scenario = "absent"; });

const passes = (name) => function () { assert.ok(this.result.includes(`Home Cyclotron scenario passed: ${name}`), `${name} did not pass:\n${this.result}`); };
for (const text of [
  "the panel says the classifier was retrained twice and when it last changed",
  "the panel gives the agreement with reviewers as a percentage and says it was measured on the reviews the Cyclotron selected",
  "the panel counts the reviewed labels and the decisions awaiting review",
  "the panel says when the snapshot is from and that votes after it are not included yet",
  "the panel is in the top right of the header on a desktop and between the title and the list on a phone",
  "nothing in the panel has a border, every icon is a Lucide icon, it has no dropdown, and nothing scrolls sideways",
]) Then(text, passes("snapshot"));
for (const text of [
  "the panel says no retraining has happened yet",
  "the agreement says \"Not measured yet\" and shows no percentage",
  "no sentence in the panel implies that the classifier learned anything",
]) Then(text, passes("never"));
for (const text of [
  "the panel says the Cyclotron has not reported on this site's classifier yet, with no skeleton and no empty field",
  "when the status cannot be read the panel says so in one sentence and the feed is still shown",
  "while the status is being read the panel says it is being read",
]) Then(text, passes("sentences"));
Then("there is no classifier panel", passes("absent"));
