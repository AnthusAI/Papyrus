const assert = require("node:assert/strict");
const path = require("node:path");
const { execFile } = require("node:child_process");
const { promisify } = require("node:util");
const { Given, When, Then } = require("@cucumber/cucumber");

const root = path.resolve(__dirname, "../..");
const run = async (name) => (await promisify(execFile)(process.execPath, ["--import", "tsx", "scripts/test-home-cyclotron.ts", name], { cwd: root, maxBuffer: 8 * 1024 * 1024 })).stdout;

Given("a newsroom home page with synthetic classifier snapshots at 375 and 1440 pixels", function () { this.result = ""; });

// Each scenario's browser and unit checks live in scripts/test-home-cyclotron.ts; a Then step passes when its scenario's checks did.
When("the editor opens the home page and the classifier has cycled twice with 41 reviewed labels", { timeout: 240_000 }, async function () { this.result = (await run("words")) + (await run("states")) + (await run("snapshot")); this.scenario = "snapshot"; });
When("the editor opens the home page and the snapshot has no cycle, no last change and no reviewed labels", { timeout: 240_000 }, async function () { this.result = await run("never"); this.scenario = "never"; });
When("the editor opens the home page and the Cyclotron has not reported on this site's classifier yet", { timeout: 240_000 }, async function () { this.result = await run("sentences"); this.scenario = "sentences"; });
When("the editor opens a home page that has no classifier status source", { timeout: 240_000 }, async function () { this.result = await run("absent"); this.scenario = "absent"; });

When("the editor opens the home page and the Cyclotron's report has seven of nine compared votes over three days", { timeout: 240_000 }, async function () { this.result = (await run("report")) + (await run("reportPanel")); });
When("the editor opens the home page and expands the details of a classifier with a report", { timeout: 240_000 }, async function () { this.result = (await run("reportModel")) + (await run("reportPanel")) + (await run("reportLongPanel")); });
When("the editor opens the home page and the Cyclotron has a report but no status snapshot yet", { timeout: 240_000 }, async function () { this.result = (await run("reportZero")) + (await run("reportZeroPanel")); });
When("the editor opens the home page and the rows hold reports of several shapes", { timeout: 240_000 }, async function () { this.result = await run("reportParse"); });

const passes = (name) => function () { assert.ok(this.result.includes(`Home Cyclotron scenario passed: ${name}`), `${name} did not pass:\n${this.result}`); };
for (const text of [
  "the panel says the classifier has cycled twice and when it last changed",
  "the panel gives the agreement with reviewers as a percentage and says it was measured on the reviews the Cyclotron selected",
  "the panel counts the reviewed labels and the decisions awaiting review",
  "the panel says when the snapshot is from and that votes after it are not included yet",
  "the panel is in the top right of the header on a desktop and between the title and the list on a phone",
]) Then(text, passes("snapshot"));
// Shared by the snapshot and report scenarios: whichever browser scenario this one ran passed.
Then("nothing in the panel has a border, every icon is a Lucide icon, it has no dropdown, and nothing scrolls sideways", function () {
  const ran = this.result.includes("scenario passed: reportPanel") ? "reportPanel" : "snapshot";
  passes(ran).call(this);
});
for (const text of [
  "the panel says it has not cycled yet",
  "the agreement says \"Not measured yet\" and shows no percentage",
  "no sentence in the panel implies that the classifier learned anything",
]) Then(text, passes("never"));
for (const text of [
  "the panel says the Cyclotron has not reported on this site's classifier yet, with no skeleton and no empty field",
  "when the status cannot be read the panel says so in one sentence and the feed is still shown",
  "while the status is being read the panel says it is being read",
]) Then(text, passes("sentences"));
Then("there is no classifier panel", passes("absent"));
for (const text of [
  "the panel says the classifier is not learning from votes yet, with the report's reason, and when it last cycled",
  "the panel says \"7 of 9 compared\" for agreement with reviewers, never calls it accuracy and shows no percentage for it",
  "the panel lists the days newest first with the agreed of compared votes in words and a mark, and the classifier revisions",
  "the panel gives the held-out evaluation's reason when there is no number and a percentage when there is one",
  "the panel counts the labels, the reviewed decisions and the primed examples and keeps decisions awaiting review out of the top section",
]) Then(text, function () { passes("report").call(this); passes("reportPanel").call(this); });
for (const text of [
  "the details give the question, the classes and the rubric",
  "a classifier with no supporting questions says so in the report's own words and one with weights lists them",
  "decisions with no label filed in the engine are explained in words",
]) Then(text, function () { passes("reportModel").call(this); passes("reportPanel").call(this); });
Then("a very long rubric is folded and wraps when opened", passes("reportLongPanel"));
for (const text of [
  "the panel says \"Not compared yet\" for agreement with reviewers and never shows 0%",
  "the panel says it has not cycled yet and that there are no days with votes",
  "the panel says there is no snapshot yet and why, and the details say no decision has completed",
]) Then(text, function () { passes("reportZero").call(this); passes("reportZeroPanel").call(this); });
for (const text of [
  "a report with an unknown schema or a section out of shape is dropped, and the status beside it is kept",
  "a row with only a report is kept and a row with only a status is kept",
]) Then(text, passes("reportParse"));
